"""Control-only, uncertainty-aware injection scoring and arm selection.

This module contains no data loaders, target identities, amplitude choices, thresholds, or
default scientific policy.  Callers supply labeled reference/injection measurements, a frozen
reference-valid mask, an explicit :class:`AttritionPolicy`, bootstrap settings, equivalence
delta, a content-digest arm roster/configuration identity, hidden-plan and hidden-bootstrap-seed
commitments, and every external eligibility gate.  Array evidence is copied onto immutable byte
buffers, score IDs are recomputed from the full audit, and every arm assessment deterministically
replays its bootstrap evidence.

Responses use the exact same reference-defined order cells on both sides of each difference.
An injected fit that loses even one reference-valid order is ineligible for primary
selection; surviving orders are never allowed to rescue it.  Paired-response uncertainties
are supplied by the caller and never inferred by treating the reference and injected fits as
independent.  The uncertainty of an unweighted common-order mean uses the correlation-agnostic
upper bound ``mean(order standard deviations)`` rather than independence quadrature.

The percentile cluster bootstrap implemented here is a generic deterministic mechanism, not
a coverage guarantee.  Its repetition count, confidence level, attrition policy, and
equivalence delta, paired-response covariance/weight interpretation, and cluster minimum must
be independently calibrated and frozen on simulations or declared controls before any
claim-bearing use.

The in-memory hidden-plan digest is not proof of precommitment timing.  A signed or timestamped
external manifest must establish that the roster, configuration digests, hidden-plan ID, and
hidden bootstrap seed were frozen before target access.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Literal, TypeAlias

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray: TypeAlias = NDArray[np.float64]
BoolArray: TypeAlias = NDArray[np.bool_]
OrderStatus: TypeAlias = Literal[
    "common",
    "injection_lost",
    "reference_excluded",
    "missing_response",
]
AttritionAction: TypeAlias = Literal["fail_primary"]
AssessmentStage: TypeAlias = Literal["selection", "hidden_validation"]


class SelectionError(RuntimeError):
    """Base class for selection, fitting, and winner-selection failures."""


class SelectionDataError(SelectionError, ValueError):
    """Raised when labeled response inputs violate a frozen shape or identity contract."""


class NoEligibleArmError(SelectionError):
    """Raised when no arm passes every predeclared eligibility gate."""


def _labels(
    values: Sequence[str],
    name: str,
    *,
    expected_length: int | None = None,
    unique: bool,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise SelectionDataError(f"{name} must be a sequence of labels")
    result = tuple(values)
    if (not result and not allow_empty) or any(
        type(value) is not str or not value for value in result
    ):
        raise SelectionDataError(f"{name} must contain non-empty strings")
    if expected_length is not None and len(result) != expected_length:
        raise SelectionDataError(f"{name} must contain {expected_length} labels")
    if unique and len(set(result)) != len(result):
        raise SelectionDataError(f"{name} must not contain duplicates")
    return result


def _native_string(value: str, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a native string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _native_boolean(value: bool, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a native boolean")
    return value


def _native_nonnegative_integer(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{name} must be a non-negative native integer")
    return value


def _native_float(value: float, name: str) -> float:
    if type(value) is not float:
        raise TypeError(f"{name} must be a native float")
    if not np.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _native_optional_float(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    return _native_float(value, name)


def _float_matrix(value: ArrayLike, name: str) -> FloatArray:
    try:
        result = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SelectionDataError(f"{name} must be a rectangular numeric matrix") from exc
    if result.ndim != 2 or 0 in result.shape:
        raise SelectionDataError(f"{name} must be a non-empty two-dimensional matrix")
    return _immutable_array(result)


def _float_vector(value: ArrayLike, name: str, *, allow_nan: bool = False) -> FloatArray:
    try:
        result = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SelectionDataError(f"{name} must be a numeric vector") from exc
    if result.ndim != 1 or result.size == 0:
        raise SelectionDataError(f"{name} must be a non-empty one-dimensional vector")
    valid = np.isfinite(result) | (allow_nan & np.isnan(result))
    if not np.all(valid):
        raise SelectionDataError(f"{name} contains an invalid value")
    return _immutable_array(result)


def _bool_matrix(value: ArrayLike, name: str, shape: tuple[int, int]) -> BoolArray:
    result = np.asarray(value)
    if result.dtype.kind != "b" or result.shape != shape:
        raise SelectionDataError(f"{name} must be a boolean matrix with shape {shape}")
    copied = np.array(result, dtype=np.bool_, copy=True, order="C")
    return _immutable_array(copied)


def _immutable_array(value: NDArray) -> NDArray:
    """Copy an array onto immutable bytes, preventing write-flag re-enablement."""

    contiguous = np.ascontiguousarray(value)
    frozen = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )
    if frozen.flags.writeable:
        raise SelectionDataError("failed to create immutable array storage")
    return frozen


def _validate_masked_measurements(
    rv: FloatArray,
    uncertainty: FloatArray,
    valid_mask: BoolArray,
    *,
    prefix: str,
) -> None:
    if uncertainty.shape != rv.shape:
        raise SelectionDataError(f"{prefix}_uncertainty must match the RV shape")
    valid_bad = valid_mask & (~np.isfinite(rv) | ~np.isfinite(uncertainty) | (uncertainty <= 0.0))
    if np.any(valid_bad):
        raise SelectionDataError(
            f"{prefix} valid cells require finite RVs and positive finite uncertainties"
        )
    invalid_bad = ~valid_mask & (~np.isnan(rv) | ~np.isnan(uncertainty))
    if np.any(invalid_bad):
        raise SelectionDataError(
            f"{prefix} invalid cells must use NaN RV and uncertainty sentinels"
        )


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be a positive integer")
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _nonnegative_int(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return result


def _finite_float(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise TypeError(f"{name} must be a finite scalar")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{name} must be a finite scalar") from exc
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _digest_id(value: str, name: str) -> str:
    _native_string(value, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SelectionDataError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _float_token(value: float) -> str:
    finite = _finite_float(value, "canonical float")
    if finite == 0.0:
        finite = 0.0
    return finite.hex()


def _velocity_pattern_identity(plan: InjectionPlan) -> str:
    by_epoch = sorted(
        (
            epoch_id,
            _float_token(float(plan.velocities[index])),
        )
        for index, epoch_id in enumerate(plan.epoch_ids)
    )
    return _canonical_sha256({"epoch_velocity": by_epoch})


def _plan_identity(
    epoch_ids: tuple[str, ...],
    plans: tuple[InjectionPlan, ...],
) -> str:
    return _canonical_sha256(
        {
            "epoch_ids": sorted(epoch_ids),
            # Labels and input order cannot turn an identical velocity bank into a distinct
            # hidden-validation plan.
            "velocity_patterns": sorted(_velocity_pattern_identity(plan) for plan in plans),
        }
    )


@dataclass(frozen=True, slots=True)
class ReferenceResponse:
    """Frozen labeled reference RVs and the reference-defined valid-order mask.

    Matrices have shape ``(epoch, order)``.  A valid cell must have a finite RV and positive
    finite uncertainty.  An invalid cell must carry NaN in both matrices, making the frozen
    mask impossible to change implicitly through later finite-value tests.
    """

    epoch_ids: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    rv: FloatArray
    uncertainty: FloatArray
    valid_mask: BoolArray

    def __post_init__(self) -> None:
        rv = _float_matrix(self.rv, "reference_rv")
        uncertainty = _float_matrix(self.uncertainty, "reference_uncertainty")
        epoch_ids = _labels(
            self.epoch_ids,
            "epoch_ids",
            expected_length=rv.shape[0],
            unique=True,
        )
        cluster_ids = _labels(
            self.cluster_ids,
            "cluster_ids",
            expected_length=rv.shape[0],
            unique=False,
        )
        order_ids = _labels(
            self.order_ids,
            "order_ids",
            expected_length=rv.shape[1],
            unique=True,
        )
        valid_mask = _bool_matrix(self.valid_mask, "reference_valid_mask", rv.shape)
        _validate_masked_measurements(
            rv,
            uncertainty,
            valid_mask,
            prefix="reference",
        )
        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "cluster_ids", cluster_ids)
        object.__setattr__(self, "order_ids", order_ids)
        object.__setattr__(self, "rv", rv)
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "valid_mask", valid_mask)


@dataclass(frozen=True, slots=True)
class InjectionPlan:
    """One labeled, caller-planned epoch-aligned velocity pattern."""

    injection_id: str
    epoch_ids: tuple[str, ...]
    velocities: FloatArray

    def __post_init__(self) -> None:
        _native_string(self.injection_id, "injection_id")
        velocities = _float_vector(self.velocities, "injected_velocities")
        epoch_ids = _labels(
            self.epoch_ids,
            "injection epoch_ids",
            expected_length=velocities.size,
            unique=True,
        )
        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "velocities", velocities)


@dataclass(frozen=True, slots=True)
class InjectedResponse:
    """One planned injection's labeled epoch-by-order fitted response.

    ``response_uncertainty`` is the caller-supplied uncertainty of the paired difference for
    each common cell.  It is not derived from the two fit uncertainties.  Cells that are not
    common against the frozen reference mask must carry NaN and are checked during scoring.
    """

    injection_id: str
    epoch_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    rv: FloatArray
    uncertainty: FloatArray
    response_uncertainty: FloatArray
    valid_mask: BoolArray

    def __post_init__(self) -> None:
        _native_string(self.injection_id, "injection_id")
        rv = _float_matrix(self.rv, "injected_rv")
        uncertainty = _float_matrix(self.uncertainty, "injected_uncertainty")
        response_uncertainty = _float_matrix(
            self.response_uncertainty,
            "response_uncertainty",
        )
        epoch_ids = _labels(
            self.epoch_ids,
            "epoch_ids",
            expected_length=rv.shape[0],
            unique=True,
        )
        order_ids = _labels(
            self.order_ids,
            "order_ids",
            expected_length=rv.shape[1],
            unique=True,
        )
        valid_mask = _bool_matrix(self.valid_mask, "injected_valid_mask", rv.shape)
        _validate_masked_measurements(
            rv,
            uncertainty,
            valid_mask,
            prefix="injected",
        )
        if response_uncertainty.shape != rv.shape:
            raise SelectionDataError("response_uncertainty must match the injected RV shape")
        response_bad = ~(
            np.isnan(response_uncertainty)
            | (np.isfinite(response_uncertainty) & (response_uncertainty > 0.0))
        )
        if np.any(response_bad):
            raise SelectionDataError(
                "response_uncertainty cells must be NaN or positive and finite"
            )
        if np.any(~valid_mask & ~np.isnan(response_uncertainty)):
            raise SelectionDataError("injected-invalid cells require NaN response_uncertainty")
        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "order_ids", order_ids)
        object.__setattr__(self, "rv", rv)
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "response_uncertainty", response_uncertainty)
        object.__setattr__(self, "valid_mask", valid_mask)


@dataclass(frozen=True, slots=True)
class AttritionPolicy:
    """Explicit fail-closed primary-selection policy for injected-order losses.

    No primary-selection tolerance has been established, so both explicit maximums must be
    zero and ``attrition_action`` must be ``"fail_primary"``.  This intentionally prevents a
    favorable surviving-order slope from compensating for any injection-only loss.  A future
    diagnostic policy belongs in a separate, explicitly ineligible API.
    """

    minimum_reference_orders: int
    minimum_common_orders: int
    maximum_lost_orders: int
    maximum_lost_fraction: float
    attrition_action: AttritionAction

    def __post_init__(self) -> None:
        minimum_reference = _positive_int(
            self.minimum_reference_orders,
            "minimum_reference_orders",
        )
        minimum_common = _positive_int(self.minimum_common_orders, "minimum_common_orders")
        maximum_lost = _nonnegative_int(self.maximum_lost_orders, "maximum_lost_orders")
        maximum_fraction = _finite_float(
            self.maximum_lost_fraction,
            "maximum_lost_fraction",
        )
        if maximum_fraction < 0.0 or maximum_fraction > 1.0:
            raise ValueError("maximum_lost_fraction must lie in [0, 1]")
        if minimum_common > minimum_reference:
            raise ValueError("minimum_common_orders cannot exceed minimum_reference_orders")
        if maximum_lost != 0 or maximum_fraction != 0.0:
            raise ValueError("primary selection requires zero allowed injection-only order losses")
        attrition_action = _native_string(self.attrition_action, "attrition_action")
        if attrition_action != "fail_primary":
            raise ValueError("attrition_action must be 'fail_primary'")
        object.__setattr__(self, "minimum_reference_orders", minimum_reference)
        object.__setattr__(self, "minimum_common_orders", minimum_common)
        object.__setattr__(self, "maximum_lost_orders", maximum_lost)
        object.__setattr__(self, "maximum_lost_fraction", maximum_fraction)
        object.__setattr__(self, "attrition_action", attrition_action)


@dataclass(frozen=True, slots=True)
class OrderResponseAudit:
    """One planned injection/epoch/order cell and its frozen-mask disposition."""

    injection_id: str
    injected_velocity: float
    epoch_id: str
    order_id: str
    reference_valid: bool
    injected_valid: bool
    common_valid: bool
    injection_only_loss: bool
    status: OrderStatus
    reference_rv: float | None
    reference_uncertainty: float | None
    injected_rv: float | None
    injected_uncertainty: float | None
    response: float | None
    response_uncertainty: float | None

    def __post_init__(self) -> None:
        _native_string(self.injection_id, "order audit injection_id")
        _native_string(self.epoch_id, "order audit epoch_id")
        _native_string(self.order_id, "order audit order_id")
        status = _native_string(self.status, "order audit status")
        if status not in (
            "common",
            "injection_lost",
            "reference_excluded",
            "missing_response",
        ):
            raise SelectionDataError("order audit status is invalid")
        _native_float(self.injected_velocity, "order audit injected_velocity")
        for name in (
            "reference_valid",
            "injected_valid",
            "common_valid",
            "injection_only_loss",
        ):
            _native_boolean(getattr(self, name), f"order audit {name}")
        for name in (
            "reference_rv",
            "reference_uncertainty",
            "injected_rv",
            "injected_uncertainty",
            "response",
            "response_uncertainty",
        ):
            _native_optional_float(getattr(self, name), f"order audit {name}")
        for name in (
            "reference_uncertainty",
            "injected_uncertainty",
            "response_uncertainty",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0.0:
                raise SelectionDataError(f"order audit {name} must be positive")


@dataclass(frozen=True, slots=True)
class EpochInjectionAudit:
    """Common-mask score and attrition decision for one injection and epoch."""

    injection_id: str
    injected_velocity: float
    epoch_id: str
    cluster_id: str
    response_present: bool
    reference_order_count: int
    common_order_count: int
    lost_order_count: int
    lost_fraction: float
    common_order_ids: tuple[str, ...]
    lost_order_ids: tuple[str, ...]
    mean_response: float | None
    mean_response_uncertainty: float | None
    attrition_limit_exceeded: bool
    accepted_for_fit: bool
    failure_reasons: tuple[str, ...]
    order_records: tuple[OrderResponseAudit, ...]

    def __post_init__(self) -> None:
        _native_string(self.injection_id, "epoch audit injection_id")
        _native_string(self.epoch_id, "epoch audit epoch_id")
        _native_string(self.cluster_id, "epoch audit cluster_id")
        _native_float(self.injected_velocity, "epoch audit injected_velocity")
        for name in (
            "response_present",
            "attrition_limit_exceeded",
            "accepted_for_fit",
        ):
            _native_boolean(getattr(self, name), f"epoch audit {name}")
        for name in (
            "reference_order_count",
            "common_order_count",
            "lost_order_count",
        ):
            _native_nonnegative_integer(getattr(self, name), f"epoch audit {name}")
        lost_fraction = _native_float(self.lost_fraction, "epoch audit lost_fraction")
        if not 0.0 <= lost_fraction <= 1.0:
            raise SelectionDataError("epoch audit lost_fraction must lie in [0, 1]")
        common_order_ids = _labels(
            self.common_order_ids,
            "epoch audit common_order_ids",
            unique=True,
            allow_empty=True,
        )
        lost_order_ids = _labels(
            self.lost_order_ids,
            "epoch audit lost_order_ids",
            unique=True,
            allow_empty=True,
        )
        mean_response = _native_optional_float(
            self.mean_response,
            "epoch audit mean_response",
        )
        mean_uncertainty = _native_optional_float(
            self.mean_response_uncertainty,
            "epoch audit mean_response_uncertainty",
        )
        if mean_uncertainty is not None and mean_uncertainty <= 0.0:
            raise SelectionDataError("epoch audit mean_response_uncertainty must be positive")
        failure_reasons = _labels(
            self.failure_reasons,
            "epoch audit failure_reasons",
            unique=False,
            allow_empty=True,
        )
        order_records = tuple(self.order_records)
        if not order_records or any(
            not isinstance(record, OrderResponseAudit) for record in order_records
        ):
            raise SelectionDataError(
                "epoch audit order_records must contain OrderResponseAudit values"
            )
        object.__setattr__(self, "common_order_ids", common_order_ids)
        object.__setattr__(self, "lost_order_ids", lost_order_ids)
        object.__setattr__(self, "mean_response", mean_response)
        object.__setattr__(self, "mean_response_uncertainty", mean_uncertainty)
        object.__setattr__(self, "failure_reasons", failure_reasons)
        object.__setattr__(self, "order_records", order_records)


def _optional_float_token(value: float | None) -> str | None:
    return None if value is None else _float_token(value)


def _order_audit_payload(record: OrderResponseAudit) -> dict[str, object]:
    return {
        "common_valid": record.common_valid,
        "epoch_id": record.epoch_id,
        "injected_rv": _optional_float_token(record.injected_rv),
        "injected_uncertainty": _optional_float_token(record.injected_uncertainty),
        "injected_valid": record.injected_valid,
        "injected_velocity": _float_token(record.injected_velocity),
        "injection_id": record.injection_id,
        "injection_only_loss": record.injection_only_loss,
        "order_id": record.order_id,
        "reference_rv": _optional_float_token(record.reference_rv),
        "reference_uncertainty": _optional_float_token(record.reference_uncertainty),
        "reference_valid": record.reference_valid,
        "response": _optional_float_token(record.response),
        "response_uncertainty": _optional_float_token(record.response_uncertainty),
        "status": record.status,
    }


def _epoch_audit_payload(record: EpochInjectionAudit) -> dict[str, object]:
    return {
        "accepted_for_fit": record.accepted_for_fit,
        "attrition_limit_exceeded": record.attrition_limit_exceeded,
        "cluster_id": record.cluster_id,
        "common_order_count": record.common_order_count,
        "common_order_ids": record.common_order_ids,
        "epoch_id": record.epoch_id,
        "failure_reasons": record.failure_reasons,
        "injected_velocity": _float_token(record.injected_velocity),
        "injection_id": record.injection_id,
        "lost_fraction": _float_token(record.lost_fraction),
        "lost_order_count": record.lost_order_count,
        "lost_order_ids": record.lost_order_ids,
        "mean_response": _optional_float_token(record.mean_response),
        "mean_response_uncertainty": _optional_float_token(record.mean_response_uncertainty),
        "order_records": [_order_audit_payload(value) for value in record.order_records],
        "reference_order_count": record.reference_order_count,
        "response_present": record.response_present,
    }


def _policy_payload(policy: AttritionPolicy) -> dict[str, object]:
    return {
        "attrition_action": policy.attrition_action,
        "maximum_lost_fraction": _float_token(policy.maximum_lost_fraction),
        "maximum_lost_orders": policy.maximum_lost_orders,
        "minimum_common_orders": policy.minimum_common_orders,
        "minimum_reference_orders": policy.minimum_reference_orders,
    }


def _reference_identity(reference: ReferenceResponse) -> str:
    cells: list[dict[str, object]] = []
    for epoch_index, epoch_id in enumerate(reference.epoch_ids):
        for order_index, order_id in enumerate(reference.order_ids):
            valid = bool(reference.valid_mask[epoch_index, order_index])
            cells.append(
                {
                    "epoch_id": epoch_id,
                    "order_id": order_id,
                    "reference_rv": (
                        _float_token(float(reference.rv[epoch_index, order_index]))
                        if valid
                        else None
                    ),
                    "reference_uncertainty": (
                        _float_token(float(reference.uncertainty[epoch_index, order_index]))
                        if valid
                        else None
                    ),
                    "reference_valid": valid,
                }
            )
    return _canonical_sha256(
        {
            "cluster_ids": reference.cluster_ids,
            "epoch_ids": reference.epoch_ids,
            "order_ids": reference.order_ids,
            "reference_cells": cells,
        }
    )


def _reference_identity_from_audits(
    epoch_ids: tuple[str, ...],
    cluster_ids: tuple[str, ...],
    order_ids: tuple[str, ...],
    plans: tuple[InjectionPlan, ...],
    records: tuple[EpochInjectionAudit, ...],
) -> str:
    cells: dict[tuple[str, str], tuple[bool, str | None, str | None]] = {}
    epoch_count = len(epoch_ids)
    for plan_index, _plan in enumerate(plans):
        for epoch_index, epoch_id in enumerate(epoch_ids):
            epoch_record = records[plan_index * epoch_count + epoch_index]
            for order in epoch_record.order_records:
                evidence = (
                    order.reference_valid,
                    _optional_float_token(order.reference_rv),
                    _optional_float_token(order.reference_uncertainty),
                )
                key = (epoch_id, order.order_id)
                previous = cells.setdefault(key, evidence)
                if previous != evidence:
                    raise SelectionDataError(
                        "reference evidence is inconsistent across injection audits"
                    )
    payload_cells = [
        {
            "epoch_id": epoch_id,
            "order_id": order_id,
            "reference_rv": cells[(epoch_id, order_id)][1],
            "reference_uncertainty": cells[(epoch_id, order_id)][2],
            "reference_valid": cells[(epoch_id, order_id)][0],
        }
        for epoch_id in epoch_ids
        for order_id in order_ids
    ]
    return _canonical_sha256(
        {
            "cluster_ids": cluster_ids,
            "epoch_ids": epoch_ids,
            "order_ids": order_ids,
            "reference_cells": payload_cells,
        }
    )


def _score_evidence_identity(
    *,
    plan_id: str,
    reference_evidence_id: str,
    epoch_ids: tuple[str, ...],
    cluster_ids: tuple[str, ...],
    order_ids: tuple[str, ...],
    plans: tuple[InjectionPlan, ...],
    policy: AttritionPolicy,
    records: tuple[EpochInjectionAudit, ...],
    all_present: bool,
    attrition_passed: bool,
    fit_ready: bool,
    failures: tuple[str, ...],
) -> str:
    return _canonical_sha256(
        {
            "all_planned_responses_present": all_present,
            "attrition_gate_passed": attrition_passed,
            "cluster_ids": cluster_ids,
            "epoch_ids": epoch_ids,
            "epoch_records": [_epoch_audit_payload(record) for record in records],
            "failure_reasons": failures,
            "fit_ready": fit_ready,
            "order_ids": order_ids,
            "plan_id": plan_id,
            "plans": [
                {
                    "epoch_ids": plan.epoch_ids,
                    "injection_id": plan.injection_id,
                    "velocities": [_float_token(float(value)) for value in plan.velocities],
                }
                for plan in plans
            ],
            "policy": _policy_payload(policy),
            "reference_evidence_id": reference_evidence_id,
        }
    )


@dataclass(frozen=True, slots=True)
class InjectionScore:
    """Complete planned scoring audit; incomplete cells never yield a subset fit."""

    plan_id: str
    reference_evidence_id: str
    score_id: str
    epoch_ids: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    plans: tuple[InjectionPlan, ...]
    policy: AttritionPolicy
    epoch_records: tuple[EpochInjectionAudit, ...]
    all_planned_responses_present: bool
    attrition_gate_passed: bool
    fit_ready: bool
    failure_reasons: tuple[str, ...]

    @property
    def velocity_pattern_ids(self) -> tuple[str, ...]:
        """Canonical physical-pattern identities, independent of labels and row order."""

        return tuple(_velocity_pattern_identity(plan) for plan in self.plans)

    def __post_init__(self) -> None:
        plan_id = _digest_id(self.plan_id, "plan_id")
        reference_evidence_id = _digest_id(
            self.reference_evidence_id,
            "reference_evidence_id",
        )
        score_id = _digest_id(self.score_id, "score_id")
        epoch_ids = _labels(self.epoch_ids, "score epoch_ids", unique=True)
        cluster_ids = _labels(
            self.cluster_ids,
            "score cluster_ids",
            expected_length=len(epoch_ids),
            unique=False,
        )
        order_ids = _labels(self.order_ids, "score order_ids", unique=True)
        plans = tuple(self.plans)
        if not plans or any(not isinstance(plan, InjectionPlan) for plan in plans):
            raise SelectionDataError("score plans must contain InjectionPlan values")
        if len({plan.injection_id for plan in plans}) != len(plans):
            raise SelectionDataError("score plans must have unique injection IDs")
        pattern_ids = tuple(_velocity_pattern_identity(plan) for plan in plans)
        if len(set(pattern_ids)) != len(pattern_ids):
            raise SelectionDataError("score plans contain duplicate physical velocity patterns")
        if any(plan.epoch_ids != epoch_ids for plan in plans):
            raise SelectionDataError("score plan epoch identities are inconsistent")
        if self.plan_id != _plan_identity(epoch_ids, plans):
            raise SelectionDataError("plan_id does not bind the score velocity bank")
        if not isinstance(self.policy, AttritionPolicy):
            raise TypeError("score policy must be an AttritionPolicy")
        for name in (
            "all_planned_responses_present",
            "attrition_gate_passed",
            "fit_ready",
        ):
            _native_boolean(getattr(self, name), name)
        records = tuple(self.epoch_records)
        expected_count = len(plans) * len(epoch_ids)
        if len(records) != expected_count or any(
            not isinstance(record, EpochInjectionAudit) for record in records
        ):
            raise SelectionDataError("score epoch audit is incomplete or invalid")
        for plan_index, plan in enumerate(plans):
            for epoch_index, epoch_id in enumerate(epoch_ids):
                record = records[plan_index * len(epoch_ids) + epoch_index]
                if (
                    record.injection_id != plan.injection_id
                    or record.epoch_id != epoch_id
                    or record.cluster_id != cluster_ids[epoch_index]
                    or record.injected_velocity != float(plan.velocities[epoch_index])
                ):
                    raise SelectionDataError("score epoch audit identity/order is inconsistent")
                if (
                    len(record.order_records) != len(order_ids)
                    or tuple(order.order_id for order in record.order_records) != order_ids
                ):
                    raise SelectionDataError("score order audit identity/order is inconsistent")
                _validate_epoch_audit(record, plan, epoch_index, order_ids, self.policy)

        all_present = all(record.response_present for record in records)
        attrition_passed = all_present and all(
            record.reference_order_count >= self.policy.minimum_reference_orders
            and record.common_order_count >= self.policy.minimum_common_orders
            and record.lost_order_count == 0
            and not record.attrition_limit_exceeded
            for record in records
        )
        fit_ready = all_present and all(record.accepted_for_fit for record in records)
        failures = tuple(
            f"{record.injection_id}/{record.epoch_id}: {reason}"
            for record in records
            for reason in record.failure_reasons
        )
        supplied_failures = _labels(
            self.failure_reasons,
            "score failure_reasons",
            unique=False,
            allow_empty=True,
        )
        if self.all_planned_responses_present != all_present:
            raise SelectionDataError("all_planned_responses_present is inconsistent with audits")
        if self.attrition_gate_passed != attrition_passed:
            raise SelectionDataError("attrition_gate_passed is inconsistent with audits")
        if self.fit_ready != fit_ready:
            raise SelectionDataError("fit_ready is inconsistent with audits")
        if supplied_failures != failures:
            raise SelectionDataError("score failure_reasons are inconsistent with audits")
        expected_reference_id = _reference_identity_from_audits(
            epoch_ids,
            cluster_ids,
            order_ids,
            plans,
            records,
        )
        if reference_evidence_id != expected_reference_id:
            raise SelectionDataError("reference_evidence_id is inconsistent with audits")
        expected_score_id = _score_evidence_identity(
            plan_id=plan_id,
            reference_evidence_id=reference_evidence_id,
            epoch_ids=epoch_ids,
            cluster_ids=cluster_ids,
            order_ids=order_ids,
            plans=plans,
            policy=self.policy,
            records=records,
            all_present=all_present,
            attrition_passed=attrition_passed,
            fit_ready=fit_ready,
            failures=failures,
        )
        if score_id != expected_score_id:
            raise SelectionDataError("score_id is inconsistent with canonical score evidence")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "reference_evidence_id", reference_evidence_id)
        object.__setattr__(self, "score_id", score_id)
        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "cluster_ids", cluster_ids)
        object.__setattr__(self, "order_ids", order_ids)
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "epoch_records", records)
        object.__setattr__(self, "all_planned_responses_present", all_present)
        object.__setattr__(self, "attrition_gate_passed", attrition_passed)
        object.__setattr__(self, "fit_ready", fit_ready)
        object.__setattr__(self, "failure_reasons", failures)

    @property
    def order_records(self) -> tuple[OrderResponseAudit, ...]:
        """Flatten every per-injection/epoch/order audit record in planned order."""

        return tuple(
            record for epoch_record in self.epoch_records for record in epoch_record.order_records
        )


def _validate_epoch_audit(
    record: EpochInjectionAudit,
    plan: InjectionPlan,
    epoch_index: int,
    order_ids: tuple[str, ...],
    policy: AttritionPolicy,
) -> None:
    for name in (
        "response_present",
        "attrition_limit_exceeded",
        "accepted_for_fit",
    ):
        if type(getattr(record, name)) is not bool:
            raise TypeError(f"epoch audit {name} must be a native boolean")
    for name in (
        "reference_order_count",
        "common_order_count",
        "lost_order_count",
    ):
        value = getattr(record, name)
        if type(value) is not int or value < 0:
            raise TypeError(f"epoch audit {name} must be a non-negative native integer")
    order_records = tuple(record.order_records)
    for order_index, order in enumerate(order_records):
        if not isinstance(order, OrderResponseAudit):
            raise TypeError("epoch audit must contain OrderResponseAudit values")
        for name in (
            "reference_valid",
            "injected_valid",
            "common_valid",
            "injection_only_loss",
        ):
            if type(getattr(order, name)) is not bool:
                raise TypeError(f"order audit {name} must be a native boolean")
        if (
            order.injection_id != plan.injection_id
            or order.epoch_id != plan.epoch_ids[epoch_index]
            or order.order_id != order_ids[order_index]
            or order.injected_velocity != float(plan.velocities[epoch_index])
        ):
            raise SelectionDataError("order audit identity is inconsistent")
        common = bool(order.reference_valid and order.injected_valid)
        loss = bool(order.reference_valid and not order.injected_valid)
        if order.reference_valid:
            if (
                order.reference_rv is None
                or order.reference_uncertainty is None
                or not np.isfinite(order.reference_rv)
                or not np.isfinite(order.reference_uncertainty)
                or order.reference_uncertainty <= 0.0
            ):
                raise SelectionDataError("reference-valid order audit evidence is invalid")
        elif order.reference_rv is not None or order.reference_uncertainty is not None:
            raise SelectionDataError("reference-excluded order audit carries reference values")
        if order.injected_valid:
            if (
                order.injected_rv is None
                or order.injected_uncertainty is None
                or not np.isfinite(order.injected_rv)
                or not np.isfinite(order.injected_uncertainty)
                or order.injected_uncertainty <= 0.0
            ):
                raise SelectionDataError("injected-valid order audit evidence is invalid")
        elif order.injected_rv is not None or order.injected_uncertainty is not None:
            raise SelectionDataError("injected-excluded order audit carries injected values")
        expected_status: OrderStatus
        if not record.response_present:
            expected_status = "missing_response"
        elif common:
            expected_status = "common"
        elif loss:
            expected_status = "injection_lost"
        else:
            expected_status = "reference_excluded"
        if (
            order.common_valid != common
            or order.injection_only_loss != loss
            or order.status != expected_status
        ):
            raise SelectionDataError("order audit mask disposition is inconsistent")
        paired = (order.response, order.response_uncertainty)
        if common and record.response_present:
            if any(value is None or not np.isfinite(value) for value in paired):
                raise SelectionDataError("common order audit lacks a finite paired response")
            if order.response_uncertainty is not None and order.response_uncertainty <= 0.0:
                raise SelectionDataError("common order audit uncertainty must be positive")
            expected_response = float(order.injected_rv - order.reference_rv)
            if order.response != expected_response:
                raise SelectionDataError(
                    "paired response is inconsistent with injected minus reference RV"
                )
        elif paired != (None, None):
            raise SelectionDataError("non-common order audit cannot carry a paired response")

    common_records = tuple(order for order in order_records if order.common_valid)
    lost_records = tuple(order for order in order_records if order.injection_only_loss)
    reference_count = int(sum(order.reference_valid for order in order_records))
    common_count = len(common_records)
    lost_count = len(lost_records)
    lost_fraction = lost_count / reference_count if reference_count else 0.0
    if (
        record.reference_order_count != reference_count
        or record.common_order_count != common_count
        or record.lost_order_count != lost_count
        or record.lost_fraction != lost_fraction
        or record.common_order_ids != tuple(order.order_id for order in common_records)
        or record.lost_order_ids != tuple(order.order_id for order in lost_records)
    ):
        raise SelectionDataError("epoch audit counts or order identities are inconsistent")

    if common_records:
        expected_mean = float(
            np.mean([order.response for order in common_records], dtype=np.float64)
        )
        expected_uncertainty = float(
            np.mean(
                [order.response_uncertainty for order in common_records],
                dtype=np.float64,
            )
        )
    else:
        expected_mean = None
        expected_uncertainty = None
    if (
        record.mean_response != expected_mean
        or record.mean_response_uncertainty != expected_uncertainty
    ):
        raise SelectionDataError("epoch audit mean response is inconsistent")

    attrition_exceeded = lost_count > 0
    reasons: list[str] = []
    if not record.response_present:
        reasons.append("planned injection response is missing")
    if reference_count < policy.minimum_reference_orders:
        reasons.append("reference order count is below the frozen minimum")
    if common_count < policy.minimum_common_orders:
        reasons.append("common order count is below the frozen minimum")
    if attrition_exceeded:
        reasons.append("injection-only attrition exceeds the frozen zero-loss limit")
    accepted = (
        record.response_present
        and reference_count >= policy.minimum_reference_orders
        and common_count >= policy.minimum_common_orders
        and not attrition_exceeded
        and expected_mean is not None
    )
    if (
        record.attrition_limit_exceeded != attrition_exceeded
        or record.accepted_for_fit != accepted
        or record.failure_reasons != tuple(reasons)
    ):
        raise SelectionDataError("epoch audit decision fields are inconsistent")


def _present_order_record(
    reference: ReferenceResponse,
    injected: InjectedResponse,
    plan: InjectionPlan,
    epoch_index: int,
    order_index: int,
) -> OrderResponseAudit:
    reference_valid = bool(reference.valid_mask[epoch_index, order_index])
    injected_valid = bool(injected.valid_mask[epoch_index, order_index])
    common = reference_valid and injected_valid
    loss = reference_valid and not injected_valid
    supplied_response_uncertainty = injected.response_uncertainty[
        epoch_index,
        order_index,
    ]
    if common:
        reference_rv = float(reference.rv[epoch_index, order_index])
        reference_uncertainty = float(reference.uncertainty[epoch_index, order_index])
        injected_rv = float(injected.rv[epoch_index, order_index])
        injected_uncertainty = float(injected.uncertainty[epoch_index, order_index])
        if not np.isfinite(supplied_response_uncertainty) or supplied_response_uncertainty <= 0.0:
            raise SelectionDataError(
                "every common cell requires a positive finite paired response uncertainty"
            )
        try:
            with np.errstate(over="raise", invalid="raise"):
                response = float(injected_rv - reference_rv)
        except FloatingPointError as exc:
            raise SelectionDataError("a common-order response became non-finite") from exc
        response_uncertainty = float(supplied_response_uncertainty)
        if not np.isfinite(response):
            raise SelectionDataError("a common-order response became non-finite")
        status: OrderStatus = "common"
    else:
        if not np.isnan(supplied_response_uncertainty):
            raise SelectionDataError("non-common cells require NaN paired response uncertainty")
        reference_rv = float(reference.rv[epoch_index, order_index]) if reference_valid else None
        reference_uncertainty = (
            float(reference.uncertainty[epoch_index, order_index]) if reference_valid else None
        )
        injected_rv = float(injected.rv[epoch_index, order_index]) if injected_valid else None
        injected_uncertainty = (
            float(injected.uncertainty[epoch_index, order_index]) if injected_valid else None
        )
        response = None
        response_uncertainty = None
        status = "injection_lost" if loss else "reference_excluded"
    return OrderResponseAudit(
        injection_id=plan.injection_id,
        injected_velocity=float(plan.velocities[epoch_index]),
        epoch_id=reference.epoch_ids[epoch_index],
        order_id=reference.order_ids[order_index],
        reference_valid=reference_valid,
        injected_valid=injected_valid,
        common_valid=common,
        injection_only_loss=loss,
        status=status,
        reference_rv=reference_rv,
        reference_uncertainty=reference_uncertainty,
        injected_rv=injected_rv,
        injected_uncertainty=injected_uncertainty,
        response=response,
        response_uncertainty=response_uncertainty,
    )


def _missing_order_record(
    reference: ReferenceResponse,
    plan: InjectionPlan,
    epoch_index: int,
    order_index: int,
) -> OrderResponseAudit:
    reference_valid = bool(reference.valid_mask[epoch_index, order_index])
    return OrderResponseAudit(
        injection_id=plan.injection_id,
        injected_velocity=float(plan.velocities[epoch_index]),
        epoch_id=reference.epoch_ids[epoch_index],
        order_id=reference.order_ids[order_index],
        reference_valid=reference_valid,
        injected_valid=False,
        common_valid=False,
        injection_only_loss=reference_valid,
        status="missing_response",
        reference_rv=(float(reference.rv[epoch_index, order_index]) if reference_valid else None),
        reference_uncertainty=(
            float(reference.uncertainty[epoch_index, order_index]) if reference_valid else None
        ),
        injected_rv=None,
        injected_uncertainty=None,
        response=None,
        response_uncertainty=None,
    )


def _epoch_audit(
    reference: ReferenceResponse,
    plan: InjectionPlan,
    injected: InjectedResponse | None,
    epoch_index: int,
    policy: AttritionPolicy,
) -> EpochInjectionAudit:
    order_records = tuple(
        (
            _missing_order_record(reference, plan, epoch_index, order_index)
            if injected is None
            else _present_order_record(
                reference,
                injected,
                plan,
                epoch_index,
                order_index,
            )
        )
        for order_index in range(len(reference.order_ids))
    )
    common_records = tuple(record for record in order_records if record.common_valid)
    lost_records = tuple(record for record in order_records if record.injection_only_loss)
    reference_count = int(sum(record.reference_valid for record in order_records))
    common_count = len(common_records)
    lost_count = len(lost_records)
    lost_fraction = lost_count / reference_count if reference_count else 0.0

    if common_records:
        responses = np.array([record.response for record in common_records], dtype=np.float64)
        response_uncertainties = np.array(
            [record.response_uncertainty for record in common_records],
            dtype=np.float64,
        )
        mean_response = float(np.mean(responses))
        # For arbitrary within-epoch covariance, SD(mean) <= mean(component SDs).
        # This conservative bound does not assume independent order errors.
        mean_uncertainty = float(np.mean(response_uncertainties))
        if (
            not np.isfinite(mean_response)
            or not np.isfinite(mean_uncertainty)
            or mean_uncertainty <= 0.0
        ):
            raise SelectionDataError("an epoch common-order mean or uncertainty became invalid")
    else:
        mean_response = None
        mean_uncertainty = None

    attrition_exceeded = (
        lost_count > policy.maximum_lost_orders or lost_fraction > policy.maximum_lost_fraction
    )
    reasons: list[str] = []
    if injected is None:
        reasons.append("planned injection response is missing")
    if reference_count < policy.minimum_reference_orders:
        reasons.append("reference order count is below the frozen minimum")
    if common_count < policy.minimum_common_orders:
        reasons.append("common order count is below the frozen minimum")
    if attrition_exceeded:
        reasons.append("injection-only attrition exceeds the frozen zero-loss limit")

    hard_failure = injected is None or reference_count < policy.minimum_reference_orders
    hard_failure = hard_failure or common_count < policy.minimum_common_orders
    accepted = not hard_failure and not attrition_exceeded and mean_response is not None
    return EpochInjectionAudit(
        injection_id=plan.injection_id,
        injected_velocity=float(plan.velocities[epoch_index]),
        epoch_id=reference.epoch_ids[epoch_index],
        cluster_id=reference.cluster_ids[epoch_index],
        response_present=injected is not None,
        reference_order_count=reference_count,
        common_order_count=common_count,
        lost_order_count=lost_count,
        lost_fraction=lost_fraction,
        common_order_ids=tuple(record.order_id for record in common_records),
        lost_order_ids=tuple(record.order_id for record in lost_records),
        mean_response=mean_response,
        mean_response_uncertainty=mean_uncertainty,
        attrition_limit_exceeded=attrition_exceeded,
        accepted_for_fit=accepted,
        failure_reasons=tuple(reasons),
        order_records=order_records,
    )


def score_injection_responses(
    reference: ReferenceResponse,
    planned_injections: Sequence[InjectionPlan],
    injected_responses: Sequence[InjectedResponse],
    policy: AttritionPolicy,
) -> InjectionScore:
    """Score every planned injection/epoch on one immutable reference-defined order mask."""

    if not isinstance(reference, ReferenceResponse):
        raise TypeError("reference must be a ReferenceResponse")
    if not isinstance(policy, AttritionPolicy):
        raise TypeError("policy must be an AttritionPolicy")
    plans = tuple(planned_injections)
    if not plans or any(not isinstance(plan, InjectionPlan) for plan in plans):
        raise SelectionDataError("planned_injections must contain InjectionPlan values")
    plan_ids = tuple(plan.injection_id for plan in plans)
    if len(set(plan_ids)) != len(plan_ids):
        raise SelectionDataError("planned injection IDs must not contain duplicates")
    pattern_ids = tuple(_velocity_pattern_identity(plan) for plan in plans)
    if len(set(pattern_ids)) != len(pattern_ids):
        raise SelectionDataError("planned injections contain duplicate physical patterns")
    for plan in plans:
        if plan.epoch_ids != reference.epoch_ids:
            raise SelectionDataError(
                f"epoch identity/order mismatch for injection plan {plan.injection_id!r}"
            )

    responses = tuple(injected_responses)
    if any(not isinstance(response, InjectedResponse) for response in responses):
        raise SelectionDataError("injected_responses must contain InjectedResponse values")
    response_ids = tuple(response.injection_id for response in responses)
    if len(set(response_ids)) != len(response_ids):
        raise SelectionDataError("injected response IDs must not contain duplicates")
    extras = tuple(response_id for response_id in response_ids if response_id not in plan_ids)
    if extras:
        raise SelectionDataError(f"responses were supplied for unplanned injections: {extras}")
    expected_present_order = tuple(plan_id for plan_id in plan_ids if plan_id in response_ids)
    if response_ids != expected_present_order:
        raise SelectionDataError("injected responses do not follow frozen plan order")

    response_by_id = {response.injection_id: response for response in responses}
    for response in responses:
        if response.epoch_ids != reference.epoch_ids:
            raise SelectionDataError(
                f"epoch identity/order mismatch for injection {response.injection_id!r}"
            )
        if response.order_ids != reference.order_ids:
            raise SelectionDataError(
                f"order identity/order mismatch for injection {response.injection_id!r}"
            )

    epoch_records = tuple(
        _epoch_audit(
            reference,
            plan,
            response_by_id.get(plan.injection_id),
            epoch_index,
            policy,
        )
        for plan in plans
        for epoch_index in range(len(reference.epoch_ids))
    )
    all_present = len(responses) == len(plans)
    fit_ready = all_present and all(record.accepted_for_fit for record in epoch_records)
    attrition_passed = all(not record.attrition_limit_exceeded for record in epoch_records)
    attrition_passed = attrition_passed and all(
        record.reference_order_count >= policy.minimum_reference_orders
        and record.common_order_count >= policy.minimum_common_orders
        for record in epoch_records
    )
    attrition_passed = attrition_passed and all_present
    failures = tuple(
        f"{record.injection_id}/{record.epoch_id}: {reason}"
        for record in epoch_records
        for reason in record.failure_reasons
    )

    plan_id = _plan_identity(reference.epoch_ids, plans)
    reference_evidence_id = _reference_identity(reference)
    score_id = _score_evidence_identity(
        plan_id=plan_id,
        reference_evidence_id=reference_evidence_id,
        epoch_ids=reference.epoch_ids,
        cluster_ids=reference.cluster_ids,
        order_ids=reference.order_ids,
        plans=plans,
        policy=policy,
        records=epoch_records,
        all_present=all_present,
        attrition_passed=attrition_passed,
        fit_ready=fit_ready,
        failures=failures,
    )
    return InjectionScore(
        plan_id=plan_id,
        reference_evidence_id=reference_evidence_id,
        score_id=score_id,
        epoch_ids=reference.epoch_ids,
        cluster_ids=reference.cluster_ids,
        order_ids=reference.order_ids,
        plans=plans,
        policy=policy,
        epoch_records=epoch_records,
        all_planned_responses_present=all_present,
        attrition_gate_passed=attrition_passed,
        fit_ready=fit_ready,
        failure_reasons=failures,
    )


@dataclass(frozen=True, slots=True)
class BootstrapFailure:
    """One failed or deliberately unrun planned bootstrap repetition."""

    repetition: int
    exception_type: str
    message: str

    def __post_init__(self) -> None:
        repetition = _nonnegative_int(self.repetition, "bootstrap failure repetition")
        _native_string(self.exception_type, "bootstrap failure exception_type")
        _native_string(self.message, "bootstrap failure message")
        object.__setattr__(self, "repetition", repetition)


@dataclass(frozen=True, slots=True)
class RecoverySlopeEstimate:
    """Validated intercept/slope fit and complete cluster-bootstrap accounting."""

    plan_id: str
    score_id: str
    seed: int
    requested_repetitions: int
    minimum_independent_clusters: int
    actual_independent_clusters: int
    confidence_level: float
    interval_method: str
    slope: float | None
    intercept: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    bootstrap_slopes: FloatArray
    cluster_draws: tuple[tuple[str, ...], ...]
    epoch_index_draws: tuple[tuple[int, ...], ...]
    failures: tuple[BootstrapFailure, ...]
    fit_failure_reason: str | None

    def __post_init__(self) -> None:
        plan_id = _digest_id(self.plan_id, "plan_id")
        score_id = _digest_id(self.score_id, "score_id")
        seed = _nonnegative_int(self.seed, "seed")
        requested = _positive_int(self.requested_repetitions, "requested_repetitions")
        minimum_clusters = _positive_int(
            self.minimum_independent_clusters,
            "minimum_independent_clusters",
        )
        if minimum_clusters < 2:
            raise ValueError("minimum_independent_clusters must be at least two")
        actual_clusters = _positive_int(
            self.actual_independent_clusters,
            "actual_independent_clusters",
        )
        confidence = _finite_float(self.confidence_level, "confidence_level")
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence_level must lie strictly between zero and one")
        interval_method = _native_string(self.interval_method, "interval_method")
        fit_failure_reason = (
            None
            if self.fit_failure_reason is None
            else _native_string(self.fit_failure_reason, "fit_failure_reason")
        )
        if self.fit_failure_reason is None and actual_clusters < minimum_clusters:
            raise SelectionDataError(
                "a complete point fit cannot violate the independent-cluster minimum"
            )

        statistics = _float_vector(
            self.bootstrap_slopes,
            "bootstrap_slopes",
            allow_nan=True,
        )
        if statistics.size != requested:
            raise SelectionDataError("bootstrap_slopes length must equal requested_repetitions")
        cluster_draws = tuple(tuple(draw) for draw in self.cluster_draws)
        epoch_draws = tuple(tuple(draw) for draw in self.epoch_index_draws)
        if len(cluster_draws) != requested or len(epoch_draws) != requested:
            raise SelectionDataError("every bootstrap repetition requires a recorded draw")
        for draw in cluster_draws:
            if len(draw) != actual_clusters or any(
                type(label) is not str or not label for label in draw
            ):
                raise SelectionDataError("cluster draws have invalid identities or width")
        for draw in epoch_draws:
            if not draw or any(
                isinstance(index, (bool, np.bool_))
                or not isinstance(index, Integral)
                or int(index) < 0
                for index in draw
            ):
                raise SelectionDataError("epoch-index draws must contain non-negative integers")

        failures = tuple(self.failures)
        if any(not isinstance(failure, BootstrapFailure) for failure in failures):
            raise TypeError("failures must contain BootstrapFailure values")
        failure_indices = tuple(failure.repetition for failure in failures)
        if len(set(failure_indices)) != len(failure_indices):
            raise SelectionDataError("bootstrap failure repetitions must be unique")
        if any(index >= requested for index in failure_indices):
            raise SelectionDataError("bootstrap failure repetition is out of range")
        if failure_indices != tuple(sorted(failure_indices)):
            raise SelectionDataError("bootstrap failures must follow repetition order")
        failed = set(failure_indices)

        if fit_failure_reason is not None:
            if self.slope is not None or self.intercept is not None:
                raise SelectionDataError("a failed point fit cannot carry coefficients")
            if self.confidence_lower is not None or self.confidence_upper is not None:
                raise SelectionDataError("a failed point fit cannot carry a confidence interval")
            if failed != set(range(requested)) or not np.all(np.isnan(statistics)):
                raise SelectionDataError(
                    "a failed point fit must account for every unrun bootstrap repetition"
                )
        else:
            slope = _finite_float(self.slope, "slope")
            intercept = _finite_float(self.intercept, "intercept")
            object.__setattr__(self, "slope", slope)
            object.__setattr__(self, "intercept", intercept)
            finite_indices = {index for index, value in enumerate(statistics) if np.isfinite(value)}
            if finite_indices != set(range(requested)) - failed:
                raise SelectionDataError(
                    "bootstrap finite/NaN statistics do not match recorded failures"
                )
            if failures:
                if self.confidence_lower is not None or self.confidence_upper is not None:
                    raise SelectionDataError(
                        "an incomplete bootstrap cannot carry a confidence interval"
                    )
            else:
                lower = _finite_float(self.confidence_lower, "confidence_lower")
                upper = _finite_float(self.confidence_upper, "confidence_upper")
                if lower > upper:
                    raise SelectionDataError("confidence interval bounds are reversed")
                object.__setattr__(self, "confidence_lower", lower)
                object.__setattr__(self, "confidence_upper", upper)

        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "score_id", score_id)
        object.__setattr__(self, "requested_repetitions", requested)
        object.__setattr__(self, "minimum_independent_clusters", minimum_clusters)
        object.__setattr__(self, "actual_independent_clusters", actual_clusters)
        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "interval_method", interval_method)
        object.__setattr__(self, "bootstrap_slopes", statistics)
        object.__setattr__(self, "cluster_draws", cluster_draws)
        object.__setattr__(self, "epoch_index_draws", epoch_draws)
        object.__setattr__(self, "failures", failures)
        object.__setattr__(self, "fit_failure_reason", fit_failure_reason)

    @property
    def complete(self) -> bool:
        """Whether the point fit and every requested bootstrap repetition succeeded."""

        return (
            self.fit_failure_reason is None
            and not self.failures
            and self.confidence_lower is not None
            and self.confidence_upper is not None
        )


def _fit_line(
    x: FloatArray,
    y: FloatArray,
    uncertainty: FloatArray,
) -> tuple[float, float]:
    if (
        x.ndim != 1
        or y.ndim != 1
        or uncertainty.ndim != 1
        or x.size != y.size
        or x.size != uncertainty.size
        or x.size < 2
    ):
        raise SelectionDataError(
            "slope fit requires paired one-dimensional observations and uncertainties"
        )
    if (
        not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
        or not np.all(np.isfinite(uncertainty))
        or np.any(uncertainty <= 0.0)
    ):
        raise SelectionDataError(
            "slope fit observations require finite values and positive uncertainties"
        )
    design = np.column_stack((np.ones(x.size, dtype=np.float64), x))
    try:
        with np.errstate(divide="raise", invalid="raise", over="raise"):
            weighted_design = design / uncertainty[:, None]
            weighted_values = y / uncertainty
    except FloatingPointError as exc:
        raise SelectionDataError("slope weights produced non-finite values") from exc
    if not np.all(np.isfinite(weighted_design)) or not np.all(np.isfinite(weighted_values)):
        raise SelectionDataError("slope weights produced non-finite values")
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(
            weighted_design,
            weighted_values,
            rcond=None,
        )
    except np.linalg.LinAlgError as exc:
        raise SelectionDataError("slope fit linear algebra failed") from exc
    if int(rank) != 2:
        raise SelectionDataError("injected velocities do not identify an intercept and slope")
    intercept = float(coefficients[0])
    slope = float(coefficients[1])
    if not np.isfinite(intercept) or not np.isfinite(slope):
        raise SelectionDataError("slope fit produced a non-finite coefficient")
    return intercept, slope


def _cluster_draws(
    cluster_ids: tuple[str, ...],
    *,
    repetitions: int,
    seed: int,
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[int, ...], ...]]:
    unique_clusters = tuple(dict.fromkeys(cluster_ids))
    indices_by_cluster = {
        cluster: tuple(index for index, value in enumerate(cluster_ids) if value == cluster)
        for cluster in unique_clusters
    }
    rng = np.random.default_rng(seed)
    selections = rng.integers(
        0,
        len(unique_clusters),
        size=(repetitions, len(unique_clusters)),
    )
    cluster_draws: list[tuple[str, ...]] = []
    epoch_draws: list[tuple[int, ...]] = []
    for row in selections:
        selected_clusters = tuple(unique_clusters[int(index)] for index in row)
        expanded_epochs = tuple(
            epoch_index
            for cluster in selected_clusters
            for epoch_index in indices_by_cluster[cluster]
        )
        cluster_draws.append(selected_clusters)
        epoch_draws.append(expanded_epochs)
    return tuple(cluster_draws), tuple(epoch_draws)


def _response_lookup(score: InjectionScore) -> dict[tuple[str, str], tuple[float, float]]:
    result: dict[tuple[str, str], tuple[float, float]] = {}
    for record in score.epoch_records:
        if (
            record.accepted_for_fit
            and record.mean_response is not None
            and record.mean_response_uncertainty is not None
        ):
            result[(record.injection_id, record.epoch_id)] = (
                record.mean_response,
                record.mean_response_uncertainty,
            )
    return result


def estimate_recovery_slope(
    score: InjectionScore,
    *,
    seed: int,
    repetitions: int,
    confidence_level: float,
    minimum_independent_clusters: int,
) -> RecoverySlopeEstimate:
    """Fit response on injected velocity and run a complete cluster bootstrap.

    Each bootstrap draw resamples independent ``cluster_ids`` and expands every selected
    cluster back to all of its epochs.  Every injection, and therefore every audited common
    order contributing to that epoch response, is retained.  The point fit and bootstrap are
    inverse-variance weighted fits with an intercept, using caller-supplied paired-response
    uncertainties and the correlation-agnostic epoch-mean bound.  The caller must explicitly
    freeze a minimum independent-cluster count of at least two.  This estimator, its weight
    interpretation, and its percentile coverage must be validated on controls before use.
    """

    if not isinstance(score, InjectionScore):
        raise TypeError("score must be an InjectionScore")
    master_seed = _nonnegative_int(seed, "seed")
    requested = _positive_int(repetitions, "repetitions")
    confidence = _finite_float(confidence_level, "confidence_level")
    if confidence <= 0.0 or confidence >= 1.0:
        raise ValueError("confidence_level must lie strictly between zero and one")
    minimum_clusters = _positive_int(
        minimum_independent_clusters,
        "minimum_independent_clusters",
    )
    if minimum_clusters < 2:
        raise ValueError("minimum_independent_clusters must be at least two")
    actual_clusters = len(set(score.cluster_ids))

    cluster_draws, epoch_draws = _cluster_draws(
        score.cluster_ids,
        repetitions=requested,
        seed=master_seed,
    )
    statistics = np.full(requested, np.nan, dtype=np.float64)
    failures: list[BootstrapFailure] = []
    lookup = _response_lookup(score)

    def failed_estimate(reason: str, exception_type: str) -> RecoverySlopeEstimate:
        failures.extend(
            BootstrapFailure(index, exception_type, reason) for index in range(requested)
        )
        statistics.setflags(write=False)
        return RecoverySlopeEstimate(
            plan_id=score.plan_id,
            score_id=score.score_id,
            seed=master_seed,
            requested_repetitions=requested,
            minimum_independent_clusters=minimum_clusters,
            actual_independent_clusters=actual_clusters,
            confidence_level=confidence,
            interval_method="percentile_epoch_cluster_bootstrap",
            slope=None,
            intercept=None,
            confidence_lower=None,
            confidence_upper=None,
            bootstrap_slopes=statistics,
            cluster_draws=cluster_draws,
            epoch_index_draws=epoch_draws,
            failures=tuple(failures),
            fit_failure_reason=reason,
        )

    if actual_clusters < minimum_clusters:
        return failed_estimate(
            "actual independent-cluster count is below the caller-supplied minimum",
            "InsufficientIndependentClusters",
        )
    if not score.fit_ready:
        return failed_estimate(
            "injection score is incomplete; subset fitting is forbidden",
            "InputIncomplete",
        )

    all_epoch_indices = tuple(range(len(score.epoch_ids)))

    def observations(
        epoch_indices: tuple[int, ...],
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        x_values: list[float] = []
        y_values: list[float] = []
        uncertainties: list[float] = []
        for epoch_index in epoch_indices:
            epoch_id = score.epoch_ids[epoch_index]
            for plan in score.plans:
                response, response_uncertainty = lookup[(plan.injection_id, epoch_id)]
                x_values.append(float(plan.velocities[epoch_index]))
                y_values.append(response)
                uncertainties.append(response_uncertainty)
        return (
            np.asarray(x_values, dtype=np.float64),
            np.asarray(y_values, dtype=np.float64),
            np.asarray(uncertainties, dtype=np.float64),
        )

    point_x, point_y, point_uncertainty = observations(all_epoch_indices)
    try:
        intercept, slope = _fit_line(point_x, point_y, point_uncertainty)
    except SelectionDataError as exc:
        return failed_estimate(str(exc), "PointFitFailed")

    for repetition, epoch_indices in enumerate(epoch_draws):
        bootstrap_x, bootstrap_y, bootstrap_uncertainty = observations(epoch_indices)
        try:
            _, bootstrap_slope = _fit_line(
                bootstrap_x,
                bootstrap_y,
                bootstrap_uncertainty,
            )
        except Exception as exc:  # noqa: BLE001 - every planned bootstrap failure is audited.
            failures.append(
                BootstrapFailure(
                    repetition=repetition,
                    exception_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        statistics[repetition] = bootstrap_slope

    statistics.setflags(write=False)
    if failures:
        lower = upper = None
    else:
        alpha = (1.0 - confidence) / 2.0
        lower, upper = (
            float(value) for value in np.quantile(statistics, [alpha, 1.0 - alpha], method="linear")
        )
    return RecoverySlopeEstimate(
        plan_id=score.plan_id,
        score_id=score.score_id,
        seed=master_seed,
        requested_repetitions=requested,
        minimum_independent_clusters=minimum_clusters,
        actual_independent_clusters=actual_clusters,
        confidence_level=confidence,
        interval_method="percentile_epoch_cluster_bootstrap",
        slope=slope,
        intercept=intercept,
        confidence_lower=lower,
        confidence_upper=upper,
        bootstrap_slopes=statistics,
        cluster_draws=cluster_draws,
        epoch_index_draws=epoch_draws,
        failures=tuple(failures),
        fit_failure_reason=None,
    )


def _bootstrap_value_token(value: float) -> str:
    return "nan" if np.isnan(value) else _float_token(value)


def _estimate_evidence_identity(estimate: RecoverySlopeEstimate) -> str:
    return _canonical_sha256(
        {
            "actual_independent_clusters": estimate.actual_independent_clusters,
            "bootstrap_slopes": [
                _bootstrap_value_token(float(value)) for value in estimate.bootstrap_slopes
            ],
            "cluster_draws": estimate.cluster_draws,
            "confidence_level": _float_token(estimate.confidence_level),
            "confidence_lower": _optional_float_token(estimate.confidence_lower),
            "confidence_upper": _optional_float_token(estimate.confidence_upper),
            "epoch_index_draws": estimate.epoch_index_draws,
            "failures": [
                {
                    "exception_type": failure.exception_type,
                    "message": failure.message,
                    "repetition": failure.repetition,
                }
                for failure in estimate.failures
            ],
            "fit_failure_reason": estimate.fit_failure_reason,
            "intercept": _optional_float_token(estimate.intercept),
            "interval_method": estimate.interval_method,
            "minimum_independent_clusters": estimate.minimum_independent_clusters,
            "plan_id": estimate.plan_id,
            "requested_repetitions": estimate.requested_repetitions,
            "score_id": estimate.score_id,
            "seed": estimate.seed,
            "slope": _optional_float_token(estimate.slope),
        }
    )


def _validate_estimate_against_score(
    score: InjectionScore,
    estimate: RecoverySlopeEstimate,
) -> None:
    if estimate.score_id != score.score_id or estimate.plan_id != score.plan_id:
        raise SelectionDataError("slope estimate does not belong to the supplied score")
    expected = estimate_recovery_slope(
        score,
        seed=estimate.seed,
        repetitions=estimate.requested_repetitions,
        confidence_level=estimate.confidence_level,
        minimum_independent_clusters=estimate.minimum_independent_clusters,
    )
    if _estimate_evidence_identity(estimate) != _estimate_evidence_identity(expected):
        raise SelectionDataError(
            "slope estimate does not match deterministic recomputation from its score"
        )


@dataclass(frozen=True, slots=True)
class EquivalenceInterval:
    """Unity-centered closed equivalence region ``[1 - delta, 1 + delta]``."""

    delta: float

    def __post_init__(self) -> None:
        delta = _finite_float(self.delta, "equivalence delta")
        if delta <= 0.0:
            raise ValueError("equivalence delta must be positive")
        object.__setattr__(self, "delta", delta)

    @property
    def lower(self) -> float:
        """Lower unity-centered equivalence bound."""

        return 1.0 - self.delta

    @property
    def upper(self) -> float:
        """Upper unity-centered equivalence bound."""

        return 1.0 + self.delta

    @classmethod
    def from_delta(cls, delta: float) -> EquivalenceInterval:
        """Construct the only supported, unity-centered interval form."""

        return cls(delta=delta)


@dataclass(frozen=True, slots=True)
class ArmGates:
    """External provenance, completeness, convergence, and fit-quality gates."""

    provenance_valid: bool
    reference_run_complete: bool
    injection_runs_complete: bool
    template_convergence_complete: bool
    fit_quality_passed: bool
    per_order_stability_passed: bool
    catastrophic_fit_checks_passed: bool

    def __post_init__(self) -> None:
        for name in (
            "provenance_valid",
            "reference_run_complete",
            "injection_runs_complete",
            "template_convergence_complete",
            "fit_quality_passed",
            "per_order_stability_passed",
            "catastrophic_fit_checks_passed",
        ):
            value = getattr(self, name)
            if not isinstance(value, (bool, np.bool_)):
                raise TypeError(f"{name} must be boolean")
            object.__setattr__(self, name, bool(value))

    @property
    def all_passed(self) -> bool:
        return all(
            (
                self.provenance_valid,
                self.reference_run_complete,
                self.injection_runs_complete,
                self.template_convergence_complete,
                self.fit_quality_passed,
                self.per_order_stability_passed,
                self.catastrophic_fit_checks_passed,
            )
        )


@dataclass(frozen=True, slots=True)
class ArmAssessment:
    """One arm's immutable evidence; all decision fields are recomputed properties."""

    arm_id: str
    configuration_index: int
    configuration_identity: str
    assessment_stage: AssessmentStage
    score: InjectionScore
    estimate: RecoverySlopeEstimate
    equivalence_interval: EquivalenceInterval
    gates: ArmGates

    def __post_init__(self) -> None:
        arm_id = _native_string(self.arm_id, "arm_id")
        index = _nonnegative_int(self.configuration_index, "configuration_index")
        configuration_identity = _digest_id(
            self.configuration_identity,
            "configuration_identity",
        )
        assessment_stage = _native_string(self.assessment_stage, "assessment_stage")
        if assessment_stage not in ("selection", "hidden_validation"):
            raise ValueError("assessment_stage must be 'selection' or 'hidden_validation'")
        if not isinstance(self.score, InjectionScore):
            raise TypeError("score must be an InjectionScore")
        if not isinstance(self.estimate, RecoverySlopeEstimate):
            raise TypeError("estimate must be a RecoverySlopeEstimate")
        if not isinstance(self.equivalence_interval, EquivalenceInterval):
            raise TypeError("equivalence_interval must be an EquivalenceInterval")
        if not isinstance(self.gates, ArmGates):
            raise TypeError("gates must be ArmGates")
        _validate_estimate_against_score(self.score, self.estimate)
        object.__setattr__(self, "arm_id", arm_id)
        object.__setattr__(self, "configuration_index", index)
        object.__setattr__(self, "configuration_identity", configuration_identity)
        object.__setattr__(self, "assessment_stage", assessment_stage)

    @property
    def plan_id(self) -> str:
        return self.score.plan_id

    @property
    def score_id(self) -> str:
        return self.score.score_id

    @property
    def confidence_lower(self) -> float | None:
        return self.estimate.confidence_lower

    @property
    def confidence_upper(self) -> float | None:
        return self.estimate.confidence_upper

    @property
    def confidence_interval_inside_equivalence(self) -> bool:
        lower = self.confidence_lower
        upper = self.confidence_upper
        return (
            self.estimate.complete
            and lower is not None
            and upper is not None
            and lower >= self.equivalence_interval.lower
            and upper <= self.equivalence_interval.upper
        )

    @property
    def worst_confidence_bound_error(self) -> float | None:
        lower = self.confidence_lower
        upper = self.confidence_upper
        if lower is None or upper is None:
            return None
        return max(abs(lower - 1.0), abs(upper - 1.0))

    @property
    def failure_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for name in (
            "provenance_valid",
            "reference_run_complete",
            "injection_runs_complete",
            "template_convergence_complete",
            "fit_quality_passed",
            "per_order_stability_passed",
            "catastrophic_fit_checks_passed",
        ):
            if not getattr(self.gates, name):
                reasons.append(f"external gate failed: {name}")
        if not self.score.all_planned_responses_present:
            reasons.append("not every planned injection response is present")
        if not self.score.fit_ready:
            reasons.append("injection score is not complete enough to fit")
        if not self.score.attrition_gate_passed:
            reasons.append("attrition gate failed")
        if not self.estimate.complete:
            reasons.append("slope/bootstrap estimate is incomplete")
        if self.estimate.complete and not self.confidence_interval_inside_equivalence:
            reasons.append("confidence interval is not wholly inside equivalence bounds")
        return tuple(reasons)

    @property
    def eligible(self) -> bool:
        return not self.failure_reasons


