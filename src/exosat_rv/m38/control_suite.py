"""Strict structural records for an M38 development-control suite.

This module records caller-supplied controls and truth evidence without selecting any
control, threshold, target, or scientific default.  Validation establishes only schema,
content identity, chronology, and structural completeness.  It cannot establish that a
control is scientifically suitable, that a truth assertion is correct or independent, or
that signature metadata is cryptographically valid.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from exosat_rv.m38.provenance import ProvenanceError, canonical_json_bytes, canonical_sha256

CONTROL_SUITE_SCHEMA_VERSION = 1
ControlKind = Literal["synthetic", "stable_null", "positive_rv"]
ControlSuiteStatus = Literal["draft", "frozen"]
ReviewOutcome = Literal["accepted", "rejected"]

_CONTROL_KINDS = frozenset({"synthetic", "stable_null", "positive_rv"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class ControlSuiteError(ValueError):
    """Raised when a control-suite record is not strict or structurally valid."""


def _native_string(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ControlSuiteError(f"{name} must be a non-empty native string without edge space")
    return value


def _sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ControlSuiteError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _utc_timestamp(value: object, name: str) -> str:
    text = _native_string(value, name)
    if _UTC_TIMESTAMP.fullmatch(text) is None:
        raise ControlSuiteError(f"{name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as exc:
        raise ControlSuiteError(f"{name} is not a valid UTC timestamp") from exc
    return text


def _strict_json_snapshot(
    value: object,
    name: str,
    *,
    require_object: bool = False,
    require_nonempty: bool = False,
) -> object:
    if require_object and type(value) is not dict:
        raise ControlSuiteError(f"{name} must be a native JSON object")
    if require_nonempty and type(value) is dict and not value:
        raise ControlSuiteError(f"{name} must not be empty")
    try:
        canonical_json_bytes(value)
    except ProvenanceError as exc:
        raise ControlSuiteError(
            f"{name} must contain only strict native JSON values: {exc}"
        ) from exc
    return _freeze_json(value)


def _freeze_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_thaw_json(child) for child in value]
    return value


def _typed_tuple(value: object, name: str, item_type: type[Any]) -> tuple[Any, ...]:
    if type(value) not in {list, tuple}:
        raise ControlSuiteError(f"{name} must be a native list or tuple")
    items = tuple(value)
    if any(type(item) is not item_type for item in items):
        raise ControlSuiteError(f"every item in {name} must be an exact {item_type.__name__}")
    return items


def _unique(values: Sequence[str], name: str) -> None:
    folded = [value.casefold() for value in values]
    if len(folded) != len(set(folded)):
        raise ControlSuiteError(f"{name} must be unique, including case-insensitively")


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Opaque content identity for one caller-supplied evidentiary artifact."""

    reference: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference", _native_string(self.reference, "reference"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))

    def as_dict(self) -> dict[str, object]:
        return {"reference": self.reference, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ReviewMetadata:
    """Structural record of a review; no reviewer identity is inferred or authenticated."""

    reviewer_id: str
    reviewed_at: str
    report_sha256: str
    outcome: ReviewOutcome

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reviewer_id",
            _native_string(self.reviewer_id, "reviewer_id"),
        )
        object.__setattr__(self, "reviewed_at", _utc_timestamp(self.reviewed_at, "reviewed_at"))
        object.__setattr__(
            self,
            "report_sha256",
            _sha256(self.report_sha256, "report_sha256"),
        )
        if type(self.outcome) is not str or self.outcome not in {"accepted", "rejected"}:
            raise ControlSuiteError("review outcome must be exactly 'accepted' or 'rejected'")

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "report_sha256": self.report_sha256,
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
        }


@dataclass(frozen=True, slots=True)
class SignatureMetadata:
    """Detached signature metadata without a chosen or implicit signing scheme."""

    scheme: str
    key_id: str
    signature: str
    signed_content_sha256: str
    signed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheme", _native_string(self.scheme, "signature scheme"))
        object.__setattr__(self, "key_id", _native_string(self.key_id, "signature key_id"))
        object.__setattr__(
            self,
            "signature",
            _native_string(self.signature, "signature value"),
        )
        object.__setattr__(
            self,
            "signed_content_sha256",
            _sha256(self.signed_content_sha256, "signed_content_sha256"),
        )
        object.__setattr__(self, "signed_at", _utc_timestamp(self.signed_at, "signed_at"))

    def as_dict(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "scheme": self.scheme,
            "signature": self.signature,
            "signed_at": self.signed_at,
            "signed_content_sha256": self.signed_content_sha256,
        }


