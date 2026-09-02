"""Synthetic-only tests for strict M38 control-suite records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from exosat_rv.m38.control_suite import (
    CONTROL_SUITE_SCHEMA_VERSION,
    ContentReference,
    ControlDefinition,
    ControlEpoch,
    ControlSuite,
    ControlSuiteError,
    EvidenceReference,
    ReviewMetadata,
    SignatureMetadata,
    TruthRecord,
    control_suite_signature_payload_sha256,
    validate_control_suite,
)
from exosat_rv.m38.provenance import canonical_json_bytes


class StringSubclass(str):
    """A JSON-looking identity that exact native checks must reject."""


class IntSubclass(int):
    """An integer subclass that must not pass a content-size boundary."""


def evidence(label: str, digit: str) -> EvidenceReference:
    return EvidenceReference(reference=label, sha256=digit * 64)


def review(
    *,
    reviewer_id: str = "reviewer-independent",
    reviewed_at: str = "2030-01-01T00:02:00Z",
    outcome: str = "accepted",
    digit: str = "a",
) -> ReviewMetadata:
    return ReviewMetadata(
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        report_sha256=digit * 64,
        outcome=outcome,
    )


def truth(index: int, *, truth_review: ReviewMetadata | None = None) -> TruthRecord:
    return TruthRecord(
        basis=[evidence(f"truth-basis-{index}", str((index % 8) + 1))],
        assertion={"kind": "known_velocity", "values": [0.0, float(index)]},
        independence_statement="Established without using the held-out experiment outcome.",
        established_at="2029-12-01T00:00:00Z",
        recorded_at="2030-01-01T00:01:00Z",
        review=truth_review or review(digit="b"),
        metadata={"source_class": "synthetic-fixture"},
    )


def control(kind: str, index: int, *, setting_id: str = "setting-control") -> ControlDefinition:
    epoch = ControlEpoch(
        epoch_id=f"epoch-{index}",
        night_id=f"night-{index}",
        setting_id=setting_id,
        inputs=[
            ContentReference(
                label=f"input-{index}",
                sha256=str((index % 8) + 1) * 64,
                size_bytes=100 + index,
            )
        ],
        included=True,
        exclusion_reason=None,
        metadata={"ordinal": index},
    )
    return ControlDefinition(
        label=f"control-{kind}-{index}",
        kind=kind,
        setting_id=setting_id,
        truth=truth(index),
        epochs=[epoch],
        suitability_basis=[evidence(f"suitability-{index}", "c")],
        exclusion_rule={"rule_id": f"predeclared-{index}", "missing": "fail"},
        metadata={"declared": True},
    )


def controls() -> list[ControlDefinition]:
    return [
        control("synthetic", 1),
        control("stable_null", 2),
        control("positive_rv", 3),
    ]


def frozen_suite(
    *,
    suite_controls: list[ControlDefinition] | None = None,
    metadata: dict[str, object] | None = None,
) -> ControlSuite:
    suite_controls = controls() if suite_controls is None else suite_controls
    metadata = {"plan": {"version": 1}} if metadata is None else metadata
    suite_review = review(reviewed_at="2030-01-01T00:03:00Z", digit="d")
    frozen_at = "2030-01-01T00:04:00Z"
    payload_sha256 = control_suite_signature_payload_sha256(
        schema_version=CONTROL_SUITE_SCHEMA_VERSION,
        instrument_setting_id="setting-control",
        controls=suite_controls,
        frozen_at=frozen_at,
        review=suite_review,
        metadata=metadata,
    )
    return ControlSuite(
        schema_version=CONTROL_SUITE_SCHEMA_VERSION,
        instrument_setting_id="setting-control",
        controls=suite_controls,
        status="frozen",
        frozen_at=frozen_at,
        review=suite_review,
        signature=SignatureMetadata(
            scheme="caller-selected-test-scheme",
            key_id="test-key",
            signature="opaque-test-signature",
            signed_content_sha256=payload_sha256,
            signed_at="2030-01-01T00:05:00Z",
        ),
        metadata=metadata,
    )


def test_frozen_control_suite_is_complete_content_bound_and_canonical() -> None:
    suite = frozen_suite()

    assert validate_control_suite(suite) is suite
    assert suite.structurally_frozen
    assert len(suite.suite_id) == 64
    assert suite.signature is not None
    assert suite.signature.signed_content_sha256 == suite.signature_payload_sha256
    assert canonical_json_bytes(suite.as_dict())
    assert suite.suite_id == frozen_suite().suite_id


def test_control_records_snapshot_caller_owned_json_and_sequences() -> None:
    assertion = {"values": [1.0, 2.0]}
    truth_metadata = {"nested": {"flag": True}}
    basis = [evidence("truth-source", "1")]
    record = TruthRecord(
        basis=basis,
        assertion=assertion,
        independence_statement="Independent synthetic construction.",
        established_at="2029-01-01T00:00:00Z",
        recorded_at="2030-01-01T00:00:00Z",
        review=review(),
        metadata=truth_metadata,
    )
    original_id = record.truth_id

    assertion["values"].append(99.0)
    truth_metadata["nested"]["flag"] = False
    basis.clear()
    detached = record.as_dict()
    detached["assertion"]["values"].append(88.0)

    assert record.truth_id == original_id
    assert record.as_dict()["assertion"] == {"values": [1.0, 2.0]}
    assert record.as_dict()["metadata"] == {"nested": {"flag": True}}
    assert len(record.basis) == 1
    with pytest.raises(FrozenInstanceError):
        record.recorded_at = "2040-01-01T00:00:00Z"


def test_draft_suite_is_inspectable_but_fails_closed_by_default() -> None:
    suite = ControlSuite(
        schema_version=1,
        instrument_setting_id="setting-control",
        controls=controls(),
        status="draft",
        frozen_at=None,
        review=None,
        signature=None,
        metadata={},
    )

    assert validate_control_suite(suite, require_frozen=False) is suite
    assert not suite.structurally_frozen
    with pytest.raises(ControlSuiteError, match="draft control suite fails closed"):
        validate_control_suite(suite)


@pytest.mark.parametrize(
    "suite_controls, message",
    [
        ([control("synthetic", 1), control("stable_null", 2)], "missing required kinds"),
        (
            [
                control("synthetic", 1),
                control("stable_null", 2),
                control("positive_rv", 3, setting_id="other"),
            ],
            "instrument_setting_id",
        ),
    ],
)
def test_suite_requires_all_three_control_classes_and_one_explicit_setting(
    suite_controls: list[ControlDefinition],
    message: str,
) -> None:
    suite = ControlSuite(
        schema_version=1,
        instrument_setting_id="setting-control",
        controls=suite_controls,
        status="draft",
        frozen_at=None,
        review=None,
        signature=None,
        metadata={},
    )
    with pytest.raises(ControlSuiteError, match=message):
        validate_control_suite(suite, require_frozen=False)


def test_epoch_ids_cannot_be_reused_across_controls() -> None:
    suite_controls = controls()
    original = suite_controls[-1]
    duplicate_epoch = ControlEpoch(
        epoch_id=suite_controls[0].epochs[0].epoch_id,
        night_id="other-night",
        setting_id="setting-control",
        inputs=[ContentReference("other-input", "e" * 64, 10)],
        included=True,
        exclusion_reason=None,
        metadata={},
    )
    suite_controls[-1] = ControlDefinition(
        label=original.label,
        kind=original.kind,
        setting_id=original.setting_id,
        truth=original.truth,
        epochs=[duplicate_epoch],
        suitability_basis=original.suitability_basis,
        exclusion_rule=original.as_dict()["exclusion_rule"],
        metadata={},
    )
    suite = ControlSuite(1, "setting-control", suite_controls, "draft", None, None, None, {})

    with pytest.raises(ControlSuiteError, match="epoch IDs across the suite"):
        validate_control_suite(suite, require_frozen=False)


def test_inclusion_and_exclusion_are_explicit_and_fail_closed() -> None:
    with pytest.raises(ControlSuiteError, match="included epoch"):
        ControlEpoch(
            "epoch",
            "night",
            "setting",
            [ContentReference("input", "1" * 64, 1)],
            True,
            "should-not-exist",
            {},
        )
    with pytest.raises(ControlSuiteError, match="exclusion_reason"):
        ControlEpoch(
            "epoch",
            "night",
            "setting",
            [ContentReference("input", "1" * 64, 1)],
            False,
            None,
            {},
        )


def test_truth_and_review_must_predate_the_suite_freeze() -> None:
    late_review = review(reviewed_at="2030-01-01T00:06:00Z", digit="e")
    late_truth_control = control("positive_rv", 3)
    late_truth_control = ControlDefinition(
        label=late_truth_control.label,
        kind=late_truth_control.kind,
        setting_id=late_truth_control.setting_id,
        truth=truth(3, truth_review=late_review),
        epochs=late_truth_control.epochs,
        suitability_basis=late_truth_control.suitability_basis,
        exclusion_rule=late_truth_control.as_dict()["exclusion_rule"],
        metadata={},
    )
    suite_controls = [control("synthetic", 1), control("stable_null", 2), late_truth_control]
    suite = frozen_suite(suite_controls=suite_controls)

    with pytest.raises(ControlSuiteError, match="truth review followed freeze"):
        validate_control_suite(suite)


def test_every_truth_review_must_predate_the_enclosing_suite_review() -> None:
    nested_late_review = review(reviewed_at="2030-01-01T00:03:30Z", digit="e")
    late_control = control("positive_rv", 3)
    late_control = ControlDefinition(
        label=late_control.label,
        kind=late_control.kind,
        setting_id=late_control.setting_id,
        truth=truth(3, truth_review=nested_late_review),
        epochs=late_control.epochs,
        suitability_basis=late_control.suitability_basis,
        exclusion_rule=late_control.as_dict()["exclusion_rule"],
        metadata={},
    )
    suite = frozen_suite(
        suite_controls=[control("synthetic", 1), control("stable_null", 2), late_control]
    )

    with pytest.raises(ControlSuiteError, match="followed the enclosing suite review"):
        validate_control_suite(suite)


def test_rejected_truth_review_cannot_close_a_suite() -> None:
    rejected = review(outcome="rejected", digit="f")
    rejected_control = control("stable_null", 2)
    rejected_control = ControlDefinition(
        label=rejected_control.label,
        kind=rejected_control.kind,
        setting_id=rejected_control.setting_id,
        truth=truth(2, truth_review=rejected),
        epochs=rejected_control.epochs,
        suitability_basis=rejected_control.suitability_basis,
        exclusion_rule=rejected_control.as_dict()["exclusion_rule"],
        metadata={},
    )
    suite_controls = [control("synthetic", 1), rejected_control, control("positive_rv", 3)]
    suite = frozen_suite(suite_controls=suite_controls)

    with pytest.raises(ControlSuiteError, match="truth review was not accepted"):
        validate_control_suite(suite)


def test_suite_signature_metadata_must_bind_the_exact_frozen_payload() -> None:
    with pytest.raises(ControlSuiteError, match="does not bind"):
        ControlSuite(
            schema_version=1,
            instrument_setting_id="setting-control",
            controls=controls(),
            status="frozen",
            frozen_at="2030-01-01T00:04:00Z",
            review=review(reviewed_at="2030-01-01T00:03:00Z"),
            signature=SignatureMetadata(
                scheme="test",
                key_id="key",
                signature="value",
                signed_content_sha256="0" * 64,
                signed_at="2030-01-01T00:05:00Z",
            ),
            metadata={},
        )


@pytest.mark.parametrize(
    "factory, message",
    [
        (lambda: EvidenceReference(StringSubclass("ref"), "1" * 64), "native string"),
        (lambda: EvidenceReference("ref", "A" * 64), "lowercase SHA-256"),
        (lambda: ContentReference("input", "1" * 64, IntSubclass(1)), "native integer"),
        (
            lambda: ControlEpoch(
                "epoch",
                "night",
                "setting",
                [ContentReference("input", "1" * 64, 1)],
                1,
                None,
                {},
            ),
            "native boolean",
        ),
        (
            lambda: TruthRecord(
                [evidence("basis", "1")],
                {"nonfinite": float("nan")},
                "independent",
                "2029-01-01T00:00:00Z",
                "2030-01-01T00:00:00Z",
                review(),
                {},
            ),
            "strict native JSON",
        ),
    ],
)
def test_exact_native_and_canonical_boundaries(factory, message: str) -> None:
    with pytest.raises(ControlSuiteError, match=message):
        factory()


def test_cyclic_json_is_rejected_before_snapshotting() -> None:
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    with pytest.raises(ControlSuiteError, match="reference cycle"):
        TruthRecord(
            [evidence("basis", "1")],
            cycle,
            "independent",
            "2029-01-01T00:00:00Z",
            "2030-01-01T00:00:00Z",
            review(),
            {},
        )


def test_draft_cannot_masquerade_with_partial_freeze_metadata() -> None:
    with pytest.raises(ControlSuiteError, match="draft control suite"):
        ControlSuite(
            1,
            "setting-control",
            controls(),
            "draft",
            "2030-01-01T00:04:00Z",
            None,
            None,
            {},
        )


def test_validator_recursively_rechecks_nested_and_enclosing_signature_payloads() -> None:
    nested_mutation = frozen_suite()
    object.__setattr__(
        nested_mutation.controls[0].truth,
        "assertion",
        {"kind": "forged-after-signature", "values": [999.0]},
    )
    with pytest.raises(ControlSuiteError, match="signature does not bind"):
        validate_control_suite(nested_mutation)

    enclosing_mutation = frozen_suite()
    object.__setattr__(enclosing_mutation, "metadata", {"forged": True})
    with pytest.raises(ControlSuiteError, match="signature does not bind"):
        validate_control_suite(enclosing_mutation)