def assess_arm(
    arm_id: str,
    configuration_index: int,
    configuration_identity: str,
    score: InjectionScore,
    estimate: RecoverySlopeEstimate,
    equivalence_interval: EquivalenceInterval,
    gates: ArmGates,
    *,
    assessment_stage: AssessmentStage,
) -> ArmAssessment:
    """Bind one score/estimate pair to a declared selection or hidden-validation stage."""

    return ArmAssessment(
        arm_id=arm_id,
        configuration_index=configuration_index,
        configuration_identity=configuration_identity,
        assessment_stage=assessment_stage,
        score=score,
        estimate=estimate,
        equivalence_interval=equivalence_interval,
        gates=gates,
    )


@dataclass(frozen=True, slots=True)
class ArmRosterEntry:
    """One precommitted arm identity in the exact expected selection roster."""

    arm_id: str
    configuration_index: int
    configuration_identity: str

    def __post_init__(self) -> None:
        arm_id = _native_string(self.arm_id, "roster arm_id")
        object.__setattr__(self, "arm_id", arm_id)
        object.__setattr__(
            self,
            "configuration_index",
            _nonnegative_int(self.configuration_index, "roster configuration_index"),
        )
        object.__setattr__(
            self,
            "configuration_identity",
            _digest_id(self.configuration_identity, "roster configuration_identity"),
        )

    @property
    def identity(self) -> tuple[str, int, str]:
        return self.arm_id, self.configuration_index, self.configuration_identity