@dataclass(frozen=True, slots=True)
class ContentReference:
    """Content-bound identity for one control input without opening the input."""

    label: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _native_string(self.label, "content label"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "content sha256"))
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ControlSuiteError("content size_bytes must be a non-negative native integer")

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "sha256": self.sha256, "size_bytes": self.size_bytes}


@dataclass(frozen=True, slots=True)
class TruthRecord:
    """Caller-supplied truth definition and its independently reviewable basis."""

    basis: Sequence[EvidenceReference]
    assertion: dict[str, object]
    independence_statement: str
    established_at: str
    recorded_at: str
    review: ReviewMetadata
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        basis = _typed_tuple(self.basis, "truth basis", EvidenceReference)
        if not basis:
            raise ControlSuiteError("truth basis must contain at least one evidence reference")
        _unique([item.reference for item in basis], "truth basis references")
        object.__setattr__(self, "basis", basis)
        object.__setattr__(
            self,
            "assertion",
            _strict_json_snapshot(
                self.assertion,
                "truth assertion",
                require_object=True,
                require_nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "independence_statement",
            _native_string(self.independence_statement, "independence_statement"),
        )
        established = _utc_timestamp(self.established_at, "established_at")
        recorded = _utc_timestamp(self.recorded_at, "recorded_at")
        if established > recorded:
            raise ControlSuiteError("truth established_at cannot follow recorded_at")
        object.__setattr__(self, "established_at", established)
        object.__setattr__(self, "recorded_at", recorded)
        if type(self.review) is not ReviewMetadata:
            raise ControlSuiteError("truth review must be an exact ReviewMetadata")
        if self.review.reviewed_at < recorded:
            raise ControlSuiteError("truth review cannot predate the recorded truth")
        object.__setattr__(
            self,
            "metadata",
            _strict_json_snapshot(self.metadata, "truth metadata", require_object=True),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "assertion": _thaw_json(self.assertion),
            "basis": [item.as_dict() for item in self.basis],
            "established_at": self.established_at,
            "independence_statement": self.independence_statement,
            "metadata": _thaw_json(self.metadata),
            "recorded_at": self.recorded_at,
            "review": self.review.as_dict(),
        }

    @property
    def truth_id(self) -> str:
        return canonical_sha256(self._payload())

    def as_dict(self) -> dict[str, object]:
        return self._payload() | {"truth_id": self.truth_id}


@dataclass(frozen=True, slots=True)
class ControlEpoch:
    """One declared control epoch, including any predeclared exclusion outcome."""

    epoch_id: str
    night_id: str
    setting_id: str
    inputs: Sequence[ContentReference]
    included: bool
    exclusion_reason: str | None
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _native_string(self.epoch_id, "epoch_id"))
        object.__setattr__(self, "night_id", _native_string(self.night_id, "night_id"))
        object.__setattr__(self, "setting_id", _native_string(self.setting_id, "setting_id"))
        inputs = _typed_tuple(self.inputs, "epoch inputs", ContentReference)
        if not inputs:
            raise ControlSuiteError("each control epoch must bind at least one input")
        _unique([item.label for item in inputs], "epoch input labels")
        object.__setattr__(self, "inputs", inputs)
        if type(self.included) is not bool:
            raise ControlSuiteError("included must be a native boolean")
        if self.included:
            if self.exclusion_reason is not None:
                raise ControlSuiteError("an included epoch cannot carry an exclusion reason")
        else:
            object.__setattr__(
                self,
                "exclusion_reason",
                _native_string(self.exclusion_reason, "exclusion_reason"),
            )
        object.__setattr__(
            self,
            "metadata",
            _strict_json_snapshot(self.metadata, "epoch metadata", require_object=True),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "epoch_id": self.epoch_id,
            "exclusion_reason": self.exclusion_reason,
            "included": self.included,
            "inputs": [item.as_dict() for item in self.inputs],
            "metadata": _thaw_json(self.metadata),
            "night_id": self.night_id,
            "setting_id": self.setting_id,
        }

    @property
    def epoch_record_id(self) -> str:
        return canonical_sha256(self._payload())

    def as_dict(self) -> dict[str, object]:
        return self._payload() | {"epoch_record_id": self.epoch_record_id}


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    """One exact synthetic, stable/null, or positive control definition."""

    label: str
    kind: ControlKind
    setting_id: str
    truth: TruthRecord
    epochs: Sequence[ControlEpoch]
    suitability_basis: Sequence[EvidenceReference]
    exclusion_rule: dict[str, object]
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _native_string(self.label, "control label"))
        if type(self.kind) is not str or self.kind not in _CONTROL_KINDS:
            raise ControlSuiteError(
                "control kind must be exactly 'synthetic', 'stable_null', or 'positive_rv'"
            )
        object.__setattr__(self, "setting_id", _native_string(self.setting_id, "setting_id"))
        if type(self.truth) is not TruthRecord:
            raise ControlSuiteError("control truth must be an exact TruthRecord")
        epochs = _typed_tuple(self.epochs, "control epochs", ControlEpoch)
        if not epochs:
            raise ControlSuiteError("a control must contain at least one epoch")
        _unique([epoch.epoch_id for epoch in epochs], "control epoch IDs")
        if any(epoch.setting_id != self.setting_id for epoch in epochs):
            raise ControlSuiteError("every control epoch must use the control's setting_id")
        if not any(epoch.included for epoch in epochs):
            raise ControlSuiteError("a control must retain at least one included epoch")
        object.__setattr__(self, "epochs", epochs)
        basis = _typed_tuple(
            self.suitability_basis,
            "control suitability basis",
            EvidenceReference,
        )
        if not basis:
            raise ControlSuiteError("control suitability basis must not be empty")
        _unique([item.reference for item in basis], "control suitability references")
        object.__setattr__(self, "suitability_basis", basis)
        object.__setattr__(
            self,
            "exclusion_rule",
            _strict_json_snapshot(
                self.exclusion_rule,
                "exclusion_rule",
                require_object=True,
                require_nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _strict_json_snapshot(self.metadata, "control metadata", require_object=True),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "epochs": [epoch.as_dict() for epoch in self.epochs],
            "exclusion_rule": _thaw_json(self.exclusion_rule),
            "kind": self.kind,
            "label": self.label,
            "metadata": _thaw_json(self.metadata),
            "setting_id": self.setting_id,
            "suitability_basis": [item.as_dict() for item in self.suitability_basis],
            "truth": self.truth.as_dict(),
        }

    @property
    def control_id(self) -> str:
        return canonical_sha256(self._payload())

    def as_dict(self) -> dict[str, object]:
        return self._payload() | {"control_id": self.control_id}


def _suite_payload(
    *,
    schema_version: int,
    instrument_setting_id: str,
    controls: Sequence[ControlDefinition],
    status: ControlSuiteStatus,
    frozen_at: str | None,
    review: ReviewMetadata | None,
    metadata: object,
) -> dict[str, object]:
    scientific_payload = {
        "controls": [control.as_dict() for control in controls],
        "instrument_setting_id": instrument_setting_id,
        "metadata": _thaw_json(metadata),
        "schema_version": schema_version,
    }
    return scientific_payload | {
        "frozen_at": frozen_at,
        "review": None if review is None else review.as_dict(),
        "status": status,
        "suite_id": canonical_sha256(scientific_payload),
    }


def control_suite_signature_payload_sha256(
    *,
    schema_version: int,
    instrument_setting_id: str,
    controls: Sequence[ControlDefinition],
    frozen_at: str,
    review: ReviewMetadata,
    metadata: dict[str, object],
) -> str:
    """Return the content digest a detached suite signature must bind."""

    if type(schema_version) is not int or schema_version != CONTROL_SUITE_SCHEMA_VERSION:
        raise ControlSuiteError("unsupported control-suite schema version")
    setting = _native_string(instrument_setting_id, "instrument_setting_id")
    parsed_controls = _typed_tuple(controls, "controls", ControlDefinition)
    timestamp = _utc_timestamp(frozen_at, "frozen_at")
    if type(review) is not ReviewMetadata:
        raise ControlSuiteError("review must be an exact ReviewMetadata")
    snapshot = _strict_json_snapshot(metadata, "suite metadata", require_object=True)
    return canonical_sha256(
        _suite_payload(
            schema_version=schema_version,
            instrument_setting_id=setting,
            controls=parsed_controls,
            status="frozen",
            frozen_at=timestamp,
            review=review,
            metadata=snapshot,
        )
    )


@dataclass(frozen=True, slots=True)
class ControlSuite:
    """Immutable snapshot of an exact control suite and its freeze metadata."""

    schema_version: int
    instrument_setting_id: str
    controls: Sequence[ControlDefinition]
    status: ControlSuiteStatus
    frozen_at: str | None
    review: ReviewMetadata | None
    signature: SignatureMetadata | None
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or (
            self.schema_version != CONTROL_SUITE_SCHEMA_VERSION
        ):
            raise ControlSuiteError("unsupported control-suite schema version")
        object.__setattr__(
            self,
            "instrument_setting_id",
            _native_string(self.instrument_setting_id, "instrument_setting_id"),
        )
        controls = _typed_tuple(self.controls, "controls", ControlDefinition)
        if not controls:
            raise ControlSuiteError("control suite must not be empty")
        object.__setattr__(self, "controls", controls)
        if type(self.status) is not str or self.status not in {"draft", "frozen"}:
            raise ControlSuiteError("control suite status must be exactly 'draft' or 'frozen'")
        object.__setattr__(
            self,
            "metadata",
            _strict_json_snapshot(self.metadata, "suite metadata", require_object=True),
        )
        if self.status == "draft":
            if any(value is not None for value in (self.frozen_at, self.review, self.signature)):
                raise ControlSuiteError("a draft control suite cannot carry freeze metadata")
            return

        object.__setattr__(self, "frozen_at", _utc_timestamp(self.frozen_at, "frozen_at"))
        if type(self.review) is not ReviewMetadata:
            raise ControlSuiteError("a frozen control suite requires exact review metadata")
        if self.review.outcome != "accepted":
            raise ControlSuiteError("a frozen control suite requires an accepted review")
        if self.review.reviewed_at > self.frozen_at:
            raise ControlSuiteError("control-suite review cannot follow the freeze")
        if type(self.signature) is not SignatureMetadata:
            raise ControlSuiteError("a frozen control suite requires signature metadata")
        if self.signature.signed_at < self.frozen_at:
            raise ControlSuiteError("control-suite signature cannot predate the freeze")
        if self.signature.signed_content_sha256 != self.signature_payload_sha256:
            raise ControlSuiteError("control-suite signature does not bind the frozen payload")

    def _scientific_payload(self) -> dict[str, object]:
        return {
            "controls": [control.as_dict() for control in self.controls],
            "instrument_setting_id": self.instrument_setting_id,
            "metadata": _thaw_json(self.metadata),
            "schema_version": self.schema_version,
        }

    @property
    def suite_id(self) -> str:
        return canonical_sha256(self._scientific_payload())

    @property
    def signature_payload_sha256(self) -> str:
        return canonical_sha256(
            _suite_payload(
                schema_version=self.schema_version,
                instrument_setting_id=self.instrument_setting_id,
                controls=self.controls,
                status=self.status,
                frozen_at=self.frozen_at,
                review=self.review,
                metadata=self.metadata,
            )
        )

    @property
    def structurally_frozen(self) -> bool:
        """Whether required freeze metadata is present and content-bound.

        This property is not a scientific suitability decision or target-run authority.
        """

        return self.status == "frozen"

    def as_dict(self) -> dict[str, object]:
        return _suite_payload(
            schema_version=self.schema_version,
            instrument_setting_id=self.instrument_setting_id,
            controls=self.controls,
            status=self.status,
            frozen_at=self.frozen_at,
            review=self.review,
            metadata=self.metadata,
        ) | {"signature": None if self.signature is None else self.signature.as_dict()}


def _reconstruct_review(review: ReviewMetadata | None) -> ReviewMetadata | None:
    if review is None:
        return None
    if type(review) is not ReviewMetadata:
        raise ControlSuiteError("review must be an exact ReviewMetadata")
    return ReviewMetadata(
        reviewer_id=review.reviewer_id,
        reviewed_at=review.reviewed_at,
        report_sha256=review.report_sha256,
        outcome=review.outcome,
    )


def _reconstruct_signature(signature: SignatureMetadata | None) -> SignatureMetadata | None:
    if signature is None:
        return None
    if type(signature) is not SignatureMetadata:
        raise ControlSuiteError("signature must be exact SignatureMetadata")
    return SignatureMetadata(
        scheme=signature.scheme,
        key_id=signature.key_id,
        signature=signature.signature,
        signed_content_sha256=signature.signed_content_sha256,
        signed_at=signature.signed_at,
    )


def _reconstruct_evidence(reference: EvidenceReference) -> EvidenceReference:
    if type(reference) is not EvidenceReference:
        raise ControlSuiteError("evidence reference must be exact EvidenceReference")
    return EvidenceReference(reference=reference.reference, sha256=reference.sha256)


def _reconstruct_content(reference: ContentReference) -> ContentReference:
    if type(reference) is not ContentReference:
        raise ControlSuiteError("content reference must be exact ContentReference")
    return ContentReference(
        label=reference.label,
        sha256=reference.sha256,
        size_bytes=reference.size_bytes,
    )


def _reconstruct_control(control: ControlDefinition) -> ControlDefinition:
    if type(control) is not ControlDefinition:
        raise ControlSuiteError("control must be exact ControlDefinition")
    truth = control.truth
    if type(truth) is not TruthRecord:
        raise ControlSuiteError("control truth must be exact TruthRecord")
    reconstructed_truth = TruthRecord(
        basis=[_reconstruct_evidence(item) for item in truth.basis],
        assertion=_thaw_json(truth.assertion),
        independence_statement=truth.independence_statement,
        established_at=truth.established_at,
        recorded_at=truth.recorded_at,
        review=_reconstruct_review(truth.review),
        metadata=_thaw_json(truth.metadata),
    )
    epochs: list[ControlEpoch] = []
    for epoch in control.epochs:
        if type(epoch) is not ControlEpoch:
            raise ControlSuiteError("control epoch must be exact ControlEpoch")
        epochs.append(
            ControlEpoch(
                epoch_id=epoch.epoch_id,
                night_id=epoch.night_id,
                setting_id=epoch.setting_id,
                inputs=[_reconstruct_content(item) for item in epoch.inputs],
                included=epoch.included,
                exclusion_reason=epoch.exclusion_reason,
                metadata=_thaw_json(epoch.metadata),
            )
        )
    return ControlDefinition(
        label=control.label,
        kind=control.kind,
        setting_id=control.setting_id,
        truth=reconstructed_truth,
        epochs=epochs,
        suitability_basis=[_reconstruct_evidence(item) for item in control.suitability_basis],
        exclusion_rule=_thaw_json(control.exclusion_rule),
        metadata=_thaw_json(control.metadata),
    )


def _reconstruct_suite(suite: ControlSuite) -> ControlSuite:
    return ControlSuite(
        schema_version=suite.schema_version,
        instrument_setting_id=suite.instrument_setting_id,
        controls=[_reconstruct_control(control) for control in suite.controls],
        status=suite.status,
        frozen_at=suite.frozen_at,
        review=_reconstruct_review(suite.review),
        signature=_reconstruct_signature(suite.signature),
        metadata=_thaw_json(suite.metadata),
    )


def validate_control_suite(
    suite: ControlSuite,
    *,
    require_frozen: bool = True,
) -> ControlSuite:
    """Validate structural completeness without judging scientific suitability."""

    if type(suite) is not ControlSuite:
        raise ControlSuiteError("suite must be an exact ControlSuite")
    if type(require_frozen) is not bool:
        raise ControlSuiteError("require_frozen must be a native boolean")

    checked = _reconstruct_suite(suite)

    _unique([control.label for control in checked.controls], "control labels")
    if len({control.control_id for control in checked.controls}) != len(checked.controls):
        raise ControlSuiteError("control content identities must be unique")
    kinds = {control.kind for control in checked.controls}
    missing_kinds = sorted(_CONTROL_KINDS - kinds)
    if missing_kinds:
        raise ControlSuiteError(f"control suite is missing required kinds: {missing_kinds}")
    if any(control.setting_id != checked.instrument_setting_id for control in checked.controls):
        raise ControlSuiteError("every control must use the suite instrument_setting_id")

    epoch_ids: list[str] = []
    for control in checked.controls:
        if control.truth.review.outcome != "accepted":
            raise ControlSuiteError(f"control {control.label!r} truth review was not accepted")
        if checked.frozen_at is not None:
            if control.truth.recorded_at > checked.frozen_at:
                raise ControlSuiteError(
                    f"control {control.label!r} truth was recorded after freeze"
                )
            if control.truth.review.reviewed_at > checked.frozen_at:
                raise ControlSuiteError(f"control {control.label!r} truth review followed freeze")
        if (
            checked.review is not None
            and control.truth.review.reviewed_at > checked.review.reviewed_at
        ):
            raise ControlSuiteError(
                f"control {control.label!r} truth review followed the enclosing suite review"
            )
        epoch_ids.extend(epoch.epoch_id for epoch in control.epochs)
    _unique(epoch_ids, "control epoch IDs across the suite")

    if require_frozen and not checked.structurally_frozen:
        raise ControlSuiteError("draft control suite fails closed when a frozen suite is required")
    return suite


__all__ = [
    "CONTROL_SUITE_SCHEMA_VERSION",
    "ContentReference",
    "ControlDefinition",
    "ControlEpoch",
    "ControlKind",
    "ControlSuite",
    "ControlSuiteError",
    "ControlSuiteStatus",
    "EvidenceReference",
    "ReviewMetadata",
    "ReviewOutcome",
    "SignatureMetadata",
    "TruthRecord",
    "control_suite_signature_payload_sha256",
    "validate_control_suite",
]
