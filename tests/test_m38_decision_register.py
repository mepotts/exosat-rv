"""Synthetic-only tests for the complete M38 structural decision register."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from exosat_rv.m38.control_suite import EvidenceReference, ReviewMetadata, SignatureMetadata
from exosat_rv.m38.decision_register import (
    DECISION_REGISTER_SCHEMA_VERSION,
    M38_DECISION_KEYS,
    DecisionRecord,
    DecisionRegister,
    DecisionRegisterError,
    validate_decision_register,
)
from exosat_rv.m38.provenance import canonical_json_bytes


class StringSubclass(str):
    """A hostile string subclass that exact identity checks must reject."""


def review(
    *,
    reviewer_id: str = "independent-reviewer",
    reviewed_at: str = "2030-01-01T00:01:00Z",
    outcome: str = "accepted",
    digit: str = "a",
) -> ReviewMetadata:
    return ReviewMetadata(
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        report_sha256=digit * 64,
        outcome=outcome,
    )


def roles_value() -> dict[str, object]:
    key_owners = {f"key-{key}": "custodian-a" for key in M38_DECISION_KEYS}
    key_owners |= {
        "late-key": "custodian-a",
        "register-key": "custodian-a",
    }
    return {
        "development_team": ["developer-a"],
        "holdout_custodian": ["custodian-a"],
        "blind_executor": ["executor-a"],
        "unblinding_reviewer": ["unblinder-a"],
        "independent_reviewer": ["independent-reviewer", "register-reviewer"],
        "enforcement_mechanism": {
            "mechanism_sha256": "f" * 64,
            "signature_key_owners": key_owners,
        },
    }


def resolved_decision(
    key: str,
    *,
    selected_value: dict[str, object] | None = None,
    signature_digest: str | None = None,
) -> DecisionRecord:
    selected = selected_value
    if selected is None and key == "roles_and_enforcement":
        selected = roles_value()
    elif selected is None:
        selected = {"choice_id": f"caller-supplied-{key}"}
    basis = [EvidenceReference(f"basis-{key}", "1" * 64)]
    decision_review = review(digit="b")
    frozen_at = "2030-01-01T00:02:00Z"
    provisional = DecisionRecord(
        key=key,
        status="resolved",
        selected_value=selected,
        rationale=f"Caller-supplied independent rationale for {key}.",
        basis=basis,
        review=decision_review,
        frozen_at=frozen_at,
        signature=None,
        metadata={"basis_class": "synthetic-fixture"},
    )
    digest = provisional.signature_payload_sha256 if signature_digest is None else signature_digest
    return DecisionRecord(
        key=key,
        status="resolved",
        selected_value=selected,
        rationale=f"Caller-supplied independent rationale for {key}.",
        basis=basis,
        review=decision_review,
        frozen_at=frozen_at,
        signature=SignatureMetadata(
            scheme="caller-selected-test-scheme",
            key_id=f"key-{key}",
            signature=f"opaque-signature-{key}",
            signed_content_sha256=digest,
            signed_at="2030-01-01T00:03:00Z",
        ),
        metadata={"basis_class": "synthetic-fixture"},
    )


def decisions() -> list[DecisionRecord]:
    return [resolved_decision(key) for key in M38_DECISION_KEYS]


def frozen_register(*, records: list[DecisionRecord] | None = None) -> DecisionRegister:
    records = decisions() if records is None else records
    register_review = review(
        reviewer_id="register-reviewer",
        reviewed_at="2030-01-01T00:04:00Z",
        digit="c",
    )
    provisional = DecisionRegister(
        schema_version=DECISION_REGISTER_SCHEMA_VERSION,
        protocol_sha256="d" * 64,
        decisions=records,
        status="frozen",
        frozen_at="2030-01-01T00:05:00Z",
        review=register_review,
        signature=None,
        metadata={"register_class": "synthetic-fixture"},
    )
    return DecisionRegister(
        schema_version=DECISION_REGISTER_SCHEMA_VERSION,
        protocol_sha256="d" * 64,
        decisions=records,
        status="frozen",
        frozen_at="2030-01-01T00:05:00Z",
        review=register_review,
        signature=SignatureMetadata(
            scheme="caller-selected-test-scheme",
            key_id="register-key",
            signature="opaque-register-signature",
            signed_content_sha256=provisional.signature_payload_sha256,
            signed_at="2030-01-01T00:06:00Z",
        ),
        metadata={"register_class": "synthetic-fixture"},
    )


def test_complete_register_has_exact_18_keys_and_bound_canonical_identity() -> None:
    register = frozen_register()

    assert len(M38_DECISION_KEYS) == 18
    assert len(set(M38_DECISION_KEYS)) == 18
    assert [record.key for record in register.decisions] == list(M38_DECISION_KEYS)
    assert validate_decision_register(register) is register
    assert register.structurally_frozen
    assert register.signature is not None
    assert register.signature.signed_content_sha256 == register.signature_payload_sha256
    assert canonical_json_bytes(register.as_dict())
    assert register.register_id == frozen_register().register_id


def test_selected_values_metadata_and_sequences_are_immutable_snapshots() -> None:
    selected = {"choice": {"values": [1, 2]}}
    metadata = {"notes": ["original"]}
    basis = [EvidenceReference("basis", "1" * 64)]
    provisional = DecisionRecord(
        key="claim_and_target_data_regime",
        status="resolved",
        selected_value=selected,
        rationale="A caller-owned rationale.",
        basis=basis,
        review=review(),
        frozen_at="2030-01-01T00:02:00Z",
        signature=None,
        metadata=metadata,
    )
    original_id = provisional.decision_id

    selected["choice"]["values"].append(3)
    metadata["notes"].append("changed")
    basis.clear()
    detached = provisional.as_dict()
    detached["selected_value"]["choice"]["values"].append(4)

    assert provisional.decision_id == original_id
    assert provisional.as_dict()["selected_value"] == {"choice": {"values": [1, 2]}}
    assert provisional.as_dict()["metadata"] == {"notes": ["original"]}
    assert len(provisional.basis) == 1
    with pytest.raises(FrozenInstanceError):
        provisional.status = "unresolved"


def test_unresolved_decision_fails_closed_even_inside_an_18_key_draft() -> None:
    records = decisions()
    records[4] = DecisionRecord(
        key=M38_DECISION_KEYS[4],
        status="unresolved",
        selected_value=None,
        rationale=None,
        basis=[EvidenceReference("work-in-progress", "e" * 64)],
        review=None,
        frozen_at=None,
        signature=None,
        metadata={"note": "not selected"},
    )
    register = DecisionRegister(
        1,
        "d" * 64,
        records,
        "draft",
        None,
        None,
        None,
        {},
    )

    with pytest.raises(DecisionRegisterError, match="unresolved decisions fail closed"):
        validate_decision_register(register, require_frozen=False)


def test_missing_decision_key_fails_the_complete_namespace_check() -> None:
    register = DecisionRegister(
        1,
        "d" * 64,
        decisions()[:-1],
        "draft",
        None,
        None,
        None,
        {},
    )

    with pytest.raises(DecisionRegisterError, match="key mismatch"):
        validate_decision_register(register, require_frozen=False)


def test_decision_register_requires_one_canonical_key_order() -> None:
    records = decisions()
    records[0], records[1] = records[1], records[0]
    register = DecisionRegister(
        1,
        "d" * 64,
        records,
        "draft",
        None,
        None,
        None,
        {},
    )

    with pytest.raises(DecisionRegisterError, match="canonical M38 order"):
        validate_decision_register(register, require_frozen=False)


def test_draft_register_with_resolved_decisions_still_requires_explicit_freeze() -> None:
    register = DecisionRegister(
        1,
        "d" * 64,
        decisions(),
        "draft",
        None,
        None,
        None,
        {},
    )

    assert validate_decision_register(register, require_frozen=False) is register
    with pytest.raises(DecisionRegisterError, match="draft or unsigned register fails closed"):
        validate_decision_register(register)


@pytest.mark.parametrize(
    "left_role, right_role",
    [
        ("development_team", "blind_executor"),
        ("holdout_custodian", "blind_executor"),
        ("blind_executor", "unblinding_reviewer"),
    ],
)
def test_incompatible_role_collisions_are_rejected(
    left_role: str,
    right_role: str,
) -> None:
    collided = roles_value()
    collided[left_role] = ["same-principal"]
    collided[right_role] = ["SAME-PRINCIPAL"]
    records = decisions()
    records[0] = resolved_decision("roles_and_enforcement", selected_value=collided)
    register = frozen_register(records=records)

    with pytest.raises(DecisionRegisterError, match="incompatible role collision"):
        validate_decision_register(register)


@pytest.mark.parametrize(
    "selected, message",
    [
        ({"development_team": ["developer"]}, "missing assignments"),
        (
            {
                "development_team": ["developer"],
                "holdout_custodian": ["custodian"],
                "blind_executor": ["executor"],
                "unblinding_reviewer": ["reviewer"],
                "independent_reviewer": ["independent"],
                "enforcement_mechanism": {},
            },
            "enforcement_mechanism",
        ),
        (
            {
                "development_team": "developer",
                "holdout_custodian": ["custodian"],
                "blind_executor": ["executor"],
                "unblinding_reviewer": ["reviewer"],
                "independent_reviewer": ["independent"],
                "enforcement_mechanism": {
                    "mechanism_sha256": "f" * 64,
                    "signature_key_owners": {"key": "executor"},
                },
            },
            "development_team must be a non-empty native list",
        ),
    ],
)
def test_role_assignment_schema_is_explicit(selected: dict[str, object], message: str) -> None:
    records = decisions()
    records[0] = resolved_decision("roles_and_enforcement", selected_value=selected)
    register = frozen_register(records=records)

    with pytest.raises(DecisionRegisterError, match=message):
        validate_decision_register(register)


def test_reviews_and_signature_keys_are_bound_to_frozen_role_ownership() -> None:
    records = decisions()
    records[1] = resolved_decision("claim_and_target_data_regime")
    mismatched_review = review(reviewer_id="undeclared-reviewer", digit="b")
    provisional = DecisionRecord(
        key=records[1].key,
        status="resolved",
        selected_value=records[1].as_dict()["selected_value"],
        rationale=records[1].rationale,
        basis=records[1].basis,
        review=mismatched_review,
        frozen_at=records[1].frozen_at,
        signature=None,
        metadata=records[1].as_dict()["metadata"],
    )
    records[1] = DecisionRecord(
        key=provisional.key,
        status=provisional.status,
        selected_value=provisional.as_dict()["selected_value"],
        rationale=provisional.rationale,
        basis=provisional.basis,
        review=provisional.review,
        frozen_at=provisional.frozen_at,
        signature=SignatureMetadata(
            scheme="test",
            key_id=f"key-{provisional.key}",
            signature="opaque",
            signed_content_sha256=provisional.signature_payload_sha256,
            signed_at="2030-01-01T00:03:00Z",
        ),
        metadata=provisional.as_dict()["metadata"],
    )

    with pytest.raises(DecisionRegisterError, match="declared independent reviewer"):
        validate_decision_register(frozen_register(records=records))

    roles = roles_value()
    roles["enforcement_mechanism"]["signature_key_owners"].pop("key-claim_and_target_data_regime")
    records = decisions()
    records[0] = resolved_decision("roles_and_enforcement", selected_value=roles)
    with pytest.raises(DecisionRegisterError, match="lacks frozen ownership"):
        validate_decision_register(frozen_register(records=records))


def test_resolved_decision_requires_basis_review_rationale_and_freeze() -> None:
    with pytest.raises(DecisionRegisterError, match="basis artifact"):
        DecisionRecord(
            key="period_search_design",
            status="resolved",
            selected_value={"choice": "caller"},
            rationale="A rationale.",
            basis=[],
            review=review(),
            frozen_at="2030-01-01T00:02:00Z",
            signature=None,
            metadata={},
        )
    with pytest.raises(DecisionRegisterError, match="accepted review"):
        DecisionRecord(
            key="period_search_design",
            status="resolved",
            selected_value={"choice": "caller"},
            rationale="A rationale.",
            basis=[EvidenceReference("basis", "1" * 64)],
            review=review(outcome="rejected"),
            frozen_at="2030-01-01T00:02:00Z",
            signature=None,
            metadata={},
        )


def test_unresolved_decision_cannot_smuggle_a_selection_or_review() -> None:
    with pytest.raises(DecisionRegisterError, match="unresolved decision cannot carry"):
        DecisionRecord(
            key="convergence_policy",
            status="unresolved",
            selected_value={"threshold": 1.0},
            rationale=None,
            basis=[],
            review=None,
            frozen_at=None,
            signature=None,
            metadata={},
        )


def test_decision_signature_must_bind_selected_value_and_review_metadata() -> None:
    with pytest.raises(DecisionRegisterError, match="does not bind"):
        resolved_decision("convergence_policy", signature_digest="0" * 64)


def test_register_signature_must_bind_all_decisions_and_register_review() -> None:
    with pytest.raises(DecisionRegisterError, match="does not bind"):
        DecisionRegister(
            schema_version=1,
            protocol_sha256="d" * 64,
            decisions=decisions(),
            status="frozen",
            frozen_at="2030-01-01T00:05:00Z",
            review=review(reviewed_at="2030-01-01T00:04:00Z"),
            signature=SignatureMetadata(
                scheme="test",
                key_id="key",
                signature="value",
                signed_content_sha256="0" * 64,
                signed_at="2030-01-01T00:06:00Z",
            ),
            metadata={},
        )


def test_decisions_must_be_frozen_before_register_freeze() -> None:
    late_review = review(reviewed_at="2030-01-01T00:06:00Z")
    provisional = DecisionRecord(
        key="period_search_design",
        status="resolved",
        selected_value={"choice": "caller"},
        rationale="A rationale.",
        basis=[EvidenceReference("basis-late", "1" * 64)],
        review=late_review,
        frozen_at="2030-01-01T00:07:00Z",
        signature=None,
        metadata={},
    )
    late = DecisionRecord(
        key=provisional.key,
        status=provisional.status,
        selected_value=provisional.as_dict()["selected_value"],
        rationale=provisional.rationale,
        basis=provisional.basis,
        review=provisional.review,
        frozen_at=provisional.frozen_at,
        signature=SignatureMetadata(
            scheme="test",
            key_id="late-key",
            signature="late-value",
            signed_content_sha256=provisional.signature_payload_sha256,
            signed_at="2030-01-01T00:08:00Z",
        ),
        metadata={},
    )
    records = decisions()
    records[M38_DECISION_KEYS.index("period_search_design")] = late
    register_review = review(reviewed_at="2030-01-01T00:04:00Z")
    provisional_register = DecisionRegister(
        1,
        "d" * 64,
        records,
        "frozen",
        "2030-01-01T00:05:00Z",
        register_review,
        None,
        {},
    )
    register = DecisionRegister(
        1,
        "d" * 64,
        records,
        "frozen",
        "2030-01-01T00:05:00Z",
        register_review,
        SignatureMetadata(
            scheme="test",
            key_id="register-key",
            signature="register-value",
            signed_content_sha256=provisional_register.signature_payload_sha256,
            signed_at="2030-01-01T00:09:00Z",
        ),
        {},
    )

    with pytest.raises(DecisionRegisterError, match="not frozen before the register"):
        validate_decision_register(register)


def test_child_review_must_predate_the_enclosing_register_review() -> None:
    key = "period_search_design"
    base = resolved_decision(key)
    late_review = review(reviewed_at="2030-01-01T00:04:10Z")
    provisional = DecisionRecord(
        key=key,
        status="resolved",
        selected_value=base.as_dict()["selected_value"],
        rationale=base.rationale,
        basis=base.basis,
        review=late_review,
        frozen_at="2030-01-01T00:04:20Z",
        signature=None,
        metadata={},
    )
    late = DecisionRecord(
        key=key,
        status="resolved",
        selected_value=base.as_dict()["selected_value"],
        rationale=base.rationale,
        basis=base.basis,
        review=late_review,
        frozen_at=provisional.frozen_at,
        signature=SignatureMetadata(
            scheme="test",
            key_id=f"key-{key}",
            signature="late-review-signature",
            signed_content_sha256=provisional.signature_payload_sha256,
            signed_at="2030-01-01T00:04:30Z",
        ),
        metadata={},
    )
    records = decisions()
    records[M38_DECISION_KEYS.index(key)] = late

    with pytest.raises(DecisionRegisterError, match="reviews followed the enclosing"):
        validate_decision_register(frozen_register(records=records))


def test_child_signature_must_predate_the_enclosing_register_review() -> None:
    key = "period_search_design"
    base = resolved_decision(key)
    provisional = DecisionRecord(
        key=base.key,
        status=base.status,
        selected_value=base.as_dict()["selected_value"],
        rationale=base.rationale,
        basis=base.basis,
        review=base.review,
        frozen_at=base.frozen_at,
        signature=None,
        metadata={},
    )
    late_signature = DecisionRecord(
        key=base.key,
        status=base.status,
        selected_value=base.as_dict()["selected_value"],
        rationale=base.rationale,
        basis=base.basis,
        review=base.review,
        frozen_at=base.frozen_at,
        signature=SignatureMetadata(
            scheme="test",
            key_id=f"key-{key}",
            signature="late-child-signature",
            signed_content_sha256=provisional.signature_payload_sha256,
            signed_at="2030-01-01T00:04:30Z",
        ),
        metadata={},
    )
    records = decisions()
    records[M38_DECISION_KEYS.index(key)] = late_signature

    with pytest.raises(DecisionRegisterError, match="signatures followed the enclosing"):
        validate_decision_register(frozen_register(records=records))


@pytest.mark.parametrize(
    "factory, message",
    [
        (
            lambda: DecisionRecord(
                key=StringSubclass("convergence_policy"),
                status="unresolved",
                selected_value=None,
                rationale=None,
                basis=[],
                review=None,
                frozen_at=None,
                signature=None,
                metadata={},
            ),
            "native string",
        ),
        (
            lambda: DecisionRecord(
                key="convergence_policy",
                status="resolved",
                selected_value={"invalid": (1, 2)},
                rationale="rationale",
                basis=[EvidenceReference("basis", "1" * 64)],
                review=review(),
                frozen_at="2030-01-01T00:02:00Z",
                signature=None,
                metadata={},
            ),
            "strict native JSON",
        ),
        (
            lambda: DecisionRegister(
                schema_version=True,
                protocol_sha256="d" * 64,
                decisions=[],
                status="draft",
                frozen_at=None,
                review=None,
                signature=None,
                metadata={},
            ),
            "schema version",
        ),
    ],
)
def test_exact_native_boundaries(factory, message: str) -> None:
    with pytest.raises((DecisionRegisterError, ValueError), match=message):
        factory()


def test_draft_register_cannot_carry_partial_freeze_metadata() -> None:
    with pytest.raises(DecisionRegisterError, match="draft register"):
        DecisionRegister(
            1,
            "d" * 64,
            decisions(),
            "draft",
            "2030-01-01T00:05:00Z",
            None,
            None,
            {},
        )


def test_validator_recursively_rechecks_child_and_register_signature_payloads() -> None:
    child_mutation = frozen_register()
    object.__setattr__(
        child_mutation.decisions[0],
        "selected_value",
        {"choice_id": "forged-after-signature"},
    )
    with pytest.raises(DecisionRegisterError, match="signature does not bind"):
        validate_decision_register(child_mutation)

    enclosing_mutation = frozen_register()
    object.__setattr__(enclosing_mutation, "metadata", {"forged": True})
    with pytest.raises(DecisionRegisterError, match="signature does not bind"):
        validate_decision_register(enclosing_mutation)