@dataclass(frozen=True, slots=True)
class SelectionContract:
    """Precommitted arm roster, hidden physical-plan identity, and hidden seed.

    The digest commitment is carried by the winner selection before hidden evidence is
    supplied.  An external signed/timestamped manifest is still required to demonstrate that
    this object itself predates target access.
    """

    expected_arms: tuple[ArmRosterEntry, ...]
    expected_hidden_plan_id: str
    expected_hidden_bootstrap_seed: int

    def __post_init__(self) -> None:
        expected = tuple(self.expected_arms)
        if not expected or any(not isinstance(entry, ArmRosterEntry) for entry in expected):
            raise SelectionDataError("expected_arms must contain ArmRosterEntry values")
        identities = tuple(entry.identity for entry in expected)
        if len(set(identities)) != len(identities):
            raise SelectionDataError("expected arm roster contains duplicate entries")
        if len({entry.arm_id for entry in expected}) != len(expected):
            raise SelectionDataError("expected arm roster contains duplicate arm IDs")
        if len({entry.configuration_index for entry in expected}) != len(expected):
            raise SelectionDataError("expected arm roster contains duplicate configuration indices")
        if len({entry.configuration_identity for entry in expected}) != len(expected):
            raise SelectionDataError(
                "expected arm roster contains duplicate configuration identities"
            )
        object.__setattr__(self, "expected_arms", expected)
        object.__setattr__(
            self,
            "expected_hidden_plan_id",
            _digest_id(self.expected_hidden_plan_id, "expected_hidden_plan_id"),
        )
        object.__setattr__(
            self,
            "expected_hidden_bootstrap_seed",
            _nonnegative_int(
                self.expected_hidden_bootstrap_seed,
                "expected_hidden_bootstrap_seed",
            ),
        )


