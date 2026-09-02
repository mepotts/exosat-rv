"""Fail-closed, signed stage orchestration for a future M38 execution.

The workflow is intentionally generic and target-free.  It records one-way transitions and
enforces output schemas, but it neither mounts data nor runs scientific code.  External code
must perform those operations and submit only content identities to this ledger.

Decision-register and runtime-audit integration uses a narrow attestation/callback boundary so
this module does not depend on a particular register implementation.  Attestation booleans are
*structural evidence fields*, not human or scientific approval.  The callback must independently
verify their signature and evidence lineage.  A current application firewall is never accepted
as operating-system confinement.  Failure classification likewise comes only from a fixed-schema
attestation accepted by an independently controlled verifier, never from an operator assertion.

Rollback protection depends on external durable-record-inclusion and exact-head verifiers plus
an atomic compare-and-append committer.  The in-process object is not itself durable storage and
cannot make caller-owned callbacks independent or trustworthy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .provenance import ProvenanceError, canonical_json_bytes, canonical_sha256

WORKFLOW_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_MAX_FROZEN_ARM_COUNT = 1024

TransitionSigner = Callable[[bytes], Mapping[str, Any]]
TransitionSignatureVerifier = Callable[[bytes, Mapping[str, Any]], bool]
GateAttestationVerifier = Callable[[str, Mapping[str, Any]], bool]
FailureAttestationVerifier = Callable[[Mapping[str, Any]], bool]
DurableHeadVerifier = Callable[[str, int, str], bool]
DurableRecordVerifier = Callable[[str, int, str], bool]
ExclusiveAppendCommitter = Callable[[str, int | None, str | None, Mapping[str, Any]], bool]

_TRANSITION_SIGNATURE_ALGORITHM = "external-detached-sha256-v1"
_TRANSITION_SIGNATURE_FIELDS = frozenset({"algorithm", "key_identity_sha256", "signature_sha256"})
_FAILURE_ATTESTATION_FIELDS = frozenset(
    {
        "diagnostic_sha256",
        "evidence_sha256",
        "failure_code",
        "failure_kind",
        "independent_review_sha256",
        "input_identity_sha256",
        "expected_prior_record_sha256",
        "expected_record_sequence",
        "schema_version",
        "scientific_identity_sha256",
        "signature",
        "stage",
        "workflow_id",
    }
)
_INFRASTRUCTURE_FAILURE_CODES = frozenset(
    {
        "input_unavailable",
        "manifest_io_failure",
        "runtime_interruption",
    }
)
_SCIENTIFIC_FAILURE_CODES = frozenset(
    {
        "calibration_gate_failure",
        "no_eligible_winner",
        "scientific_gate_failure",
        "winner_validation_failure",
    }
)
_CANCELLATION_CODES = frozenset(
    {
        "retry_identity_changed",
        "scientific_change_declared",
        "scientific_identity_changed",
    }
)

_ATTESTATION_FIELDS = frozenset(
    {
        "claims",
        "complete",
        "evidence_sha256",
        "independent_review_sha256",
        "kind",
        "schema_version",
        "signature",
        "structurally_valid",
        "subject_sha256",
    }
)
_DECISION_REGISTER_BOOLEAN_CLAIMS = {
    "all_blocking_decisions_resolved": True,
    "register_structurally_valid": True,
    "replacement_preregistration_frozen": True,
}
_DECISION_REGISTER_CLAIM_FIELDS = frozenset(
    {
        *_DECISION_REGISTER_BOOLEAN_CLAIMS,
        "frozen_arm_roster",
        "role_bindings",
        "stage_authorizations",
    }
)
_ROLE_NAMES = (
    "protocol_freezer",
    "custodian",
    "blind_executor",
    "unblinding_reviewer",
)
_ROLE_BINDING_FIELDS = frozenset({"key_identity_sha256", "principal_identity_sha256"})
_STAGE_AUTHORIZATION_FIELDS = frozenset(
    {"key_identity_sha256", "principal_identity_sha256", "role"}
)
_FROZEN_ARM_FIELDS = frozenset({"arm_id", "config_sha256"})
_RUNTIME_AUDIT_CLAIMS = {
    "application_firewall_is_os_confinement": False,
    "dedicated_build_context_allowlist_verified": True,
    "deny_list_and_file_access_audit_verified": True,
    "network_disabled_enforced": True,
    "non_root_container_user_verified": True,
    "read_only_root_filesystem_enforced": True,
}
_PAYLOAD_FIELDS = frozenset(
    {
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
)
_RECORD_FIELDS = _PAYLOAD_FIELDS | {"integrity", "record_sha256"}


class WorkflowError(RuntimeError):
    """Raised when a transition, signature, or stage barrier fails closed."""


class WorkflowStage(str, Enum):
    """The only successful one-way stage order."""

    FROZEN = "frozen"
    TARGET_MOUNTED = "target_mounted"
    SELECTION_COMPLETE = "selection_complete"
    WINNER_LOCKED = "winner_locked"
    VALIDATION_COMPLETE = "validation_complete"
    SEARCH_COMPLETE = "search_complete"
    SEARCH_SEALED = "search_sealed"
    UNBLINDED = "unblinded"
    CANCELLED = "cancelled"


_REQUIRED_STAGE_ROLES = {
    WorkflowStage.FROZEN: "protocol_freezer",
    WorkflowStage.TARGET_MOUNTED: "custodian",
    WorkflowStage.SELECTION_COMPLETE: "blind_executor",
    WorkflowStage.WINNER_LOCKED: "blind_executor",
    WorkflowStage.VALIDATION_COMPLETE: "blind_executor",
    WorkflowStage.SEARCH_COMPLETE: "blind_executor",
    WorkflowStage.SEARCH_SEALED: "blind_executor",
    WorkflowStage.UNBLINDED: "unblinding_reviewer",
    WorkflowStage.CANCELLED: "protocol_freezer",
}


_ADVANCE_ORDER = (
    WorkflowStage.FROZEN,
    WorkflowStage.TARGET_MOUNTED,
    WorkflowStage.SELECTION_COMPLETE,
    WorkflowStage.WINNER_LOCKED,
    WorkflowStage.VALIDATION_COMPLETE,
    WorkflowStage.SEARCH_COMPLETE,
    WorkflowStage.SEARCH_SEALED,
    WorkflowStage.UNBLINDED,
)


@dataclass(frozen=True)
class WorkflowSnapshot:
    """Derived ledger state; no mutable caller-owned record is exposed."""

    stage: WorkflowStage
    next_stage: WorkflowStage | None
    pending_retry_stage: WorkflowStage | None
    record_count: int
    workflow_id: str
    scientific_identity_sha256: str


@dataclass(frozen=True)
class _Evaluation:
    snapshot: WorkflowSnapshot
    pending_failure: dict[str, Any] | None
    winner_id: str | None
    winner_config_sha256: str | None
    hidden_validation_plan_sha256: str | None
    search_artifact_sha256: str | None
    sealed_artifact_sha256: str | None


def _strict_copy(value: Any, *, label: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (ProvenanceError, ValueError) as exc:
        raise WorkflowError(f"{label} must contain strict native JSON: {exc}") from exc


def _require_hash(value: Any, *, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise WorkflowError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_identifier(value: Any, *, field: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise WorkflowError(f"{field} must be a bounded native identifier")
    return value


def _coerce_stage(value: WorkflowStage | str) -> WorkflowStage:
    if isinstance(value, WorkflowStage):
        return value
    if type(value) is not str:
        raise WorkflowError("stage must be a WorkflowStage or native string")
    try:
        return WorkflowStage(value)
    except ValueError as exc:
        raise WorkflowError(f"unknown workflow stage: {value!r}") from exc


def _validate_decision_register_claims(claims: Any) -> dict[str, Any]:
    if type(claims) is not dict or set(claims) != _DECISION_REGISTER_CLAIM_FIELDS:
        raise WorkflowError("decision_register attestation has incomplete or unsafe claims")
    for field, expected in _DECISION_REGISTER_BOOLEAN_CLAIMS.items():
        if claims[field] is not expected:
            raise WorkflowError("decision_register attestation has incomplete or unsafe claims")

    roster = claims["frozen_arm_roster"]
    if type(roster) is not list or not 1 <= len(roster) <= _MAX_FROZEN_ARM_COUNT:
        raise WorkflowError(
            "decision_register frozen arm roster must be non-empty and explicitly bounded"
        )
    arm_ids: list[str] = []
    config_ids: list[str] = []
    for entry in roster:
        if type(entry) is not dict or set(entry) != _FROZEN_ARM_FIELDS:
            raise WorkflowError("every frozen arm must use the exact arm/config schema")
        arm_ids.append(_require_identifier(entry["arm_id"], field="frozen arm_id"))
        config_ids.append(_require_hash(entry["config_sha256"], field="frozen arm config_sha256"))
    if len(set(arm_ids)) != len(arm_ids):
        raise WorkflowError("frozen arm IDs must be unique")
    if len(set(config_ids)) != len(config_ids):
        raise WorkflowError("frozen arm configuration identities must be unique")

    bindings = claims["role_bindings"]
    if type(bindings) is not dict or set(bindings) != set(_ROLE_NAMES):
        raise WorkflowError("decision_register role bindings must name exactly four required roles")
    principal_ids: list[str] = []
    key_ids: list[str] = []
    for role in _ROLE_NAMES:
        binding = bindings[role]
        if type(binding) is not dict or set(binding) != _ROLE_BINDING_FIELDS:
            raise WorkflowError(f"role binding for {role} must use the exact identity schema")
        principal_ids.append(
            _require_hash(
                binding["principal_identity_sha256"],
                field=f"{role}.principal_identity_sha256",
            )
        )
        key_ids.append(
            _require_hash(binding["key_identity_sha256"], field=f"{role}.key_identity_sha256")
        )
    if len(set(principal_ids)) != len(_ROLE_NAMES):
        raise WorkflowError("the four workflow roles require distinct frozen principals")
    if len(set(key_ids)) != len(_ROLE_NAMES):
        raise WorkflowError("the four workflow roles require distinct frozen signing keys")

    authorizations = claims["stage_authorizations"]
    expected_stages = {stage.value for stage in WorkflowStage}
    if type(authorizations) is not dict or set(authorizations) != expected_stages:
        raise WorkflowError("stage authorizations must cover every workflow stage exactly once")
    for stage, required_role in _REQUIRED_STAGE_ROLES.items():
        authorization = authorizations[stage.value]
        if type(authorization) is not dict or set(authorization) != _STAGE_AUTHORIZATION_FIELDS:
            raise WorkflowError(
                f"stage authorization for {stage.value} must use the exact role/key schema"
            )
        binding = bindings[required_role]
        if authorization != {
            "key_identity_sha256": binding["key_identity_sha256"],
            "principal_identity_sha256": binding["principal_identity_sha256"],
            "role": required_role,
        }:
            raise WorkflowError(
                f"stage authorization for {stage.value} does not bind the required role identities"
            )
    return claims


def _attestation_body(attestation: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(attestation)
    body.pop("signature")
    return body


def _derive_workflow_id(
    decision_attestation: Mapping[str, Any],
    runtime_attestation: Mapping[str, Any],
    scientific_identity_sha256: str,
) -> str:
    """Derive the CAS namespace from verified bodies, never randomized signatures."""

    return canonical_sha256(
        {
            "decision_register_attestation_body_sha256": canonical_sha256(
                _attestation_body(decision_attestation)
            ),
            "runtime_audit_attestation_body_sha256": canonical_sha256(
                _attestation_body(runtime_attestation)
            ),
            "scientific_identity_sha256": scientific_identity_sha256,
        }
    )


def _require_authorized_transition_key(
    record: Mapping[str, Any],
    *,
    stage: WorkflowStage,
    decision_attestation: Mapping[str, Any],
) -> None:
    expected = decision_attestation["claims"]["stage_authorizations"][stage.value][
        "key_identity_sha256"
    ]
    supplied = record["integrity"]["signature"]["details"]["key_identity_sha256"]
    if supplied != expected:
        raise WorkflowError(f"transition signer key is not authorized for stage {stage.value}")


def _validate_attestation(
    attestation: Mapping[str, Any],
    *,
    expected_kind: str,
    verifier: GateAttestationVerifier,
) -> dict[str, Any]:
    detached = _strict_copy(attestation, label=f"{expected_kind} attestation")
    if type(detached) is not dict:
        raise WorkflowError(f"{expected_kind} attestation must be a native JSON object")
    fields = set(detached)
    if fields != _ATTESTATION_FIELDS:
        raise WorkflowError(
            f"{expected_kind} attestation schema mismatch; "
            f"missing={sorted(_ATTESTATION_FIELDS - fields)}, "
            f"unexpected={sorted(fields - _ATTESTATION_FIELDS)}"
        )
    if type(detached["schema_version"]) is not int or detached["schema_version"] != 1:
        raise WorkflowError(f"unsupported {expected_kind} attestation schema")
    if type(detached["kind"]) is not str or detached["kind"] != expected_kind:
        raise WorkflowError(f"expected {expected_kind} attestation")
    if detached["complete"] is not True or detached["structurally_valid"] is not True:
        raise WorkflowError(f"{expected_kind} attestation is incomplete or structurally invalid")
    for field in ("subject_sha256", "evidence_sha256", "independent_review_sha256"):
        _require_hash(detached[field], field=f"{expected_kind}.{field}")
    if type(detached["signature"]) is not dict or not detached["signature"]:
        raise WorkflowError(f"{expected_kind} attestation requires signature evidence")
    if expected_kind == "decision_register":
        _validate_decision_register_claims(detached["claims"])
    elif type(detached["claims"]) is not dict or detached["claims"] != _RUNTIME_AUDIT_CLAIMS:
        raise WorkflowError("runtime_audit attestation has incomplete or unsafe claims")
    result = verifier(expected_kind, _strict_copy(detached, label="attestation verifier input"))
    if result is not True:
        raise WorkflowError(f"{expected_kind} attestation verification failed")
    return detached


def _signature_block(payload_bytes: bytes, signer: TransitionSigner) -> dict[str, Any]:
    details = signer(payload_bytes)
    detached = _strict_copy(details, label="transition signature details")
    _validate_transition_signature_details(detached)
    return {
        "details": detached,
        "signed_content_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "status": "signed",
    }


def _validate_transition_signature_details(details: Any) -> dict[str, Any]:
    if type(details) is not dict or set(details) != _TRANSITION_SIGNATURE_FIELDS:
        raise WorkflowError("transition signature details must use the fixed hash-only schema")
    if (
        type(details["algorithm"]) is not str
        or details["algorithm"] != _TRANSITION_SIGNATURE_ALGORITHM
    ):
        raise WorkflowError("transition signature algorithm is not the fixed external scheme")
    _require_hash(details["key_identity_sha256"], field="signature.key_identity_sha256")
    _require_hash(details["signature_sha256"], field="signature.signature_sha256")
    return details


def _build_record(
    *,
    workflow_id: str,
    sequence: int,
    stage: WorkflowStage,
    status: str,
    prior_record_sha256: str | None,
    scientific_identity_sha256: str,
    input_identity_sha256: str,
    retry_of_record_sha256: str | None,
    output: Mapping[str, Any],
    signer: TransitionSigner,
) -> dict[str, Any]:
    payload = {
        "input_identity_sha256": _require_hash(
            input_identity_sha256, field="input_identity_sha256"
        ),
        "output": _strict_copy(output, label="stage output"),
        "prior_record_sha256": prior_record_sha256,
        "retry_of_record_sha256": retry_of_record_sha256,
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "scientific_identity_sha256": _require_hash(
            scientific_identity_sha256, field="scientific_identity_sha256"
        ),
        "sequence": sequence,
        "stage": stage.value,
        "status": status,
        "workflow_id": _require_hash(workflow_id, field="workflow_id"),
    }
    if type(sequence) is not int or sequence < 0:
        raise WorkflowError("sequence must be a non-negative native integer")
    if status not in {"complete", "failed"} or type(status) is not str:
        raise WorkflowError("transition status must be complete or failed")
    if prior_record_sha256 is not None:
        _require_hash(prior_record_sha256, field="prior_record_sha256")
    if retry_of_record_sha256 is not None:
        _require_hash(retry_of_record_sha256, field="retry_of_record_sha256")
    payload_bytes = canonical_json_bytes(payload)
    record = payload | {
        "integrity": {
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "signature": _signature_block(payload_bytes, signer),
        }
    }
    record["record_sha256"] = canonical_sha256(record)
    return record


def _verify_record(
    record: Mapping[str, Any],
    *,
    signature_verifier: TransitionSignatureVerifier,
) -> dict[str, Any]:
    detached = _strict_copy(record, label="workflow record")
    if type(detached) is not dict or set(detached) != _RECORD_FIELDS:
        raise WorkflowError("workflow record schema mismatch")
    if type(detached["schema_version"]) is not int or detached["schema_version"] != 1:
        raise WorkflowError("unsupported workflow record schema")
    sequence = detached["sequence"]
    if type(sequence) is not int or sequence < 0:
        raise WorkflowError("workflow record sequence must be a non-negative native integer")
    if type(detached["stage"]) is not str:
        raise WorkflowError("workflow record stage must be a native string")
    _coerce_stage(detached["stage"])
    if type(detached["status"]) is not str or detached["status"] not in {"complete", "failed"}:
        raise WorkflowError("workflow record status is invalid")
    for field in ("workflow_id", "scientific_identity_sha256", "input_identity_sha256"):
        _require_hash(detached[field], field=field)
    for field in ("prior_record_sha256", "retry_of_record_sha256"):
        if detached[field] is not None:
            _require_hash(detached[field], field=field)
    if type(detached["output"]) is not dict:
        raise WorkflowError("workflow record output must be a native JSON object")
    expected_hash = _require_hash(detached["record_sha256"], field="record_sha256")
    body = dict(detached)
    body.pop("record_sha256")
    if canonical_sha256(body) != expected_hash:
        raise WorkflowError("workflow record self-hash mismatch")

    payload = {field: detached[field] for field in _PAYLOAD_FIELDS}
    payload_bytes = canonical_json_bytes(payload)
    integrity = detached["integrity"]
    if type(integrity) is not dict or set(integrity) != {"payload_sha256", "signature"}:
        raise WorkflowError("workflow integrity block is invalid")
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    if integrity["payload_sha256"] != payload_hash:
        raise WorkflowError("workflow payload hash mismatch")
    signature = integrity["signature"]
    if type(signature) is not dict or set(signature) != {
        "details",
        "signed_content_sha256",
        "status",
    }:
        raise WorkflowError("workflow signature block is invalid")
    if signature["status"] != "signed" or signature["signed_content_sha256"] != payload_hash:
        raise WorkflowError("workflow transition is unsigned or signed over different content")
    details = _validate_transition_signature_details(signature["details"])
    if signature_verifier(payload_bytes, _strict_copy(details, label="signature")) is not True:
        raise WorkflowError("workflow transition signature verification failed")
    return detached


def validate_workflow_record_envelope(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a record's strict schema, self-hash, payload hash, and signature envelope.

    This deliberately does not authenticate the detached signature, its key owner, the
    transition's stage authorization, or the complete workflow state machine.  It is the
    narrow validation level needed by an untrusted local persistence adapter before storing
    bytes.  :class:`WorkflowLedger` still performs the authoritative verifier callbacks and
    whole-chain evaluation when creating, restoring, or advancing a workflow.
    """

    return _verify_record(
        record,
        signature_verifier=lambda _payload, _details: True,
    )


