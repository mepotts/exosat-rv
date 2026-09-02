"""Content-bound structural decision register for the draft M38 protocol.

The register enumerates every blocking decision, but deliberately supplies no selected value.
It can establish that caller-supplied decisions are complete, reviewed, frozen, and bound to
detached signature metadata.  It cannot judge the scientific basis, authenticate people or
keys, verify a cryptographic signature, create observer blindness, or authorise a target run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from exosat_rv.m38.control_suite import (
    EvidenceReference,
    ReviewMetadata,
    SignatureMetadata,
    _native_string,
    _sha256,
    _strict_json_snapshot,
    _thaw_json,
    _typed_tuple,
    _unique,
    _utc_timestamp,
)
from exosat_rv.m38.provenance import canonical_sha256

DECISION_REGISTER_SCHEMA_VERSION = 1
DecisionStatus = Literal["unresolved", "resolved"]
DecisionRegisterStatus = Literal["draft", "frozen"]

M38_DECISION_KEYS = (
    "roles_and_enforcement",
    "claim_and_target_data_regime",
    "control_targets_and_truth",
    "extraction_family_and_template_scope",
    "target_raw_calibration_manifest_and_reduction",
    "seed_template",
    "order_estimator_and_epoch_qc",
    "convergence_policy",
    "cross_fitted_template_construction",
    "end_to_end_injection_operator",
    "selection_validation_injection_plans",
    "recovery_uncertainty_and_equivalence",
    "common_orders_failures_and_fit_quality",
    "injection_attrition_policy",
    "period_search_design",
    "adaptive_familywise_null_calibration",
    "detection_completeness_design",
    "frozen_runtime_and_signing",
)
_DECISION_KEY_SET = frozenset(M38_DECISION_KEYS)
_ROLE_KEY = "roles_and_enforcement"
_ROLE_ASSIGNMENT_FIELDS = (
    "development_team",
    "holdout_custodian",
    "blind_executor",
    "unblinding_reviewer",
    "independent_reviewer",
)


class DecisionRegisterError(ValueError):
    """Raised when a decision or register is incomplete or structurally invalid."""


def _translated(callable_value, *args, **kwargs):
    try:
        return callable_value(*args, **kwargs)
    except ValueError as exc:
        raise DecisionRegisterError(str(exc)) from exc


def _decision_selection_payload(
    *,
    key: str,
    status: DecisionStatus,
    selected_value: object | None,
    rationale: str | None,
    basis: Sequence[EvidenceReference],
    metadata: object,
) -> dict[str, object]:
    return {
        "basis": [item.as_dict() for item in basis],
        "key": key,
        "metadata": _thaw_json(metadata),
        "rationale": rationale,
        "selected_value": None if selected_value is None else _thaw_json(selected_value),
        "status": status,
    }


def _decision_signature_payload(
    *,
    key: str,
    status: DecisionStatus,
    selected_value: object | None,
    rationale: str | None,
    basis: Sequence[EvidenceReference],
    review: ReviewMetadata | None,
    frozen_at: str | None,
    metadata: object,
) -> dict[str, object]:
    selection = _decision_selection_payload(
        key=key,
        status=status,
        selected_value=selected_value,
        rationale=rationale,
        basis=basis,
        metadata=metadata,
    )
    return selection | {
        "decision_id": canonical_sha256(selection),
        "frozen_at": frozen_at,
        "review": None if review is None else review.as_dict(),
    }


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One blocking decision, including its evidence, review, freeze, and signature metadata."""

    key: str
    status: DecisionStatus
    selected_value: dict[str, object] | None
    rationale: str | None
    basis: Sequence[EvidenceReference]
    review: ReviewMetadata | None
    frozen_at: str | None
    signature: SignatureMetadata | None
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        key = _translated(_native_string, self.key, "decision key")
        if key not in _DECISION_KEY_SET:
            raise DecisionRegisterError(f"unknown M38 blocking decision key: {key!r}")
        object.__setattr__(self, "key", key)
        if type(self.status) is not str or self.status not in {"unresolved", "resolved"}:
            raise DecisionRegisterError(
                "decision status must be exactly 'unresolved' or 'resolved'"
            )
        basis = _translated(_typed_tuple, self.basis, "decision basis", EvidenceReference)
        _translated(_unique, [item.reference for item in basis], "decision basis references")
        object.__setattr__(self, "basis", basis)
        object.__setattr__(
            self,
            "metadata",
            _translated(
                _strict_json_snapshot,
                self.metadata,
                "decision metadata",
                require_object=True,
            ),
        )

        if self.status == "unresolved":
            if any(
                value is not None
                for value in (
                    self.selected_value,
                    self.rationale,
                    self.review,
                    self.frozen_at,
                    self.signature,
                )
            ):
                raise DecisionRegisterError(
                    "an unresolved decision cannot carry a selection, rationale, review, freeze, "
                    "or signature"
                )
            return

        object.__setattr__(
            self,
            "selected_value",
            _translated(
                _strict_json_snapshot,
                self.selected_value,
                "selected_value",
                require_object=True,
                require_nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "rationale",
            _translated(_native_string, self.rationale, "decision rationale"),
        )
        if not basis:
            raise DecisionRegisterError("a resolved decision requires at least one basis artifact")
        if type(self.review) is not ReviewMetadata:
            raise DecisionRegisterError("a resolved decision requires exact review metadata")
        if self.review.outcome != "accepted":
            raise DecisionRegisterError("a resolved decision requires an accepted review")
        frozen_at = _translated(_utc_timestamp, self.frozen_at, "decision frozen_at")
        object.__setattr__(self, "frozen_at", frozen_at)
        if self.review.reviewed_at > frozen_at:
            raise DecisionRegisterError("decision review cannot follow the decision freeze")
        if self.signature is not None:
            if type(self.signature) is not SignatureMetadata:
                raise DecisionRegisterError("decision signature must be exact SignatureMetadata")
            if self.signature.signed_at < frozen_at:
                raise DecisionRegisterError("decision signature cannot predate its freeze")
            if self.signature.signed_content_sha256 != self.signature_payload_sha256:
                raise DecisionRegisterError("decision signature does not bind its frozen payload")

    def _selection_payload(self) -> dict[str, object]:
        return _decision_selection_payload(
            key=self.key,
            status=self.status,
            selected_value=self.selected_value,
            rationale=self.rationale,
            basis=self.basis,
            metadata=self.metadata,
        )

    @property
    def decision_id(self) -> str:
        return canonical_sha256(self._selection_payload())

    @property
    def signature_payload_sha256(self) -> str:
        return canonical_sha256(
            _decision_signature_payload(
                key=self.key,
                status=self.status,
                selected_value=self.selected_value,
                rationale=self.rationale,
                basis=self.basis,
                review=self.review,
                frozen_at=self.frozen_at,
                metadata=self.metadata,
            )
        )

    @property
    def structurally_complete(self) -> bool:
        """Whether this decision is resolved and has bound signature metadata."""

        return self.status == "resolved" and self.signature is not None

    def as_dict(self) -> dict[str, object]:
        return _decision_signature_payload(
            key=self.key,
            status=self.status,
            selected_value=self.selected_value,
            rationale=self.rationale,
            basis=self.basis,
            review=self.review,
            frozen_at=self.frozen_at,
            metadata=self.metadata,
        ) | {"signature": None if self.signature is None else self.signature.as_dict()}


def _register_payload(
    *,
    schema_version: int,
    protocol_sha256: str,
    decisions: Sequence[DecisionRecord],
    status: DecisionRegisterStatus,
    frozen_at: str | None,
    review: ReviewMetadata | None,
    metadata: object,
) -> dict[str, object]:
    register_content = {
        "decisions": [decision.as_dict() for decision in decisions],
        "metadata": _thaw_json(metadata),
        "protocol_sha256": protocol_sha256,
        "schema_version": schema_version,
    }
    return register_content | {
        "frozen_at": frozen_at,
        "register_id": canonical_sha256(register_content),
        "review": None if review is None else review.as_dict(),
        "status": status,
    }


@dataclass(frozen=True, slots=True)
class DecisionRegister:
    """Immutable snapshot covering the complete M38 blocking-decision namespace."""

    schema_version: int
    protocol_sha256: str
    decisions: Sequence[DecisionRecord]
    status: DecisionRegisterStatus
    frozen_at: str | None
    review: ReviewMetadata | None
    signature: SignatureMetadata | None
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or (
            self.schema_version != DECISION_REGISTER_SCHEMA_VERSION
        ):
            raise DecisionRegisterError("unsupported decision-register schema version")
        object.__setattr__(
            self,
            "protocol_sha256",
            _translated(_sha256, self.protocol_sha256, "protocol_sha256"),
        )
        decisions = _translated(_typed_tuple, self.decisions, "decisions", DecisionRecord)
        object.__setattr__(self, "decisions", decisions)
        if type(self.status) is not str or self.status not in {"draft", "frozen"}:
            raise DecisionRegisterError("register status must be exactly 'draft' or 'frozen'")
        object.__setattr__(
            self,
            "metadata",
            _translated(
                _strict_json_snapshot,
                self.metadata,
                "register metadata",
                require_object=True,
            ),
        )

        if self.status == "draft":
            if any(value is not None for value in (self.frozen_at, self.review, self.signature)):
                raise DecisionRegisterError(
                    "a draft register cannot carry register freeze metadata"
                )
            return

        frozen_at = _translated(_utc_timestamp, self.frozen_at, "register frozen_at")
        object.__setattr__(self, "frozen_at", frozen_at)
        if type(self.review) is not ReviewMetadata:
            raise DecisionRegisterError("a frozen register requires exact review metadata")
        if self.review.outcome != "accepted":
            raise DecisionRegisterError("a frozen register requires an accepted review")
        if self.review.reviewed_at > frozen_at:
            raise DecisionRegisterError("register review cannot follow the register freeze")
        if self.signature is not None:
            if type(self.signature) is not SignatureMetadata:
                raise DecisionRegisterError("register signature must be exact SignatureMetadata")
            if self.signature.signed_at < frozen_at:
                raise DecisionRegisterError("register signature cannot predate its freeze")
            if self.signature.signed_content_sha256 != self.signature_payload_sha256:
                raise DecisionRegisterError("register signature does not bind its frozen payload")

    def _content_payload(self) -> dict[str, object]:
        return {
            "decisions": [decision.as_dict() for decision in self.decisions],
            "metadata": _thaw_json(self.metadata),
            "protocol_sha256": self.protocol_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def register_id(self) -> str:
        return canonical_sha256(self._content_payload())

    @property
    def signature_payload_sha256(self) -> str:
        return canonical_sha256(
            _register_payload(
                schema_version=self.schema_version,
                protocol_sha256=self.protocol_sha256,
                decisions=self.decisions,
                status=self.status,
                frozen_at=self.frozen_at,
                review=self.review,
                metadata=self.metadata,
            )
        )

    @property
    def structurally_frozen(self) -> bool:
        """Whether register-level freeze metadata is present and content-bound."""

        return self.status == "frozen" and self.signature is not None

    def as_dict(self) -> dict[str, object]:
        return _register_payload(
            schema_version=self.schema_version,
            protocol_sha256=self.protocol_sha256,
            decisions=self.decisions,
            status=self.status,
            frozen_at=self.frozen_at,
            review=self.review,
            metadata=self.metadata,
        ) | {"signature": None if self.signature is None else self.signature.as_dict()}


def _reconstruct_review(review: ReviewMetadata | None) -> ReviewMetadata | None:
    if review is None:
        return None
    if type(review) is not ReviewMetadata:
        raise DecisionRegisterError("review must be exact ReviewMetadata")
    return _translated(
        ReviewMetadata,
        reviewer_id=review.reviewer_id,
        reviewed_at=review.reviewed_at,
        report_sha256=review.report_sha256,
        outcome=review.outcome,
    )


def _reconstruct_signature(signature: SignatureMetadata | None) -> SignatureMetadata | None:
    if signature is None:
        return None
    if type(signature) is not SignatureMetadata:
        raise DecisionRegisterError("signature must be exact SignatureMetadata")
    return _translated(
        SignatureMetadata,
        scheme=signature.scheme,
        key_id=signature.key_id,
        signature=signature.signature,
        signed_content_sha256=signature.signed_content_sha256,
        signed_at=signature.signed_at,
    )


def _reconstruct_evidence(reference: EvidenceReference) -> EvidenceReference:
    if type(reference) is not EvidenceReference:
        raise DecisionRegisterError("basis item must be exact EvidenceReference")
    return _translated(
        EvidenceReference,
        reference=reference.reference,
        sha256=reference.sha256,
    )


def _reconstruct_decision(decision: DecisionRecord) -> DecisionRecord:
    if type(decision) is not DecisionRecord:
        raise DecisionRegisterError("decision must be exact DecisionRecord")
    return DecisionRecord(
        key=decision.key,
        status=decision.status,
        selected_value=(
            None if decision.selected_value is None else _thaw_json(decision.selected_value)
        ),
        rationale=decision.rationale,
        basis=[_reconstruct_evidence(item) for item in decision.basis],
        review=_reconstruct_review(decision.review),
        frozen_at=decision.frozen_at,
        signature=_reconstruct_signature(decision.signature),
        metadata=_thaw_json(decision.metadata),
    )


def _reconstruct_register(register: DecisionRegister) -> DecisionRegister:
    return DecisionRegister(
        schema_version=register.schema_version,
        protocol_sha256=register.protocol_sha256,
        decisions=[_reconstruct_decision(decision) for decision in register.decisions],
        status=register.status,
        frozen_at=register.frozen_at,
        review=_reconstruct_review(register.review),
        signature=_reconstruct_signature(register.signature),
        metadata=_thaw_json(register.metadata),
    )


def _role_assignments(
    decision: DecisionRecord,
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    value = _thaw_json(decision.selected_value)
    if type(value) is not dict:
        raise DecisionRegisterError("roles decision selected_value must be a native JSON object")
    expected_fields = set(_ROLE_ASSIGNMENT_FIELDS) | {"enforcement_mechanism"}
    missing = sorted(expected_fields - set(value))
    unexpected = sorted(set(value) - expected_fields)
    if missing:
        raise DecisionRegisterError(f"roles decision is missing assignments: {missing}")
    if unexpected:
        raise DecisionRegisterError(f"roles decision has unexpected fields: {unexpected}")
    mechanism = value.get("enforcement_mechanism")
    if type(mechanism) is not dict or not mechanism:
        raise DecisionRegisterError("roles decision requires a non-empty enforcement_mechanism")
    expected_mechanism_fields = {"mechanism_sha256", "signature_key_owners"}
    if set(mechanism) != expected_mechanism_fields:
        raise DecisionRegisterError(
            "enforcement_mechanism must contain exactly mechanism_sha256 and signature_key_owners"
        )
    _translated(_sha256, mechanism["mechanism_sha256"], "mechanism_sha256")

    assignments: dict[str, tuple[str, ...]] = {}
    for field in _ROLE_ASSIGNMENT_FIELDS:
        principals = value[field]
        if type(principals) is not list or not principals:
            raise DecisionRegisterError(f"roles decision {field} must be a non-empty native list")
        parsed = tuple(_translated(_native_string, principal, field) for principal in principals)
        _translated(_unique, parsed, f"{field} principals")
        assignments[field] = parsed

    ownership: dict[str, str] = {}
    for field, principals in assignments.items():
        for principal in principals:
            folded = principal.casefold()
            if folded in ownership:
                raise DecisionRegisterError(
                    f"incompatible role collision between {ownership[folded]} and {field}: "
                    f"{principal!r}"
                )
            ownership[folded] = field
    raw_key_owners = mechanism["signature_key_owners"]
    if type(raw_key_owners) is not dict or not raw_key_owners:
        raise DecisionRegisterError("signature_key_owners must be a non-empty native object")
    key_owners: dict[str, str] = {}
    folded_keys: set[str] = set()
    declared_principals = {
        principal.casefold() for principals in assignments.values() for principal in principals
    }
    for raw_key_id, raw_principal in raw_key_owners.items():
        key_id = _translated(_native_string, raw_key_id, "signature key ID")
        principal = _translated(_native_string, raw_principal, "signature key owner")
        folded_key = key_id.casefold()
        if folded_key in folded_keys:
            raise DecisionRegisterError("signature key IDs must be case-insensitively unique")
        if principal.casefold() not in declared_principals:
            raise DecisionRegisterError(
                f"signature key owner is not a declared role principal: {principal!r}"
            )
        folded_keys.add(folded_key)
        key_owners[folded_key] = principal
    return assignments, key_owners


def validate_decision_register(
    register: DecisionRegister,
    *,
    require_frozen: bool = True,
) -> DecisionRegister:
    """Fail closed unless all 18 decisions are resolved, reviewed, frozen, and signed.

    Passing this validator establishes structural closure only.  It is not cryptographic
    signature verification, scientific approval, observer blindness, or run authority.
    """

    if type(register) is not DecisionRegister:
        raise DecisionRegisterError("register must be an exact DecisionRegister")
    if type(require_frozen) is not bool:
        raise DecisionRegisterError("require_frozen must be a native boolean")

    checked = _reconstruct_register(register)

    keys = [decision.key for decision in checked.decisions]
    _translated(_unique, keys, "decision keys")
    key_set = set(keys)
    missing = sorted(_DECISION_KEY_SET - key_set)
    unexpected = sorted(key_set - _DECISION_KEY_SET)
    if missing or unexpected:
        raise DecisionRegisterError(
            f"decision register key mismatch; missing={missing}, unexpected={unexpected}"
        )
    if tuple(keys) != M38_DECISION_KEYS:
        raise DecisionRegisterError("decision register keys must use the canonical M38 order")

    unresolved = [decision.key for decision in checked.decisions if decision.status != "resolved"]
    if unresolved:
        raise DecisionRegisterError(f"unresolved decisions fail closed: {unresolved}")
    unsigned = [
        decision.key for decision in checked.decisions if not decision.structurally_complete
    ]
    if unsigned:
        raise DecisionRegisterError(f"decisions lack bound signature metadata: {unsigned}")

    by_key = {decision.key: decision for decision in checked.decisions}
    assignments, key_owners = _role_assignments(by_key[_ROLE_KEY])
    independent_reviewers = {
        principal.casefold() for principal in assignments["independent_reviewer"]
    }
    for decision in checked.decisions:
        if decision.review is None or (
            decision.review.reviewer_id.casefold() not in independent_reviewers
        ):
            raise DecisionRegisterError(
                f"decision review is not bound to a declared independent reviewer: {decision.key}"
            )
        if decision.signature is None or decision.signature.key_id.casefold() not in key_owners:
            raise DecisionRegisterError(
                f"decision signature key lacks frozen ownership: {decision.key}"
            )
    if checked.review is not None and (
        checked.review.reviewer_id.casefold() not in independent_reviewers
    ):
        raise DecisionRegisterError("register review is not bound to an independent reviewer")
    if checked.signature is not None and checked.signature.key_id.casefold() not in key_owners:
        raise DecisionRegisterError("register signature key lacks frozen ownership")

    if checked.frozen_at is not None:
        late = [
            decision.key
            for decision in checked.decisions
            if decision.frozen_at is None or decision.frozen_at > checked.frozen_at
        ]
        if late:
            raise DecisionRegisterError(f"decisions were not frozen before the register: {late}")
    if checked.review is not None:
        late_reviews = [
            decision.key
            for decision in checked.decisions
            if decision.review is None or decision.review.reviewed_at > checked.review.reviewed_at
        ]
        if late_reviews:
            raise DecisionRegisterError(
                f"decision reviews followed the enclosing register review: {late_reviews}"
            )
        late_signatures = [
            decision.key
            for decision in checked.decisions
            if decision.signature is None
            or decision.signature.signed_at > checked.review.reviewed_at
        ]
        if late_signatures:
            raise DecisionRegisterError(
                f"decision signatures followed the enclosing register review: {late_signatures}"
            )
    if require_frozen and not checked.structurally_frozen:
        raise DecisionRegisterError(
            "draft or unsigned register fails closed when freeze is required"
        )
    return register


__all__ = [
    "DECISION_REGISTER_SCHEMA_VERSION",
    "M38_DECISION_KEYS",
    "DecisionRecord",
    "DecisionRegister",
    "DecisionRegisterError",
    "DecisionRegisterStatus",
    "DecisionStatus",
    "validate_decision_register",
]