def _selection_contract_key(value: ArmAssessment) -> tuple[object, ...]:
    estimate = value.estimate
    return (
        value.plan_id,
        value.score.epoch_ids,
        value.score.cluster_ids,
        value.score.policy,
        value.equivalence_interval.delta,
        estimate.seed,
        estimate.requested_repetitions,
        estimate.confidence_level,
        estimate.minimum_independent_clusters,
        estimate.interval_method,
    )


def _validate_common_selection_contract(values: tuple[ArmAssessment, ...]) -> None:
    if not values:
        raise SelectionDataError("at least one selection assessment is required")
    if any(value.assessment_stage != "selection" for value in values):
        raise SelectionDataError("only selection-stage assessments may be ranked")
    expected = _selection_contract_key(values[0])
    if any(_selection_contract_key(value) != expected for value in values[1:]):
        raise SelectionDataError("all supplied arms must share one frozen selection contract")


def _assessment_evidence_identity(value: ArmAssessment) -> str:
    return _canonical_sha256(
        {
            "arm_id": value.arm_id,
            "assessment_stage": value.assessment_stage,
            "configuration_identity": value.configuration_identity,
            "configuration_index": value.configuration_index,
            "equivalence_delta": _float_token(value.equivalence_interval.delta),
            "estimate_evidence_id": _estimate_evidence_identity(value.estimate),
            "gates": {
                "catastrophic_fit_checks_passed": value.gates.catastrophic_fit_checks_passed,
                "fit_quality_passed": value.gates.fit_quality_passed,
                "injection_runs_complete": value.gates.injection_runs_complete,
                "per_order_stability_passed": value.gates.per_order_stability_passed,
                "provenance_valid": value.gates.provenance_valid,
                "reference_run_complete": value.gates.reference_run_complete,
                "template_convergence_complete": value.gates.template_convergence_complete,
            },
            "order_ids": value.score.order_ids,
            "reference_evidence_id": value.score.reference_evidence_id,
            "score_id": value.score_id,
        }
    )