def _require_exact_fields(output: dict[str, Any], expected: set[str], stage: WorkflowStage) -> None:
    if set(output) != expected:
        raise WorkflowError(
            f"{stage.value} output schema mismatch; "
            f"missing={sorted(expected - set(output))}, unexpected={sorted(set(output) - expected)}"
        )


def _require_canonical_utc(value: Any, *, field: str) -> str:
    if type(value) is not str:
        raise WorkflowError(f"{field} must be a canonical UTC timestamp")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise WorkflowError(f"{field} must use canonical YYYY-MM-DDTHH:MM:SSZ UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as exc:
        raise WorkflowError(f"{field} must use canonical YYYY-MM-DDTHH:MM:SSZ UTC") from exc
    return value


def _validate_stage_output(stage: WorkflowStage, output: Mapping[str, Any]) -> dict[str, Any]:
    detached = _strict_copy(output, label=f"{stage.value} output")
    if type(detached) is not dict:
        raise WorkflowError(f"{stage.value} output must be a native JSON object")
    if stage is WorkflowStage.TARGET_MOUNTED:
        _require_exact_fields(
            detached,
            {"mount_manifest_sha256", "mounted_by_role_sha256", "read_only"},
            stage,
        )
        _require_hash(detached["mount_manifest_sha256"], field="mount_manifest_sha256")
        _require_hash(detached["mounted_by_role_sha256"], field="mounted_by_role_sha256")
        if detached["read_only"] is not True:
            raise WorkflowError("target mount must be declared read-only")
    elif stage is WorkflowStage.SELECTION_COMPLETE:
        _require_exact_fields(
            detached,
            {"eligible_arm_ids", "selection_artifact_sha256", "winner_id"},
            stage,
        )
        _require_hash(detached["selection_artifact_sha256"], field="selection_artifact_sha256")
        winner = _require_identifier(detached["winner_id"], field="winner_id")
        eligible = detached["eligible_arm_ids"]
        if type(eligible) is not list or not eligible:
            raise WorkflowError("eligible_arm_ids must be a non-empty native list")
        parsed = [_require_identifier(item, field="eligible_arm_ids item") for item in eligible]
        if len(set(parsed)) != len(parsed) or winner not in parsed:
            raise WorkflowError("eligible arms must be unique and contain the winner")
    elif stage is WorkflowStage.WINNER_LOCKED:
        _require_exact_fields(
            detached,
            {"hidden_validation_plan_sha256", "winner_config_sha256", "winner_id"},
            stage,
        )
        _require_identifier(detached["winner_id"], field="winner_id")
        _require_hash(detached["winner_config_sha256"], field="winner_config_sha256")
        _require_hash(
            detached["hidden_validation_plan_sha256"],
            field="hidden_validation_plan_sha256",
        )
    elif stage is WorkflowStage.VALIDATION_COMPLETE:
        _require_exact_fields(
            detached,
            {
                "hidden_validation_plan_sha256",
                "passed",
                "validation_artifact_sha256",
                "winner_config_sha256",
                "winner_id",
            },
            stage,
        )
        _require_identifier(detached["winner_id"], field="winner_id")
        _require_hash(detached["winner_config_sha256"], field="winner_config_sha256")
        _require_hash(
            detached["hidden_validation_plan_sha256"],
            field="hidden_validation_plan_sha256",
        )
        _require_hash(detached["validation_artifact_sha256"], field="validation_artifact_sha256")
        if detached["passed"] is not True:
            raise WorkflowError("failed winner validation must stop; it is not a complete stage")
    elif stage is WorkflowStage.SEARCH_COMPLETE:
        _require_exact_fields(
            detached,
            {
                "global_calibration_sha256",
                "hidden_validation_plan_sha256",
                "search_artifact_sha256",
                "winner_config_sha256",
                "winner_id",
            },
            stage,
        )
        _require_identifier(detached["winner_id"], field="winner_id")
        _require_hash(detached["winner_config_sha256"], field="winner_config_sha256")
        _require_hash(
            detached["hidden_validation_plan_sha256"],
            field="hidden_validation_plan_sha256",
        )
        _require_hash(detached["search_artifact_sha256"], field="search_artifact_sha256")
        _require_hash(detached["global_calibration_sha256"], field="global_calibration_sha256")
    elif stage is WorkflowStage.SEARCH_SEALED:
        _require_exact_fields(
            detached,
            {"search_artifact_sha256", "sealed_artifact_sha256", "sealed_at"},
            stage,
        )
        _require_hash(detached["search_artifact_sha256"], field="search_artifact_sha256")
        _require_hash(detached["sealed_artifact_sha256"], field="sealed_artifact_sha256")
        _require_canonical_utc(detached["sealed_at"], field="sealed_at")
    elif stage is WorkflowStage.UNBLINDED:
        _require_exact_fields(
            detached,
            {"comparison_artifact_sha256", "reviewer_identity_sha256", "sealed_artifact_sha256"},
            stage,
        )
        _require_hash(detached["comparison_artifact_sha256"], field="comparison_artifact_sha256")
        _require_hash(detached["reviewer_identity_sha256"], field="reviewer_identity_sha256")
        _require_hash(detached["sealed_artifact_sha256"], field="sealed_artifact_sha256")
    else:
        raise WorkflowError(f"no public output schema exists for {stage.value}")
    return detached


def _validate_failure_attestation(
    attestation: Mapping[str, Any],
    *,
    expected_workflow_id: str,
    expected_record_sequence: int,
    expected_prior_record_sha256: str,
    expected_stage: WorkflowStage,
    expected_input_identity_sha256: str,
    expected_scientific_identity_sha256: str,
    verifier: FailureAttestationVerifier,
) -> dict[str, Any]:
    detached = _strict_copy(attestation, label="failure attestation")
    if type(detached) is not dict or set(detached) != _FAILURE_ATTESTATION_FIELDS:
        raise WorkflowError("failure attestation must use the exact fixed schema")
    if type(detached["schema_version"]) is not int or detached["schema_version"] != 1:
        raise WorkflowError("unsupported failure attestation schema")
    if type(detached["stage"]) is not str or detached["stage"] != expected_stage.value:
        raise WorkflowError("failure attestation does not bind the expected stage")
    for field in (
        "diagnostic_sha256",
        "evidence_sha256",
        "expected_prior_record_sha256",
        "independent_review_sha256",
        "input_identity_sha256",
        "scientific_identity_sha256",
        "workflow_id",
    ):
        _require_hash(detached[field], field=f"failure_attestation.{field}")
    if detached["workflow_id"] != expected_workflow_id:
        raise WorkflowError("failure attestation does not bind the workflow namespace")
    if (
        type(detached["expected_record_sequence"]) is not int
        or detached["expected_record_sequence"] != expected_record_sequence
    ):
        raise WorkflowError("failure attestation does not bind the expected record sequence")
    if detached["expected_prior_record_sha256"] != expected_prior_record_sha256:
        raise WorkflowError("failure attestation does not bind the expected prior durable head")
    failure_kind = detached["failure_kind"]
    failure_code = detached["failure_code"]
    if type(failure_kind) is not str or failure_kind not in {"infrastructure", "scientific"}:
        raise WorkflowError("failure attestation kind is invalid")
    allowed_codes = (
        _INFRASTRUCTURE_FAILURE_CODES
        if failure_kind == "infrastructure"
        else _SCIENTIFIC_FAILURE_CODES
    )
    if type(failure_code) is not str or failure_code not in allowed_codes:
        raise WorkflowError("failure attestation code is not allowed for its kind")
    if detached["input_identity_sha256"] != expected_input_identity_sha256:
        raise WorkflowError("failure attestation does not bind the stage input identity")
    if detached["scientific_identity_sha256"] != expected_scientific_identity_sha256:
        raise WorkflowError("failure attestation does not bind the scientific identity")
    _validate_transition_signature_details(detached["signature"])
    if verifier(_strict_copy(detached, label="failure verifier input")) is not True:
        raise WorkflowError("failure attestation verification failed")
    return detached


def _validate_failure_output(
    output: Mapping[str, Any],
    *,
    expected_workflow_id: str,
    expected_record_sequence: int,
    expected_prior_record_sha256: str,
    expected_stage: WorkflowStage,
    expected_input_identity_sha256: str,
    expected_scientific_identity_sha256: str,
    verifier: FailureAttestationVerifier,
) -> dict[str, Any]:
    detached = _strict_copy(output, label="failure output")
    if type(detached) is not dict or set(detached) != {"failure_attestation"}:
        raise WorkflowError("failure output schema mismatch")
    _validate_failure_attestation(
        detached["failure_attestation"],
        expected_workflow_id=expected_workflow_id,
        expected_record_sequence=expected_record_sequence,
        expected_prior_record_sha256=expected_prior_record_sha256,
        expected_stage=expected_stage,
        expected_input_identity_sha256=expected_input_identity_sha256,
        expected_scientific_identity_sha256=expected_scientific_identity_sha256,
        verifier=verifier,
    )
    return detached


def _validate_cancellation_output(output: Mapping[str, Any]) -> dict[str, Any]:
    detached = _strict_copy(output, label="cancellation output")
    expected = {
        "attempted_stage",
        "cancellation_code",
        "diagnostic_sha256",
        "frozen_scientific_identity_sha256",
        "proposed_scientific_identity_sha256",
    }
    if type(detached) is not dict or set(detached) != expected:
        raise WorkflowError("cancellation output schema mismatch")
    attempted = _coerce_stage(detached["attempted_stage"])
    if attempted in {WorkflowStage.FROZEN, WorkflowStage.CANCELLED}:
        raise WorkflowError("cancellation attempted_stage is invalid")
    _require_hash(
        detached["frozen_scientific_identity_sha256"],
        field="frozen_scientific_identity_sha256",
    )
    _require_hash(
        detached["proposed_scientific_identity_sha256"],
        field="proposed_scientific_identity_sha256",
    )
    _require_hash(detached["diagnostic_sha256"], field="diagnostic_sha256")
    if (
        type(detached["cancellation_code"]) is not str
        or detached["cancellation_code"] not in _CANCELLATION_CODES
    ):
        raise WorkflowError("cancellation_code is not an allowed fixed code")
    return detached


class WorkflowLedger:
    """A signed ledger coupled to an external compare-and-append durable head.

    The callbacks are security-critical.  The record verifier confirms that a successful
    commit remains durably included even if a successor has already landed.  The exact-head
    verifier rejects stale local ledgers before transitions or snapshot exposure, and the
    committer atomically compares the expected head and exclusively appends the next record.
    """

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        signer: TransitionSigner,
        signature_verifier: TransitionSignatureVerifier,
        gate_attestation_verifier: GateAttestationVerifier,
        failure_attestation_verifier: FailureAttestationVerifier,
        durable_head_verifier: DurableHeadVerifier,
        durable_record_verifier: DurableRecordVerifier,
        exclusive_append_committer: ExclusiveAppendCommitter,
    ) -> None:
        self._initialize(
            records,
            signer=signer,
            signature_verifier=signature_verifier,
            gate_attestation_verifier=gate_attestation_verifier,
            failure_attestation_verifier=failure_attestation_verifier,
            durable_head_verifier=durable_head_verifier,
            durable_record_verifier=durable_record_verifier,
            exclusive_append_committer=exclusive_append_committer,
            require_current_head=True,
        )

    def _initialize(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        signer: TransitionSigner,
        signature_verifier: TransitionSignatureVerifier,
        gate_attestation_verifier: GateAttestationVerifier,
        failure_attestation_verifier: FailureAttestationVerifier,
        durable_head_verifier: DurableHeadVerifier,
        durable_record_verifier: DurableRecordVerifier,
        exclusive_append_committer: ExclusiveAppendCommitter,
        require_current_head: bool,
    ) -> None:
        if not records:
            raise WorkflowError("workflow ledger cannot be empty")
        self._signer = signer
        self._signature_verifier = signature_verifier
        self._gate_attestation_verifier = gate_attestation_verifier
        self._failure_attestation_verifier = failure_attestation_verifier
        self._durable_head_verifier = durable_head_verifier
        self._durable_record_verifier = durable_record_verifier
        self._exclusive_append_committer = exclusive_append_committer
        self._records = tuple(_strict_copy(record, label="workflow record") for record in records)
        self._evaluate()
        self._require_durable_record(self._records[-1])
        if require_current_head:
            self._require_current_durable_head()

    @classmethod
    def create(
        cls,
        *,
        decision_register_attestation: Mapping[str, Any],
        runtime_audit_attestation: Mapping[str, Any],
        scientific_identity_sha256: str,
        signer: TransitionSigner,
        signature_verifier: TransitionSignatureVerifier,
        gate_attestation_verifier: GateAttestationVerifier,
        failure_attestation_verifier: FailureAttestationVerifier,
        durable_head_verifier: DurableHeadVerifier,
        durable_record_verifier: DurableRecordVerifier,
        exclusive_append_committer: ExclusiveAppendCommitter,
    ) -> WorkflowLedger:
        """Create a frozen workflow only after both structural attestations verify."""

        science = _require_hash(scientific_identity_sha256, field="scientific_identity_sha256")
        decision = _validate_attestation(
            decision_register_attestation,
            expected_kind="decision_register",
            verifier=gate_attestation_verifier,
        )
        runtime = _validate_attestation(
            runtime_audit_attestation,
            expected_kind="runtime_audit",
            verifier=gate_attestation_verifier,
        )
        output = {
            "decision_register_attestation": decision,
            "runtime_audit_attestation": runtime,
        }
        input_identity = canonical_sha256(output)
        workflow_id = _derive_workflow_id(decision, runtime, science)
        genesis = _build_record(
            workflow_id=workflow_id,
            sequence=0,
            stage=WorkflowStage.FROZEN,
            status="complete",
            prior_record_sha256=None,
            scientific_identity_sha256=science,
            input_identity_sha256=input_identity,
            retry_of_record_sha256=None,
            output=output,
            signer=signer,
        )
        verified_genesis = _verify_record(genesis, signature_verifier=signature_verifier)
        _require_authorized_transition_key(
            verified_genesis,
            stage=WorkflowStage.FROZEN,
            decision_attestation=decision,
        )
        if (
            exclusive_append_committer(
                workflow_id,
                None,
                None,
                _strict_copy(genesis, label="genesis commit record"),
            )
            is not True
        ):
            raise WorkflowError("durable store refused exclusive workflow creation")
        ledger = cls.__new__(cls)
        ledger._initialize(
            [genesis],
            signer=signer,
            signature_verifier=signature_verifier,
            gate_attestation_verifier=gate_attestation_verifier,
            failure_attestation_verifier=failure_attestation_verifier,
            durable_head_verifier=durable_head_verifier,
            durable_record_verifier=durable_record_verifier,
            exclusive_append_committer=exclusive_append_committer,
            require_current_head=False,
        )
        return ledger

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        self._require_current_durable_head()
        return tuple(_strict_copy(record, label="workflow record") for record in self._records)

    @property
    def snapshot(self) -> WorkflowSnapshot:
        self._require_current_durable_head()
        return self._evaluate().snapshot

    def _require_current_durable_head(self) -> None:
        last = self._records[-1]
        if (
            self._durable_head_verifier(
                last["workflow_id"],
                last["sequence"],
                last["record_sha256"],
            )
            is not True
        ):
            raise WorkflowError(
                "durable head verification failed; refusing a stale, truncated, or rolled-back ledger"
            )

    def _require_durable_record(self, record: Mapping[str, Any]) -> None:
        if (
            self._durable_record_verifier(
                record["workflow_id"],
                record["sequence"],
                record["record_sha256"],
            )
            is not True
        ):
            raise WorkflowError("durable store did not verify committed record inclusion")

    def _evaluate(self) -> _Evaluation:
        verified = [
            _verify_record(record, signature_verifier=self._signature_verifier)
            for record in self._records
        ]
        first = verified[0]
        if first["sequence"] != 0 or first["stage"] != WorkflowStage.FROZEN.value:
            raise WorkflowError("workflow must begin with a frozen sequence-zero record")
        if (
            first["status"] != "complete"
            or first["prior_record_sha256"] is not None
            or first["retry_of_record_sha256"] is not None
        ):
            raise WorkflowError("frozen genesis record is invalid")
        genesis_output = first["output"]
        if type(genesis_output) is not dict or set(genesis_output) != {
            "decision_register_attestation",
            "runtime_audit_attestation",
        }:
            raise WorkflowError("frozen output schema mismatch")
        decision = _validate_attestation(
            genesis_output["decision_register_attestation"],
            expected_kind="decision_register",
            verifier=self._gate_attestation_verifier,
        )
        runtime = _validate_attestation(
            genesis_output["runtime_audit_attestation"],
            expected_kind="runtime_audit",
            verifier=self._gate_attestation_verifier,
        )
        science = _require_hash(
            first["scientific_identity_sha256"], field="scientific_identity_sha256"
        )
        expected_workflow_id = _derive_workflow_id(decision, runtime, science)
        if first["workflow_id"] != expected_workflow_id:
            raise WorkflowError("workflow identity does not bind its frozen attestations")
        if first["input_identity_sha256"] != canonical_sha256(genesis_output):
            raise WorkflowError("frozen input identity does not bind both attestations")
        _require_authorized_transition_key(
            first,
            stage=WorkflowStage.FROZEN,
            decision_attestation=decision,
        )

        decision_claims = decision["claims"]
        role_bindings = decision_claims["role_bindings"]
        arm_configs = {
            entry["arm_id"]: entry["config_sha256"]
            for entry in decision_claims["frozen_arm_roster"]
        }

        completed_index = 0
        stage = WorkflowStage.FROZEN
        pending: dict[str, Any] | None = None
        winner: str | None = None
        winner_config: str | None = None
        hidden_validation_plan: str | None = None
        search_artifact: str | None = None
        sealed_artifact: str | None = None
        terminal = False

        for index, record in enumerate(verified):
            if index == 0:
                continue
            previous = verified[index - 1]
            if record["sequence"] != index:
                raise WorkflowError("workflow record sequence is out of order or has a gap")
            if record["prior_record_sha256"] != previous["record_sha256"]:
                raise WorkflowError("workflow prior-record hash link is invalid")
            if record["workflow_id"] != expected_workflow_id:
                raise WorkflowError("workflow identity changed within the ledger")
            if record["scientific_identity_sha256"] != science:
                raise WorkflowError("record changed the frozen scientific identity")
            if terminal:
                raise WorkflowError(
                    "workflow contains a transition after terminal cancellation/unblinding"
                )

            record_stage = _coerce_stage(record["stage"])
            _require_authorized_transition_key(
                record,
                stage=record_stage,
                decision_attestation=decision,
            )
            next_stage = _ADVANCE_ORDER[completed_index + 1]
            if record_stage is WorkflowStage.CANCELLED:
                if record["status"] != "complete" or record["retry_of_record_sha256"] is not None:
                    raise WorkflowError("cancellation record is invalid")
                cancellation = _validate_cancellation_output(record["output"])
                if cancellation["frozen_scientific_identity_sha256"] != science:
                    raise WorkflowError("cancellation does not bind the frozen scientific identity")
                if cancellation["attempted_stage"] != next_stage.value:
                    raise WorkflowError("cancellation attempted stage is not the next stage")
                cancellation_code = cancellation["cancellation_code"]
                if cancellation_code == "scientific_identity_changed":
                    if cancellation["proposed_scientific_identity_sha256"] == science:
                        raise WorkflowError("scientific-identity cancellation records no change")
                    expected_diagnostic = canonical_sha256(
                        {
                            "attempted_stage": next_stage.value,
                            "frozen_scientific_identity_sha256": science,
                            "input_identity_sha256": record["input_identity_sha256"],
                            "proposed_scientific_identity_sha256": cancellation[
                                "proposed_scientific_identity_sha256"
                            ],
                        }
                    )
                    if cancellation["diagnostic_sha256"] != expected_diagnostic:
                        raise WorkflowError("scientific-identity cancellation diagnostic mismatch")
                elif cancellation_code == "retry_identity_changed":
                    if pending is None:
                        raise WorkflowError("retry-identity cancellation lacks a pending failure")
                    if (
                        cancellation["proposed_scientific_identity_sha256"] == science
                        and record["input_identity_sha256"] == pending["input_identity_sha256"]
                    ):
                        raise WorkflowError("retry-identity cancellation records no change")
                    expected_diagnostic = canonical_sha256(
                        {
                            "attempted_stage": next_stage.value,
                            "failed_input_identity_sha256": pending["input_identity_sha256"],
                            "frozen_scientific_identity_sha256": science,
                            "proposed_input_identity_sha256": record["input_identity_sha256"],
                            "proposed_scientific_identity_sha256": cancellation[
                                "proposed_scientific_identity_sha256"
                            ],
                        }
                    )
                    if cancellation["diagnostic_sha256"] != expected_diagnostic:
                        raise WorkflowError("retry-identity cancellation diagnostic mismatch")
                stage = WorkflowStage.CANCELLED
                terminal = True
                pending = None
                continue
            if record_stage is not next_stage:
                raise WorkflowError(
                    f"out-of-order transition: expected {next_stage.value}, got {record_stage.value}"
                )

            if record["status"] == "failed":
                if pending is not None or record["retry_of_record_sha256"] is not None:
                    raise WorkflowError("failed transition cannot replace or retry another failure")
                failure = _validate_failure_output(
                    record["output"],
                    expected_workflow_id=expected_workflow_id,
                    expected_record_sequence=record["sequence"],
                    expected_prior_record_sha256=record["prior_record_sha256"],
                    expected_stage=record_stage,
                    expected_input_identity_sha256=record["input_identity_sha256"],
                    expected_scientific_identity_sha256=science,
                    verifier=self._failure_attestation_verifier,
                )
                attestation = failure["failure_attestation"]
                if attestation["failure_kind"] == "infrastructure":
                    pending = record
                else:
                    stage = WorkflowStage.CANCELLED
                    terminal = True
                continue
            if record["status"] != "complete":
                raise WorkflowError("workflow record status is invalid")
            if pending is None:
                if record["retry_of_record_sha256"] is not None:
                    raise WorkflowError("successful transition refers to a nonexistent failure")
            else:
                if record["retry_of_record_sha256"] != pending["record_sha256"]:
                    raise WorkflowError("retry does not bind the pending failure")
                if record["input_identity_sha256"] != pending["input_identity_sha256"]:
                    raise WorkflowError("retry input is not content-identical")
                pending = None

            output = _validate_stage_output(record_stage, record["output"])
            if record_stage is WorkflowStage.TARGET_MOUNTED:
                if (
                    output["mounted_by_role_sha256"]
                    != role_bindings["custodian"]["principal_identity_sha256"]
                ):
                    raise WorkflowError("target mount does not bind the frozen custodian principal")
            elif record_stage is WorkflowStage.SELECTION_COMPLETE:
                if not set(output["eligible_arm_ids"]).issubset(arm_configs):
                    raise WorkflowError("eligible arm IDs must be drawn from the frozen roster")
                winner = output["winner_id"]
            elif record_stage is WorkflowStage.WINNER_LOCKED:
                if output["winner_id"] != winner:
                    raise WorkflowError("runner-up substitution is forbidden at winner lock")
                if output["winner_config_sha256"] != arm_configs[winner]:
                    raise WorkflowError("winner configuration does not match the frozen arm roster")
                winner_config = output["winner_config_sha256"]
                hidden_validation_plan = output["hidden_validation_plan_sha256"]
            elif record_stage in {WorkflowStage.VALIDATION_COMPLETE, WorkflowStage.SEARCH_COMPLETE}:
                if output["winner_id"] != winner:
                    raise WorkflowError("the locked winner may not be substituted")
                if output["winner_config_sha256"] != winner_config:
                    raise WorkflowError("winner configuration hash changed after winner lock")
                if output["hidden_validation_plan_sha256"] != hidden_validation_plan:
                    raise WorkflowError("hidden validation plan hash changed after winner lock")
                if record_stage is WorkflowStage.SEARCH_COMPLETE:
                    search_artifact = output["search_artifact_sha256"]
            elif record_stage is WorkflowStage.SEARCH_SEALED:
                if output["search_artifact_sha256"] != search_artifact:
                    raise WorkflowError("search seal does not bind the completed search artifact")
                sealed_artifact = output["sealed_artifact_sha256"]
            elif record_stage is WorkflowStage.UNBLINDED:
                if output["sealed_artifact_sha256"] != sealed_artifact:
                    raise WorkflowError("unblinding does not bind the sealed search artifact")
                if (
                    output["reviewer_identity_sha256"]
                    != role_bindings["unblinding_reviewer"]["principal_identity_sha256"]
                ):
                    raise WorkflowError(
                        "unblinding does not bind the frozen unblinding reviewer principal"
                    )
                terminal = True
            completed_index += 1
            stage = record_stage

        next_stage = (
            None
            if terminal or completed_index == len(_ADVANCE_ORDER) - 1
            else _ADVANCE_ORDER[completed_index + 1]
        )
        snapshot = WorkflowSnapshot(
            stage=stage,
            next_stage=next_stage,
            pending_retry_stage=_coerce_stage(pending["stage"]) if pending is not None else None,
            record_count=len(verified),
            workflow_id=expected_workflow_id,
            scientific_identity_sha256=science,
        )
        return _Evaluation(
            snapshot=snapshot,
            pending_failure=pending,
            winner_id=winner,
            winner_config_sha256=winner_config,
            hidden_validation_plan_sha256=hidden_validation_plan,
            search_artifact_sha256=search_artifact,
            sealed_artifact_sha256=sealed_artifact,
        )

    def _append(
        self,
        *,
        stage: WorkflowStage,
        status: str,
        output: Mapping[str, Any],
        input_identity_sha256: str,
        retry_of_record_sha256: str | None = None,
    ) -> dict[str, Any]:
        self._require_current_durable_head()
        evaluation = self._evaluate()
        record = _build_record(
            workflow_id=evaluation.snapshot.workflow_id,
            sequence=len(self._records),
            stage=stage,
            status=status,
            prior_record_sha256=self._records[-1]["record_sha256"],
            scientific_identity_sha256=evaluation.snapshot.scientific_identity_sha256,
            input_identity_sha256=input_identity_sha256,
            retry_of_record_sha256=retry_of_record_sha256,
            output=output,
            signer=self._signer,
        )
        candidate = self._records + (_strict_copy(record, label="workflow record"),)
        previous = self._records
        self._records = candidate
        try:
            self._evaluate()
        finally:
            self._records = previous
        prior = previous[-1]
        if (
            self._exclusive_append_committer(
                evaluation.snapshot.workflow_id,
                prior["sequence"],
                prior["record_sha256"],
                _strict_copy(record, label="exclusive append record"),
            )
            is not True
        ):
            raise WorkflowError("durable store refused exclusive compare-and-append")
        self._require_durable_record(record)
        self._records = candidate
        return _strict_copy(record, label="workflow record")

    def _append_scientific_change_cancellation(
        self,
        *,
        attempted_stage: WorkflowStage,
        proposed_scientific_identity_sha256: str,
        input_identity_sha256: str,
        cancellation_code: str,
        diagnostic_sha256: str,
    ) -> dict[str, Any]:
        evaluation = self._evaluate()
        proposed = _require_hash(
            proposed_scientific_identity_sha256,
            field="proposed_scientific_identity_sha256",
        )
        if type(cancellation_code) is not str or cancellation_code not in _CANCELLATION_CODES:
            raise WorkflowError("cancellation_code is not an allowed fixed code")
        diagnostic = _require_hash(diagnostic_sha256, field="diagnostic_sha256")
        return self._append(
            stage=WorkflowStage.CANCELLED,
            status="complete",
            input_identity_sha256=input_identity_sha256,
            output={
                "attempted_stage": attempted_stage.value,
                "cancellation_code": cancellation_code,
                "diagnostic_sha256": diagnostic,
                "frozen_scientific_identity_sha256": evaluation.snapshot.scientific_identity_sha256,
                "proposed_scientific_identity_sha256": proposed,
            },
        )

    def advance(
        self,
        stage: WorkflowStage | str,
        output: Mapping[str, Any],
        *,
        input_identity_sha256: str,
        scientific_identity_sha256: str,
    ) -> dict[str, Any]:
        """Complete the next stage, or cancel if its scientific identity changed."""

        requested = _coerce_stage(stage)
        evaluation = self._evaluate()
        if evaluation.snapshot.next_stage is None:
            raise WorkflowError("workflow is terminal")
        if requested is not evaluation.snapshot.next_stage:
            raise WorkflowError(
                f"next stage is {evaluation.snapshot.next_stage.value}, not {requested.value}"
            )
        if evaluation.pending_failure is not None:
            raise WorkflowError("an infrastructure failure is pending; use retry_content_identical")
        proposed = _require_hash(scientific_identity_sha256, field="scientific_identity_sha256")
        if proposed != evaluation.snapshot.scientific_identity_sha256:
            diagnostic = canonical_sha256(
                {
                    "attempted_stage": requested.value,
                    "frozen_scientific_identity_sha256": evaluation.snapshot.scientific_identity_sha256,
                    "input_identity_sha256": input_identity_sha256,
                    "proposed_scientific_identity_sha256": proposed,
                }
            )
            return self._append_scientific_change_cancellation(
                attempted_stage=requested,
                proposed_scientific_identity_sha256=proposed,
                input_identity_sha256=input_identity_sha256,
                cancellation_code="scientific_identity_changed",
                diagnostic_sha256=diagnostic,
            )
        validated_output = _validate_stage_output(requested, output)
        return self._append(
            stage=requested,
            status="complete",
            output=validated_output,
            input_identity_sha256=input_identity_sha256,
        )

    def fail_next_stage(
        self,
        *,
        failure_attestation: Mapping[str, Any],
        input_identity_sha256: str,
        scientific_identity_sha256: str,
    ) -> dict[str, Any]:
        """Record a failure only after an independent exact-schema attestation verifies."""

        evaluation = self._evaluate()
        stage = evaluation.snapshot.next_stage
        if stage is None:
            raise WorkflowError("workflow is terminal")
        if evaluation.pending_failure is not None:
            raise WorkflowError("a failure is already pending")
        proposed = _require_hash(scientific_identity_sha256, field="scientific_identity_sha256")
        if proposed != evaluation.snapshot.scientific_identity_sha256:
            diagnostic = canonical_sha256(
                {
                    "attempted_stage": stage.value,
                    "frozen_scientific_identity_sha256": evaluation.snapshot.scientific_identity_sha256,
                    "input_identity_sha256": input_identity_sha256,
                    "proposed_scientific_identity_sha256": proposed,
                }
            )
            return self._append_scientific_change_cancellation(
                attempted_stage=stage,
                proposed_scientific_identity_sha256=proposed,
                input_identity_sha256=input_identity_sha256,
                cancellation_code="scientific_identity_changed",
                diagnostic_sha256=diagnostic,
            )
        stage_input = _require_hash(input_identity_sha256, field="input_identity_sha256")
        output = _validate_failure_output(
            {"failure_attestation": failure_attestation},
            expected_workflow_id=evaluation.snapshot.workflow_id,
            expected_record_sequence=len(self._records),
            expected_prior_record_sha256=self._records[-1]["record_sha256"],
            expected_stage=stage,
            expected_input_identity_sha256=stage_input,
            expected_scientific_identity_sha256=evaluation.snapshot.scientific_identity_sha256,
            verifier=self._failure_attestation_verifier,
        )
        return self._append(
            stage=stage,
            status="failed",
            output=output,
            input_identity_sha256=stage_input,
        )

    def retry_content_identical(
        self,
        output: Mapping[str, Any],
        *,
        input_identity_sha256: str,
        scientific_identity_sha256: str,
    ) -> dict[str, Any]:
        """Retry only the pending infrastructure failure with identical content identities.

        A changed input or scientific identity appends a terminal cancellation instead of
        silently starting a revised experiment.
        """

        evaluation = self._evaluate()
        pending = evaluation.pending_failure
        if pending is None:
            raise WorkflowError("there is no retryable infrastructure failure")
        stage = _coerce_stage(pending["stage"])
        proposed_science = _require_hash(
            scientific_identity_sha256, field="scientific_identity_sha256"
        )
        proposed_input = _require_hash(input_identity_sha256, field="input_identity_sha256")
        if (
            proposed_science != evaluation.snapshot.scientific_identity_sha256
            or proposed_input != pending["input_identity_sha256"]
        ):
            diagnostic = canonical_sha256(
                {
                    "attempted_stage": stage.value,
                    "failed_input_identity_sha256": pending["input_identity_sha256"],
                    "frozen_scientific_identity_sha256": evaluation.snapshot.scientific_identity_sha256,
                    "proposed_input_identity_sha256": proposed_input,
                    "proposed_scientific_identity_sha256": proposed_science,
                }
            )
            return self._append_scientific_change_cancellation(
                attempted_stage=stage,
                proposed_scientific_identity_sha256=proposed_science,
                input_identity_sha256=proposed_input,
                cancellation_code="retry_identity_changed",
                diagnostic_sha256=diagnostic,
            )
        validated_output = _validate_stage_output(stage, output)
        return self._append(
            stage=stage,
            status="complete",
            output=validated_output,
            input_identity_sha256=proposed_input,
            retry_of_record_sha256=pending["record_sha256"],
        )

    def cancel_scientific_change(
        self,
        *,
        proposed_scientific_identity_sha256: str,
        input_identity_sha256: str,
        diagnostic_sha256: str,
    ) -> dict[str, Any]:
        """Explicitly cancel before applying a scientific code/input/rule change."""

        evaluation = self._evaluate()
        if evaluation.snapshot.next_stage is None:
            raise WorkflowError("workflow is terminal")
        return self._append_scientific_change_cancellation(
            attempted_stage=evaluation.snapshot.next_stage,
            proposed_scientific_identity_sha256=proposed_scientific_identity_sha256,
            input_identity_sha256=input_identity_sha256,
            cancellation_code="scientific_change_declared",
            diagnostic_sha256=diagnostic_sha256,
        )


__all__ = [
    "WORKFLOW_SCHEMA_VERSION",
    "DurableHeadVerifier",
    "DurableRecordVerifier",
    "ExclusiveAppendCommitter",
    "FailureAttestationVerifier",
    "GateAttestationVerifier",
    "TransitionSignatureVerifier",
    "TransitionSigner",
    "WorkflowError",
    "WorkflowLedger",
    "WorkflowSnapshot",
    "WorkflowStage",
    "validate_workflow_record_envelope",
]
