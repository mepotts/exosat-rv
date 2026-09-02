"""Synthetic-only tests for M38's signed one-way workflow ledger."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from exosat_rv.m38.provenance import canonical_json_bytes, canonical_sha256
from exosat_rv.m38.workflow import WorkflowError, WorkflowLedger, WorkflowStage

SCIENCE = "a" * 64
OTHER_SCIENCE = "b" * 64


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


ROLE_BINDINGS = {
    role: {
        "key_identity_sha256": digest(f"{role}-key"),
        "principal_identity_sha256": digest(f"{role}-principal"),
    }
    for role in (
        "protocol_freezer",
        "custodian",
        "blind_executor",
        "unblinding_reviewer",
    )
}
STAGE_ROLES = {
    "cancelled": "protocol_freezer",
    "frozen": "protocol_freezer",
    "search_complete": "blind_executor",
    "search_sealed": "blind_executor",
    "selection_complete": "blind_executor",
    "target_mounted": "custodian",
    "unblinded": "unblinding_reviewer",
    "validation_complete": "blind_executor",
    "winner_locked": "blind_executor",
}
STAGE_AUTHORIZATIONS = {
    stage: {
        "key_identity_sha256": ROLE_BINDINGS[role]["key_identity_sha256"],
        "principal_identity_sha256": ROLE_BINDINGS[role]["principal_identity_sha256"],
        "role": role,
    }
    for stage, role in STAGE_ROLES.items()
}
DECISION_CLAIMS = {
    "all_blocking_decisions_resolved": True,
    "frozen_arm_roster": [
        {"arm_id": "arm-01", "config_sha256": digest("config-arm-01")},
        {"arm_id": "arm-02", "config_sha256": digest("config-arm-02")},
    ],
    "register_structurally_valid": True,
    "replacement_preregistration_frozen": True,
    "role_bindings": ROLE_BINDINGS,
    "stage_authorizations": STAGE_AUTHORIZATIONS,
}
RUNTIME_CLAIMS = {
    "application_firewall_is_os_confinement": False,
    "dedicated_build_context_allowlist_verified": True,
    "deny_list_and_file_access_audit_verified": True,
    "network_disabled_enforced": True,
    "non_root_container_user_verified": True,
    "read_only_root_filesystem_enforced": True,
}


def transition_details(payload: bytes, *, key_identity_sha256: str | None = None):
    stage = json.loads(payload)["stage"]
    key_id = (
        STAGE_AUTHORIZATIONS[stage]["key_identity_sha256"]
        if key_identity_sha256 is None
        else key_identity_sha256
    )
    return {
        "algorithm": "external-detached-sha256-v1",
        "key_identity_sha256": key_id,
        "signature_sha256": hashlib.sha256(key_id.encode("ascii") + b"\0" + payload).hexdigest(),
    }


def transition_signer(payload: bytes):
    return transition_details(payload)


def transition_verifier(payload: bytes, details):
    if type(details) is not dict or set(details) != {
        "algorithm",
        "key_identity_sha256",
        "signature_sha256",
    }:
        return False
    if details["algorithm"] != "external-detached-sha256-v1":
        return False
    key_id = details["key_identity_sha256"]
    if type(key_id) is not str:
        return False
    expected = hashlib.sha256(key_id.encode("ascii") + b"\0" + payload).hexdigest()
    return details["signature_sha256"] == expected


def reseal_record(record, *, key_identity_sha256=None):
    payload_fields = {
        "input_identity_sha256",
        "output",
        "prior_record_sha256",
        "retry_of_record_sha256",
        "schema_version",
        "scientific_identity_sha256",
        "sequence",
        "stage",
        "status",
        "workflow_id",
    }
    payload = {key: record[key] for key in payload_fields}
    payload_bytes = canonical_json_bytes(payload)
    record["integrity"] = {
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "signature": {
            "details": transition_details(
                payload_bytes,
                key_identity_sha256=key_identity_sha256,
            ),
            "signed_content_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "status": "signed",
        },
    }
    body = dict(record)
    body.pop("record_sha256", None)
    record["record_sha256"] = canonical_sha256(body)


def gate_attestation(kind: str, *, signature_nonce: str = "default-encoding"):
    claims = DECISION_CLAIMS if kind == "decision_register" else RUNTIME_CLAIMS
    attestation = {
        "claims": deepcopy(claims),
        "complete": True,
        "evidence_sha256": digest(f"{kind}-evidence"),
        "independent_review_sha256": digest(f"{kind}-review"),
        "kind": kind,
        "schema_version": 1,
        "structurally_valid": True,
        "subject_sha256": digest(f"{kind}-subject"),
    }
    attestation["signature"] = {
        "algorithm": "sha256-test-only",
        "body_sha256": canonical_sha256(attestation),
        "encoding_nonce": signature_nonce,
    }
    return attestation


def gate_verifier(kind: str, attestation):
    if attestation.get("kind") != kind:
        return False
    body = deepcopy(attestation)
    signature = body.pop("signature", None)
    return bool(
        type(signature) is dict
        and set(signature) == {"algorithm", "body_sha256", "encoding_nonce"}
        and signature["algorithm"] == "sha256-test-only"
        and signature["body_sha256"] == canonical_sha256(body)
        and type(signature["encoding_nonce"]) is str
        and signature["encoding_nonce"]
    )


def reseal_gate_attestation(attestation, *, signature_nonce="resealed-encoding"):
    body = deepcopy(attestation)
    body.pop("signature", None)
    attestation["signature"] = {
        "algorithm": "sha256-test-only",
        "body_sha256": canonical_sha256(body),
        "encoding_nonce": signature_nonce,
    }


def failure_attestation(
    ledger,
    stage,
    *,
    failure_kind,
    failure_code,
    input_identity_sha256,
    scientific_identity_sha256=SCIENCE,
):
    head = ledger.records[-1]
    attestation = {
        "diagnostic_sha256": digest(f"{stage.value}-diagnostic"),
        "evidence_sha256": digest(f"{stage.value}-failure-evidence"),
        "expected_prior_record_sha256": head["record_sha256"],
        "expected_record_sequence": head["sequence"] + 1,
        "failure_code": failure_code,
        "failure_kind": failure_kind,
        "independent_review_sha256": digest(f"{stage.value}-failure-review"),
        "input_identity_sha256": input_identity_sha256,
        "schema_version": 1,
        "scientific_identity_sha256": scientific_identity_sha256,
        "stage": stage.value,
        "workflow_id": ledger.snapshot.workflow_id,
    }
    attestation["signature"] = {
        "algorithm": "external-detached-sha256-v1",
        "key_identity_sha256": digest("failure-attestation-key"),
        "signature_sha256": canonical_sha256(attestation),
    }
    return attestation


def failure_verifier(attestation):
    body = deepcopy(attestation)
    signature = body.pop("signature", None)
    return signature == {
        "algorithm": "external-detached-sha256-v1",
        "key_identity_sha256": digest("failure-attestation-key"),
        "signature_sha256": canonical_sha256(body),
    }


def reseal_failure_attestation(attestation):
    body = deepcopy(attestation)
    body.pop("signature", None)
    attestation["signature"] = {
        "algorithm": "external-detached-sha256-v1",
        "key_identity_sha256": digest("failure-attestation-key"),
        "signature_sha256": canonical_sha256(body),
    }


class MemoryWorkflowStore:
    """Test-only CAS store modelling an externally controlled durable head."""

    def __init__(self):
        self._records = {}

    def append_exclusive(self, workflow_id, expected_sequence, expected_sha256, record):
        if record["workflow_id"] != workflow_id:
            return False
        chain = self._records.setdefault(workflow_id, [])
        if chain:
            current = chain[-1]
            if (
                current["sequence"] != expected_sequence
                or current["record_sha256"] != expected_sha256
                or record["sequence"] != expected_sequence + 1
                or record["prior_record_sha256"] != expected_sha256
            ):
                return False
        elif (
            expected_sequence is not None
            or expected_sha256 is not None
            or record["sequence"] != 0
            or record["prior_record_sha256"] is not None
        ):
            return False
        chain.append(deepcopy(record))
        return True

    def verify_head(self, workflow_id, sequence, record_sha256):
        chain = self._records.get(workflow_id, [])
        return bool(
            chain
            and chain[-1]["sequence"] == sequence
            and chain[-1]["record_sha256"] == record_sha256
        )


def ledger_restore_arguments(store):
    return {
        "signer": transition_signer,
        "signature_verifier": transition_verifier,
        "gate_attestation_verifier": gate_verifier,
        "failure_attestation_verifier": failure_verifier,
        "durable_head_verifier": store.verify_head,
        "exclusive_append_committer": store.append_exclusive,
    }


def make_ledger(*, store=None, **overrides):
    store = MemoryWorkflowStore() if store is None else store
    arguments = {
        "decision_register_attestation": gate_attestation("decision_register"),
        "runtime_audit_attestation": gate_attestation("runtime_audit"),
        "scientific_identity_sha256": SCIENCE,
        "signer": transition_signer,
        "signature_verifier": transition_verifier,
        "gate_attestation_verifier": gate_verifier,
        "failure_attestation_verifier": failure_verifier,
        "durable_head_verifier": store.verify_head,
        "exclusive_append_committer": store.append_exclusive,
    }
    arguments.update(overrides)
    return WorkflowLedger.create(**arguments)


def mount_output():
    return {
        "mount_manifest_sha256": digest("mount-manifest"),
        "mounted_by_role_sha256": ROLE_BINDINGS["custodian"]["principal_identity_sha256"],
        "read_only": True,
    }


def selection_output(winner="arm-01"):
    return {
        "eligible_arm_ids": ["arm-01", "arm-02"],
        "selection_artifact_sha256": digest("selection"),
        "winner_id": winner,
    }


def lock_output(winner="arm-01"):
    return {
        "hidden_validation_plan_sha256": digest("hidden-plan"),
        "winner_config_sha256": digest(f"config-{winner}"),
        "winner_id": winner,
    }


def validation_output(winner="arm-01"):
    return {
        "hidden_validation_plan_sha256": digest("hidden-plan"),
        "passed": True,
        "validation_artifact_sha256": digest("validation"),
        "winner_config_sha256": digest(f"config-{winner}"),
        "winner_id": winner,
    }


def search_output(winner="arm-01"):
    return {
        "global_calibration_sha256": digest("calibration"),
        "hidden_validation_plan_sha256": digest("hidden-plan"),
        "search_artifact_sha256": digest("search"),
        "winner_config_sha256": digest(f"config-{winner}"),
        "winner_id": winner,
    }


def advance(ledger, stage, output, label):
    return ledger.advance(
        stage,
        output,
        input_identity_sha256=digest(label),
        scientific_identity_sha256=SCIENCE,
    )


def through_selection(ledger):
    advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")
    advance(ledger, WorkflowStage.SELECTION_COMPLETE, selection_output(), "selection-input")


def through_validation(ledger):
    through_selection(ledger)
    advance(ledger, WorkflowStage.WINNER_LOCKED, lock_output(), "lock-input")
    advance(
        ledger,
        WorkflowStage.VALIDATION_COMPLETE,
        validation_output(),
        "validation-input",
    )


@pytest.mark.parametrize("kind", ["decision_register", "runtime_audit"])
def test_incomplete_or_structurally_invalid_attestation_blocks_freeze(kind):
    bad = gate_attestation(kind)
    bad["complete"] = False
    reseal_gate_attestation(bad)
    key = f"{kind}_attestation"

    with pytest.raises(WorkflowError, match="incomplete or structurally invalid"):
        make_ledger(**{key: bad})


def test_runtime_claim_cannot_treat_application_firewall_as_os_confinement():
    runtime = gate_attestation("runtime_audit")
    runtime["claims"]["application_firewall_is_os_confinement"] = True
    reseal_gate_attestation(runtime)

    with pytest.raises(WorkflowError, match="unsafe claims"):
        make_ledger(runtime_audit_attestation=runtime)


def test_attestation_and_transition_verifiers_must_return_exact_true():
    with pytest.raises(WorkflowError, match="attestation verification failed"):
        make_ledger(gate_attestation_verifier=lambda _kind, _value: 1)

    with pytest.raises(WorkflowError, match="signature verification failed"):
        make_ledger(signature_verifier=lambda _payload, _details: 1)


def test_randomized_gate_signatures_share_one_cas_genesis_namespace():
    first_decision = gate_attestation("decision_register", signature_nonce="encoding-one")
    second_decision = gate_attestation("decision_register", signature_nonce="encoding-two")
    first_runtime = gate_attestation("runtime_audit", signature_nonce="encoding-three")
    second_runtime = gate_attestation("runtime_audit", signature_nonce="encoding-four")

    first = make_ledger(
        decision_register_attestation=first_decision,
        runtime_audit_attestation=first_runtime,
    )
    second = make_ledger(
        decision_register_attestation=second_decision,
        runtime_audit_attestation=second_runtime,
    )
    assert first.snapshot.workflow_id == second.snapshot.workflow_id

    shared_store = MemoryWorkflowStore()
    make_ledger(
        store=shared_store,
        decision_register_attestation=first_decision,
        runtime_audit_attestation=first_runtime,
    )
    with pytest.raises(WorkflowError, match="refused exclusive workflow creation"):
        make_ledger(
            store=shared_store,
            decision_register_attestation=second_decision,
            runtime_audit_attestation=second_runtime,
        )


def test_decision_claims_require_bounded_roster_and_distinct_role_keys():
    decision = gate_attestation("decision_register")
    decision["claims"]["frozen_arm_roster"] = [
        {"arm_id": f"arm-{index}", "config_sha256": digest(f"config-{index}")}
        for index in range(1025)
    ]
    reseal_gate_attestation(decision)
    with pytest.raises(WorkflowError, match="explicitly bounded"):
        make_ledger(decision_register_attestation=decision)

    decision = gate_attestation("decision_register")
    shared_key = digest("one-key-for-all-roles")
    for binding in decision["claims"]["role_bindings"].values():
        binding["key_identity_sha256"] = shared_key
    for authorization in decision["claims"]["stage_authorizations"].values():
        authorization["key_identity_sha256"] = shared_key
    reseal_gate_attestation(decision)
    with pytest.raises(WorkflowError, match="distinct frozen signing keys"):
        make_ledger(decision_register_attestation=decision)


def test_frozen_arm_labels_cannot_disguise_duplicate_configuration_identities():
    decision = gate_attestation("decision_register")
    duplicate_config = decision["claims"]["frozen_arm_roster"][0]["config_sha256"]
    decision["claims"]["frozen_arm_roster"][1]["config_sha256"] = duplicate_config
    reseal_gate_attestation(decision)

    with pytest.raises(WorkflowError, match="configuration identities must be unique"):
        make_ledger(decision_register_attestation=decision)


def test_cryptographically_valid_wrong_stage_signer_is_rejected():
    wrong_key = ROLE_BINDINGS["blind_executor"]["key_identity_sha256"]

    with pytest.raises(WorkflowError, match="not authorized for stage frozen"):
        make_ledger(
            signer=lambda payload: transition_details(
                payload,
                key_identity_sha256=wrong_key,
            )
        )

    def wrong_mount_signer(payload):
        stage = json.loads(payload)["stage"]
        if stage == WorkflowStage.TARGET_MOUNTED.value:
            return transition_details(
                payload,
                key_identity_sha256=ROLE_BINDINGS["protocol_freezer"]["key_identity_sha256"],
            )
        return transition_details(payload)

    ledger = make_ledger(signer=wrong_mount_signer)
    with pytest.raises(WorkflowError, match="not authorized for stage target_mounted"):
        advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")


def test_genesis_is_signed_hash_linked_and_caller_cannot_mutate_it():
    ledger = make_ledger()
    exposed = ledger.records
    exposed[0]["output"]["decision_register_attestation"]["complete"] = False

    assert ledger.snapshot.stage is WorkflowStage.FROZEN
    assert ledger.snapshot.next_stage is WorkflowStage.TARGET_MOUNTED
    assert ledger.records[0]["output"]["decision_register_attestation"]["complete"] is True
    assert ledger.records[0]["integrity"]["signature"]["status"] == "signed"


def test_stage_order_and_exact_output_schemas_enforce_information_barriers():
    ledger = make_ledger()
    with pytest.raises(WorkflowError, match="next stage is target_mounted"):
        advance(ledger, WorkflowStage.UNBLINDED, {}, "early-unblind")

    unsafe = mount_output() | {"period_diagnostic": [1, 2, 3]}
    with pytest.raises(WorkflowError, match="output schema mismatch"):
        advance(ledger, WorkflowStage.TARGET_MOUNTED, unsafe, "mount-input")
    assert ledger.snapshot.stage is WorkflowStage.FROZEN


def test_full_happy_path_requires_winner_validation_search_seal_then_unblind():
    ledger = make_ledger()
    through_validation(ledger)
    advance(ledger, WorkflowStage.SEARCH_COMPLETE, search_output(), "search-input")
    advance(
        ledger,
        WorkflowStage.SEARCH_SEALED,
        {
            "sealed_artifact_sha256": digest("sealed-search"),
            "sealed_at": "2030-01-01T00:00:00Z",
            "search_artifact_sha256": digest("search"),
        },
        "seal-input",
    )
    advance(
        ledger,
        WorkflowStage.UNBLINDED,
        {
            "comparison_artifact_sha256": digest("comparison"),
            "reviewer_identity_sha256": ROLE_BINDINGS["unblinding_reviewer"][
                "principal_identity_sha256"
            ],
            "sealed_artifact_sha256": digest("sealed-search"),
        },
        "unblind-input",
    )

    assert ledger.snapshot.stage is WorkflowStage.UNBLINDED
    assert ledger.snapshot.next_stage is None
    records = ledger.records
    for index in range(1, len(records)):
        assert records[index]["prior_record_sha256"] == records[index - 1]["record_sha256"]


def test_runner_up_substitution_is_rejected_at_lock_and_later_stages():
    ledger = make_ledger()
    through_selection(ledger)
    with pytest.raises(WorkflowError, match="runner-up substitution"):
        advance(ledger, WorkflowStage.WINNER_LOCKED, lock_output("arm-02"), "lock-input")
    assert ledger.snapshot.stage is WorkflowStage.SELECTION_COMPLETE

    advance(ledger, WorkflowStage.WINNER_LOCKED, lock_output(), "lock-input")
    with pytest.raises(WorkflowError, match="locked winner"):
        advance(
            ledger,
            WorkflowStage.VALIDATION_COMPLETE,
            validation_output("arm-02"),
            "validation-input",
        )


def test_selection_and_lock_are_bounded_by_the_exact_frozen_arm_roster():
    ledger = make_ledger()
    advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")
    invented = selection_output()
    invented["eligible_arm_ids"].append("arm-invented-after-freeze")
    with pytest.raises(WorkflowError, match="drawn from the frozen roster"):
        advance(ledger, WorkflowStage.SELECTION_COMPLETE, invented, "selection-input")

    advance(ledger, WorkflowStage.SELECTION_COMPLETE, selection_output(), "selection-input")
    changed_config = lock_output() | {"winner_config_sha256": digest("invented-config")}
    with pytest.raises(WorkflowError, match="configuration does not match the frozen arm roster"):
        advance(ledger, WorkflowStage.WINNER_LOCKED, changed_config, "lock-input")


def test_role_output_hashes_must_name_the_frozen_custodian_and_reviewer():
    ledger = make_ledger()
    spoofed_mount = mount_output() | {"mounted_by_role_sha256": digest("spoofed-custodian")}
    with pytest.raises(WorkflowError, match="frozen custodian principal"):
        advance(ledger, WorkflowStage.TARGET_MOUNTED, spoofed_mount, "mount-input")

    ledger = make_ledger()
    through_validation(ledger)
    advance(ledger, WorkflowStage.SEARCH_COMPLETE, search_output(), "search-input")
    advance(
        ledger,
        WorkflowStage.SEARCH_SEALED,
        {
            "sealed_artifact_sha256": digest("sealed-search"),
            "sealed_at": "2030-01-01T00:00:00Z",
            "search_artifact_sha256": digest("search"),
        },
        "seal-input",
    )
    with pytest.raises(WorkflowError, match="frozen unblinding reviewer principal"):
        advance(
            ledger,
            WorkflowStage.UNBLINDED,
            {
                "comparison_artifact_sha256": digest("comparison"),
                "reviewer_identity_sha256": digest("spoofed-reviewer"),
                "sealed_artifact_sha256": digest("sealed-search"),
            },
            "unblind-input",
        )


def test_failed_hidden_validation_is_terminal_and_cannot_select_runner_up():
    ledger = make_ledger()
    through_selection(ledger)
    advance(ledger, WorkflowStage.WINNER_LOCKED, lock_output(), "lock-input")

    invalid = validation_output() | {"passed": False}
    with pytest.raises(WorkflowError, match="must stop"):
        advance(
            ledger,
            WorkflowStage.VALIDATION_COMPLETE,
            invalid,
            "validation-input",
        )
    ledger.fail_next_stage(
        failure_attestation=failure_attestation(
            ledger,
            WorkflowStage.VALIDATION_COMPLETE,
            failure_kind="scientific",
            failure_code="winner_validation_failure",
            input_identity_sha256=digest("validation-input"),
        ),
        input_identity_sha256=digest("validation-input"),
        scientific_identity_sha256=SCIENCE,
    )
    assert ledger.snapshot.stage is WorkflowStage.CANCELLED
    assert ledger.snapshot.next_stage is None
    with pytest.raises(WorkflowError, match="terminal"):
        advance(ledger, WorkflowStage.SEARCH_COMPLETE, search_output("arm-02"), "search-input")


def test_infrastructure_retry_requires_content_identical_input():
    ledger = make_ledger()
    failed = ledger.fail_next_stage(
        failure_attestation=failure_attestation(
            ledger,
            WorkflowStage.TARGET_MOUNTED,
            failure_kind="infrastructure",
            failure_code="runtime_interruption",
            input_identity_sha256=digest("mount-input"),
        ),
        input_identity_sha256=digest("mount-input"),
        scientific_identity_sha256=SCIENCE,
    )
    assert ledger.snapshot.pending_retry_stage is WorkflowStage.TARGET_MOUNTED
    with pytest.raises(WorkflowError, match="use retry_content_identical"):
        advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")

    retry = ledger.retry_content_identical(
        mount_output(),
        input_identity_sha256=digest("mount-input"),
        scientific_identity_sha256=SCIENCE,
    )
    assert retry["retry_of_record_sha256"] == failed["record_sha256"]
    assert ledger.snapshot.stage is WorkflowStage.TARGET_MOUNTED


def test_changed_retry_input_or_scientific_identity_cancels_instead_of_revising():
    ledger = make_ledger()
    ledger.fail_next_stage(
        failure_attestation=failure_attestation(
            ledger,
            WorkflowStage.TARGET_MOUNTED,
            failure_kind="infrastructure",
            failure_code="runtime_interruption",
            input_identity_sha256=digest("mount-input"),
        ),
        input_identity_sha256=digest("mount-input"),
        scientific_identity_sha256=SCIENCE,
    )
    cancellation = ledger.retry_content_identical(
        mount_output(),
        input_identity_sha256=digest("changed-mount-input"),
        scientific_identity_sha256=SCIENCE,
    )
    assert cancellation["stage"] == WorkflowStage.CANCELLED.value
    assert ledger.snapshot.stage is WorkflowStage.CANCELLED

    ledger = make_ledger()
    cancellation = ledger.advance(
        WorkflowStage.TARGET_MOUNTED,
        mount_output(),
        input_identity_sha256=digest("mount-input"),
        scientific_identity_sha256=OTHER_SCIENCE,
    )
    assert cancellation["output"]["proposed_scientific_identity_sha256"] == OTHER_SCIENCE
    assert ledger.snapshot.stage is WorkflowStage.CANCELLED


def test_tampered_serialised_ledger_fails_hash_and_signature_verification():
    store = MemoryWorkflowStore()
    ledger = make_ledger(store=store)
    records = list(ledger.records)
    records[0]["input_identity_sha256"] = digest("tampered")

    with pytest.raises(WorkflowError, match="self-hash mismatch"):
        WorkflowLedger(
            records,
            **ledger_restore_arguments(store),
        )

    records = list(ledger.records)
    records[0]["integrity"]["signature"]["details"]["signature_sha256"] = digest("forged")
    body = dict(records[0])
    body.pop("record_sha256")
    records[0]["record_sha256"] = canonical_sha256(body)
    with pytest.raises(WorkflowError, match="signature verification failed"):
        WorkflowLedger(
            records,
            **ledger_restore_arguments(store),
        )


def test_even_self_consistently_signed_records_require_strict_native_sequence_types():
    store = MemoryWorkflowStore()
    ledger = make_ledger(store=store)
    records = list(ledger.records)
    records[0]["sequence"] = False
    reseal_record(records[0])

    with pytest.raises(WorkflowError, match="sequence must be a non-negative native integer"):
        WorkflowLedger(
            records,
            **ledger_restore_arguments(store),
        )


def test_output_and_attestations_reject_non_native_json_values():
    class TextSubclass(str):
        pass

    ledger = make_ledger()
    unsafe = mount_output()
    unsafe["mounted_by_role_sha256"] = TextSubclass(digest("role"))
    with pytest.raises(WorkflowError, match="strict native JSON"):
        advance(ledger, WorkflowStage.TARGET_MOUNTED, unsafe, "mount-input")

    attestation = gate_attestation("decision_register")
    attestation["kind"] = TextSubclass("decision_register")
    with pytest.raises(WorkflowError, match="strict native JSON"):
        make_ledger(decision_register_attestation=attestation)


def test_transition_signature_binds_exact_payload_bytes():
    ledger = make_ledger()
    record = ledger.records[0]
    payload_fields = {
        "input_identity_sha256",
        "output",
        "prior_record_sha256",
        "retry_of_record_sha256",
        "schema_version",
        "scientific_identity_sha256",
        "sequence",
        "stage",
        "status",
        "workflow_id",
    }
    payload = {key: record[key] for key in payload_fields}
    payload_bytes = canonical_json_bytes(payload)
    assert record["integrity"]["payload_sha256"] == hashlib.sha256(payload_bytes).hexdigest()
    assert transition_verifier(payload_bytes, record["integrity"]["signature"]["details"])


@pytest.mark.parametrize(
    "bad_details",
    [
        {
            "algorithm": "external-detached-sha256-v1",
            "key_identity_sha256": "1" * 64,
            "note": "free text is forbidden",
            "signature_sha256": "2" * 64,
        },
        {
            "algorithm": "caller-selected-algorithm",
            "key_identity_sha256": "1" * 64,
            "signature_sha256": "2" * 64,
        },
        {
            "algorithm": "external-detached-sha256-v1",
            "key_identity_sha256": "not-a-hash",
            "signature_sha256": "2" * 64,
        },
    ],
)
def test_transition_signatures_have_one_fixed_hash_only_schema(bad_details):
    with pytest.raises(WorkflowError, match="fixed hash-only|fixed external|SHA-256"):
        make_ledger(signer=lambda _payload: bad_details)


@pytest.mark.parametrize(
    "sealed_at",
    [
        "2030-01-01T00:00:00+00:00",
        "2030-01-01T00:00:00.000Z",
        "2030-01-01t00:00:00z",
        "2030-02-30T00:00:00Z",
    ],
)
def test_search_seal_requires_one_canonical_utc_representation(sealed_at):
    ledger = make_ledger()
    through_validation(ledger)
    advance(ledger, WorkflowStage.SEARCH_COMPLETE, search_output(), "search-input")

    with pytest.raises(WorkflowError, match="canonical YYYY-MM-DDTHH:MM:SSZ UTC"):
        advance(
            ledger,
            WorkflowStage.SEARCH_SEALED,
            {
                "sealed_artifact_sha256": digest("sealed-search"),
                "sealed_at": sealed_at,
                "search_artifact_sha256": digest("search"),
            },
            "seal-input",
        )
    assert ledger.snapshot.stage is WorkflowStage.SEARCH_COMPLETE


@pytest.mark.parametrize("verification_result", [False, 1])
def test_failures_require_independently_verified_exact_hash_only_attestations(
    verification_result,
):
    ledger = make_ledger(failure_attestation_verifier=lambda _attestation: verification_result)
    attestation = failure_attestation(
        ledger,
        WorkflowStage.TARGET_MOUNTED,
        failure_kind="infrastructure",
        failure_code="runtime_interruption",
        input_identity_sha256=digest("mount-input"),
    )
    with pytest.raises(WorkflowError, match="attestation verification failed"):
        ledger.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("mount-input"),
            scientific_identity_sha256=SCIENCE,
        )
    assert ledger.snapshot.stage is WorkflowStage.FROZEN

    ledger = make_ledger()
    attestation["failure_reason"] = "free-text diagnostic"
    reseal_failure_attestation(attestation)
    with pytest.raises(WorkflowError, match="exact fixed schema"):
        ledger.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("mount-input"),
            scientific_identity_sha256=SCIENCE,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stage", WorkflowStage.SELECTION_COMPLETE.value, "expected stage"),
        ("input_identity_sha256", "f" * 64, "stage input identity"),
        ("scientific_identity_sha256", OTHER_SCIENCE, "scientific identity"),
        ("failure_code", "caller_selected_reason", "code is not allowed"),
    ],
)
def test_failure_attestation_must_bind_stage_input_science_and_fixed_code(field, value, message):
    ledger = make_ledger()
    attestation = failure_attestation(
        ledger,
        WorkflowStage.TARGET_MOUNTED,
        failure_kind="infrastructure",
        failure_code="runtime_interruption",
        input_identity_sha256=digest("mount-input"),
    )
    attestation[field] = value
    reseal_failure_attestation(attestation)

    with pytest.raises(WorkflowError, match=message):
        ledger.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("mount-input"),
            scientific_identity_sha256=SCIENCE,
        )


def test_failure_attestation_cannot_replay_across_workflow_namespaces():
    source = make_ledger()
    attestation = failure_attestation(
        source,
        WorkflowStage.TARGET_MOUNTED,
        failure_kind="infrastructure",
        failure_code="runtime_interruption",
        input_identity_sha256=digest("mount-input"),
    )

    different_decision = gate_attestation("decision_register")
    different_decision["subject_sha256"] = digest("different-register-subject")
    reseal_gate_attestation(different_decision)
    destination = make_ledger(decision_register_attestation=different_decision)
    with pytest.raises(WorkflowError, match="workflow namespace"):
        destination.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("mount-input"),
            scientific_identity_sha256=SCIENCE,
        )


def test_failure_attestation_cannot_replay_from_a_different_durable_head():
    source = make_ledger()
    destination = make_ledger()
    advance(source, WorkflowStage.TARGET_MOUNTED, mount_output(), "source-mount-input")
    advance(destination, WorkflowStage.TARGET_MOUNTED, mount_output(), "other-mount-input")
    assert source.snapshot.workflow_id == destination.snapshot.workflow_id
    assert source.records[-1]["record_sha256"] != destination.records[-1]["record_sha256"]

    attestation = failure_attestation(
        source,
        WorkflowStage.SELECTION_COMPLETE,
        failure_kind="infrastructure",
        failure_code="runtime_interruption",
        input_identity_sha256=digest("selection-input"),
    )
    with pytest.raises(WorkflowError, match="expected prior durable head"):
        destination.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("selection-input"),
            scientific_identity_sha256=SCIENCE,
        )


def test_failure_attestation_record_sequence_is_exact_and_native():
    ledger = make_ledger()
    attestation = failure_attestation(
        ledger,
        WorkflowStage.TARGET_MOUNTED,
        failure_kind="infrastructure",
        failure_code="runtime_interruption",
        input_identity_sha256=digest("mount-input"),
    )
    attestation["expected_record_sequence"] = False
    reseal_failure_attestation(attestation)
    with pytest.raises(WorkflowError, match="expected record sequence"):
        ledger.fail_next_stage(
            failure_attestation=attestation,
            input_identity_sha256=digest("mount-input"),
            scientific_identity_sha256=SCIENCE,
        )


def test_cancellation_records_expose_only_fixed_codes_and_hashes():
    ledger = make_ledger()
    cancellation = ledger.advance(
        WorkflowStage.TARGET_MOUNTED,
        mount_output(),
        input_identity_sha256=digest("mount-input"),
        scientific_identity_sha256=OTHER_SCIENCE,
    )

    assert set(cancellation["output"]) == {
        "attempted_stage",
        "cancellation_code",
        "diagnostic_sha256",
        "frozen_scientific_identity_sha256",
        "proposed_scientific_identity_sha256",
    }
    assert cancellation["output"]["cancellation_code"] == "scientific_identity_changed"
    assert len(cancellation["output"]["diagnostic_sha256"]) == 64


def test_locked_config_and_hidden_plan_hashes_must_survive_validation_and_search():
    ledger = make_ledger()
    through_selection(ledger)
    advance(ledger, WorkflowStage.WINNER_LOCKED, lock_output(), "lock-input")

    changed_config = validation_output() | {"winner_config_sha256": digest("changed-config")}
    with pytest.raises(WorkflowError, match="configuration hash changed"):
        advance(
            ledger,
            WorkflowStage.VALIDATION_COMPLETE,
            changed_config,
            "validation-input",
        )
    changed_plan = validation_output() | {"hidden_validation_plan_sha256": digest("changed-plan")}
    with pytest.raises(WorkflowError, match="validation plan hash changed"):
        advance(
            ledger,
            WorkflowStage.VALIDATION_COMPLETE,
            changed_plan,
            "validation-input",
        )

    advance(
        ledger,
        WorkflowStage.VALIDATION_COMPLETE,
        validation_output(),
        "validation-input",
    )
    changed_search = search_output() | {
        "hidden_validation_plan_sha256": digest("changed-search-plan")
    }
    with pytest.raises(WorkflowError, match="validation plan hash changed"):
        advance(ledger, WorkflowStage.SEARCH_COMPLETE, changed_search, "search-input")


def test_durable_head_rejects_restoration_from_a_valid_signed_prefix():
    store = MemoryWorkflowStore()
    ledger = make_ledger(store=store)
    signed_prefix = ledger.records
    advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")

    with pytest.raises(WorkflowError, match="stale, truncated, or rolled-back"):
        WorkflowLedger(signed_prefix, **ledger_restore_arguments(store))

    restored = WorkflowLedger(ledger.records, **ledger_restore_arguments(store))
    assert restored.snapshot.stage is WorkflowStage.TARGET_MOUNTED


def test_exclusive_store_rejects_duplicate_creation_and_stale_concurrent_append():
    store = MemoryWorkflowStore()
    ledger = make_ledger(store=store)
    with pytest.raises(WorkflowError, match="refused exclusive workflow creation"):
        make_ledger(store=store)

    peer = WorkflowLedger(ledger.records, **ledger_restore_arguments(store))
    advance(ledger, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")
    with pytest.raises(WorkflowError, match="stale, truncated, or rolled-back"):
        advance(peer, WorkflowStage.TARGET_MOUNTED, mount_output(), "mount-input")


def test_durable_callbacks_must_report_exact_true():
    store = MemoryWorkflowStore()
    with pytest.raises(WorkflowError, match="refused exclusive workflow creation"):
        make_ledger(
            store=store,
            exclusive_append_committer=lambda _workflow, _sequence, _head, _record: 1,
        )

    store = MemoryWorkflowStore()
    with pytest.raises(WorkflowError, match="did not verify the committed genesis head"):
        make_ledger(
            store=store,
            durable_head_verifier=lambda _workflow, _sequence, _head: 1,
        )