def rank_eligible_arms(assessments: Sequence[ArmAssessment]) -> tuple[ArmAssessment, ...]:
    """Validate every supplied arm contract, then rank eligible arms deterministically."""

    values = tuple(assessments)
    if any(not isinstance(value, ArmAssessment) for value in values):
        raise TypeError("assessments must contain ArmAssessment values")
    _validate_common_selection_contract(values)
    arm_ids = tuple(value.arm_id for value in values)
    indices = tuple(value.configuration_index for value in values)
    identities = tuple(value.configuration_identity for value in values)
    if len(set(arm_ids)) != len(arm_ids):
        raise SelectionDataError("arm IDs must not contain duplicates")
    if len(set(indices)) != len(indices):
        raise SelectionDataError("configuration indices must not contain duplicates")
    if len(set(identities)) != len(identities):
        raise SelectionDataError("configuration identities must not contain duplicates")
    eligible = tuple(value for value in values if value.eligible)
    if any(value.worst_confidence_bound_error is None for value in eligible):
        raise SelectionDataError("an eligible arm lacks a confidence-bound error")
    return tuple(
        sorted(
            eligible,
            key=lambda value: (
                float(value.worst_confidence_bound_error),
                value.configuration_index,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class WinnerSelection:
    """Roster-complete selection evidence and its semantic first-ranked winner."""

    contract: SelectionContract
    all_assessments: tuple[ArmAssessment, ...]
    winner: ArmAssessment
    ranked_eligible: tuple[ArmAssessment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, SelectionContract):
            raise TypeError("contract must be a SelectionContract")
        if not isinstance(self.winner, ArmAssessment):
            raise TypeError("winner must be an ArmAssessment")
        all_assessments = tuple(self.all_assessments)
        _validate_roster(all_assessments, self.contract)
        all_identities = tuple(
            (
                value.arm_id,
                value.configuration_index,
                value.configuration_identity,
            )
            for value in all_assessments
        )
        if all_identities != tuple(entry.identity for entry in self.contract.expected_arms):
            raise SelectionDataError("all_assessments must follow the precommitted roster order")
        _validate_common_selection_contract(all_assessments)
        if self.contract.expected_hidden_plan_id == all_assessments[0].plan_id:
            raise SelectionDataError(
                "expected hidden plan commitment must differ from the selection plan"
            )
        ranked = tuple(self.ranked_eligible)
        if not ranked:
            raise NoEligibleArmError("winner selection requires an eligible assessment")
        expected = rank_eligible_arms(all_assessments)
        ranked_keys = tuple(_assessment_evidence_identity(value) for value in ranked)
        expected_keys = tuple(_assessment_evidence_identity(value) for value in expected)
        if ranked_keys != expected_keys:
            raise SelectionDataError("ranked_eligible is not in deterministic rank order")
        if _assessment_evidence_identity(self.winner) != expected_keys[0]:
            raise SelectionDataError("winner is not the first deterministically ranked arm")
        object.__setattr__(self, "all_assessments", all_assessments)
        object.__setattr__(self, "ranked_eligible", ranked)


def _validate_roster(
    assessments: tuple[ArmAssessment, ...],
    contract: SelectionContract,
) -> None:
    if any(not isinstance(value, ArmAssessment) for value in assessments):
        raise TypeError("all_assessments must contain ArmAssessment values")
    supplied = tuple(
        (value.arm_id, value.configuration_index, value.configuration_identity)
        for value in assessments
    )
    expected = tuple(entry.identity for entry in contract.expected_arms)
    if len(set(supplied)) != len(supplied) or set(supplied) != set(expected):
        raise SelectionDataError(
            "supplied assessments do not exactly match the precommitted arm roster"
        )


def select_winner(
    assessments: Sequence[ArmAssessment],
    contract: SelectionContract,
) -> WinnerSelection:
    """Validate an exact precommitted roster before eligibility filtering or ranking."""

    if not isinstance(contract, SelectionContract):
        raise TypeError("contract must be a SelectionContract")
    supplied = tuple(assessments)
    _validate_roster(supplied, contract)
    by_identity = {
        (value.arm_id, value.configuration_index, value.configuration_identity): value
        for value in supplied
    }
    ordered = tuple(by_identity[entry.identity] for entry in contract.expected_arms)
    ranked = rank_eligible_arms(ordered)
    if not ranked:
        raise NoEligibleArmError("no arm passed every eligibility gate")
    return WinnerSelection(
        contract=contract,
        all_assessments=ordered,
        winner=ranked[0],
        ranked_eligible=ranked,
    )


@dataclass(frozen=True, slots=True)
class HiddenValidationResult:
    """Validated hidden evidence against the commitment stored at winner selection."""

    selection: WinnerSelection
    hidden_assessment: ArmAssessment

    def __post_init__(self) -> None:
        _validate_hidden_assessment(self.selection, self.hidden_assessment)

    @property
    def selected_winner(self) -> ArmAssessment:
        return self.selection.winner

    @property
    def passed(self) -> bool:
        return self.hidden_assessment.eligible

    @property
    def experiment_stopped(self) -> bool:
        return not self.passed

    @property
    def validated_winner(self) -> ArmAssessment | None:
        return self.selected_winner if self.passed else None


def _validate_hidden_assessment(
    selection: WinnerSelection,
    hidden_assessment: ArmAssessment,
) -> None:
    if not isinstance(selection, WinnerSelection):
        raise TypeError("selection must be a WinnerSelection")
    if not isinstance(hidden_assessment, ArmAssessment):
        raise TypeError("hidden_assessment must be an ArmAssessment")
    if hidden_assessment.assessment_stage != "hidden_validation":
        raise SelectionDataError("hidden evidence must be labeled hidden_validation")
    if (
        hidden_assessment.arm_id != selection.winner.arm_id
        or hidden_assessment.configuration_index != selection.winner.configuration_index
        or hidden_assessment.configuration_identity != selection.winner.configuration_identity
    ):
        raise SelectionDataError("hidden validation must assess exactly the locked winner")
    if hidden_assessment.plan_id != selection.contract.expected_hidden_plan_id:
        raise SelectionDataError(
            "hidden plan does not match the plan identity committed at winner selection"
        )
    if not set(hidden_assessment.score.velocity_pattern_ids).isdisjoint(
        selection.winner.score.velocity_pattern_ids
    ):
        raise SelectionDataError(
            "selection and hidden velocity-pattern banks must be fully disjoint"
        )
    if hidden_assessment.score_id == selection.winner.score_id:
        raise SelectionDataError("hidden validation must use distinct score evidence")
    if hidden_assessment.score.epoch_ids != selection.winner.score.epoch_ids:
        raise SelectionDataError("hidden validation epoch identities are not locked")
    if hidden_assessment.score.cluster_ids != selection.winner.score.cluster_ids:
        raise SelectionDataError("hidden validation cluster identities are not locked")
    if hidden_assessment.score.order_ids != selection.winner.score.order_ids:
        raise SelectionDataError("hidden validation order identities are not locked")
    if hidden_assessment.score.policy != selection.winner.score.policy:
        raise SelectionDataError("hidden validation attrition policy is not locked")
    if (
        hidden_assessment.score.reference_evidence_id
        != selection.winner.score.reference_evidence_id
    ):
        raise SelectionDataError("hidden validation reference evidence is not locked")
    if hidden_assessment.equivalence_interval != selection.winner.equivalence_interval:
        raise SelectionDataError("hidden validation must use the locked equivalence delta")
    hidden_estimate = hidden_assessment.estimate
    selection_estimate = selection.winner.estimate
    if hidden_estimate.seed != selection.contract.expected_hidden_bootstrap_seed:
        raise SelectionDataError(
            "hidden bootstrap seed does not match the value committed at winner selection"
        )
    hidden_ci_contract = (
        hidden_estimate.requested_repetitions,
        hidden_estimate.confidence_level,
        hidden_estimate.minimum_independent_clusters,
        hidden_estimate.interval_method,
    )
    selection_ci_contract = (
        selection_estimate.requested_repetitions,
        selection_estimate.confidence_level,
        selection_estimate.minimum_independent_clusters,
        selection_estimate.interval_method,
    )
    if hidden_ci_contract != selection_ci_contract:
        raise SelectionDataError("hidden validation uncertainty contract is not locked")


def apply_hidden_validation(
    selection: WinnerSelection,
    hidden_assessment: ArmAssessment,
) -> HiddenValidationResult:
    """Validate only the locked winner; a failure never promotes a runner-up.

    The hidden bootstrap seed may differ from the selection seed only when that exact value is
    already committed in :class:`SelectionContract`; repetition count, confidence, cluster
    minimum, and method also remain locked.
    """

    _validate_hidden_assessment(selection, hidden_assessment)
    return HiddenValidationResult(
        selection=selection,
        hidden_assessment=hidden_assessment,
    )


__all__ = [
    "ArmAssessment",
    "ArmGates",
    "ArmRosterEntry",
    "AssessmentStage",
    "AttritionAction",
    "AttritionPolicy",
    "BootstrapFailure",
    "EpochInjectionAudit",
    "EquivalenceInterval",
    "HiddenValidationResult",
    "InjectedResponse",
    "InjectionPlan",
    "InjectionScore",
    "NoEligibleArmError",
    "OrderResponseAudit",
    "RecoverySlopeEstimate",
    "ReferenceResponse",
    "SelectionContract",
    "SelectionDataError",
    "SelectionError",
    "WinnerSelection",
    "apply_hidden_validation",
    "assess_arm",
    "estimate_recovery_slope",
    "rank_eligible_arms",
    "score_injection_responses",
    "select_winner",
]
