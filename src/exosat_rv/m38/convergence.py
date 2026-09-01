"""Control-calibrated, paper- and time-series-free template convergence metrics.

The metrics here consume only adjacent spectral templates and adjacent epoch-by-order RV
matrices.  They do not accept timestamps, periods, or signal models.  All equivalence limits,
the required run length, and the maximum number of updates are supplied by the caller through
``ConvergencePolicy``; this module intentionally contains no unresolved numerical threshold.

``D_T`` is the median absolute adjacent-template change divided by a supplied positive noise
scale in each order.  Its cross-order aggregate is explicitly selected as either the median or
the maximum.  ``D_RV`` is the median absolute change after independently subtracting the median
RV zero point of each adjacent iteration on the common valid epoch/order cells.

NaN may represent a pre-existing invalid cell, but its mask must be identical in adjacent
iterations.  Infinity is always invalid, and any finite-mask or shape change fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]
TemplateAggregate = Literal["median", "maximum"]
FailureCode = Literal["invalid_data", "insufficient_updates", "maximum_iterations"]


class ConvergenceDataError(ValueError):
    """Raised when a metric cannot be evaluated without weakening its validity rules."""


def _readonly_float_array(value: ArrayLike) -> FloatArray:
    array = np.array(value, dtype=np.float64, copy=True)
    array.setflags(write=False)
    return array


def _readonly_int_array(value: ArrayLike) -> IntArray:
    array = np.array(value, dtype=np.int64, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class TemplateChangeMetric:
    """Noise-normalized per-order template changes and their declared aggregate."""

    per_order: FloatArray
    aggregate: float
    aggregate_method: TemplateAggregate
    valid_pixel_counts: IntArray


@dataclass(frozen=True, slots=True)
class RVChangeMetric:
    """Zero-point-invariant adjacent-iteration RV change."""

    value: float
    previous_zero_point: float
    current_zero_point: float
    valid_cell_count: int


@dataclass(frozen=True, slots=True)
class ConvergencePolicy:
    """Frozen limits calibrated and supplied by controls.

    ``d_template_limit`` is dimensionless because ``D_T`` is noise normalized.
    ``d_rv_limit`` uses the same velocity unit as the RV matrices.  No default is provided for
    any unresolved decision, including the cross-order aggregate.
    """

    d_template_limit: float
    d_rv_limit: float
    q_conv: int
    k_max: int
    template_aggregate: TemplateAggregate

    def __post_init__(self) -> None:
        for name, value in (
            ("d_template_limit", self.d_template_limit),
            ("d_rv_limit", self.d_rv_limit),
        ):
            if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
                raise ValueError(f"{name} must be a finite non-negative scalar")
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{name} must be a finite non-negative scalar") from exc
            if not np.isfinite(numeric) or numeric < 0.0:
                raise ValueError(f"{name} must be a finite non-negative scalar")
            object.__setattr__(self, name, numeric)

        for name, value in (("q_conv", self.q_conv), ("k_max", self.k_max)):
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
                raise TypeError(f"{name} must be a positive integer")
            numeric = int(value)
            if numeric < 1:
                raise ValueError(f"{name} must be a positive integer")
            object.__setattr__(self, name, numeric)
        if self.q_conv > self.k_max:
            raise ValueError("q_conv cannot exceed k_max")
        if self.template_aggregate not in ("median", "maximum"):
            raise ValueError("template_aggregate must be 'median' or 'maximum'")


@dataclass(frozen=True, slots=True)
class ConvergenceUpdate:
    """Metrics, threshold decisions, and run length for one attempted update."""

    iteration: int
    template_metric: TemplateChangeMetric | None
    rv_metric: RVChangeMetric | None
    template_passed: bool
    rv_passed: bool
    jointly_passed: bool
    consecutive_joint_passes: int
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConvergenceResult:
    """First-convergence decision or an explicit fail-closed termination."""

    converged: bool
    converged_iteration: int | None
    failure_code: FailureCode | None
    failure_reason: str | None
    history: tuple[ConvergenceUpdate, ...]
    policy: ConvergencePolicy


def _numeric_matrix(value: ArrayLike, name: str) -> FloatArray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConvergenceDataError(f"{name} must be a rectangular numeric array") from exc
    if array.ndim != 2 or 0 in array.shape:
        raise ConvergenceDataError(f"{name} must be a non-empty two-dimensional array")
    return array


def _declared_mask(value: ArrayLike | None, shape: tuple[int, int], name: str) -> BoolArray | None:
    if value is None:
        return None
    try:
        array = np.asarray(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConvergenceDataError(f"{name} must be a boolean array with shape {shape}") from exc
    if array.dtype.kind != "b" or array.shape != shape:
        raise ConvergenceDataError(f"{name} must be a boolean array with shape {shape}")
    return np.asarray(array, dtype=np.bool_)


def _common_active_mask(
    previous: FloatArray,
    current: FloatArray,
    declared_mask: ArrayLike | None,
    mask_name: str,
) -> BoolArray:
    if np.any(np.isinf(previous)) or np.any(np.isinf(current)):
        raise ConvergenceDataError("infinite values are forbidden")
    previous_finite = np.isfinite(previous)
    current_finite = np.isfinite(current)
    if not np.array_equal(previous_finite, current_finite):
        raise ConvergenceDataError("finite mask changed between adjacent iterations")

    requested = _declared_mask(declared_mask, previous.shape, mask_name)
    active = previous_finite if requested is None else requested
    if np.any(active & ~previous_finite):
        raise ConvergenceDataError(f"{mask_name} selects a non-finite cell")
    if not np.any(active):
        raise ConvergenceDataError("no common finite cells remain")
    return active


def template_change_metric(
    previous_template: ArrayLike,
    current_template: ArrayLike,
    adjacent_noise_scale: ArrayLike,
    *,
    aggregate: TemplateAggregate,
    valid_mask: ArrayLike | None = None,
) -> TemplateChangeMetric:
    """Compute robust, noise-normalized adjacent-template change ``D_T``.

    Arrays have shape ``(order, pixel)``.  ``adjacent_noise_scale`` is the predeclared
    one-sigma scale for the *difference* between the two templates, not an individual-template
    uncertainty.  Templates must already be aligned by the caller's frozen global wavelength
    alignment rule; this function neither estimates nor consumes target RV structure.
    """
    if aggregate not in ("median", "maximum"):
        raise ConvergenceDataError("aggregate must be 'median' or 'maximum'")
    previous = _numeric_matrix(previous_template, "previous_template")
    current = _numeric_matrix(current_template, "current_template")
    noise = _numeric_matrix(adjacent_noise_scale, "adjacent_noise_scale")
    if current.shape != previous.shape:
        raise ConvergenceDataError("template shape changed between adjacent iterations")
    if noise.shape != previous.shape:
        raise ConvergenceDataError("adjacent_noise_scale must match the template shape")

    active = _common_active_mask(previous, current, valid_mask, "valid_mask")
    if np.any(np.isinf(noise)):
        raise ConvergenceDataError("adjacent_noise_scale cannot contain infinity")
    if np.any(~np.isfinite(noise[active])) or np.any(noise[active] <= 0.0):
        raise ConvergenceDataError(
            "adjacent_noise_scale must be finite and positive on every valid pixel"
        )

    counts = np.sum(active, axis=1, dtype=np.int64)
    if np.any(counts == 0):
        raise ConvergenceDataError("every order must retain at least one common valid pixel")
    per_order = np.empty(previous.shape[0], dtype=np.float64)
    for order_index in range(previous.shape[0]):
        order_mask = active[order_index]
        try:
            with np.errstate(over="raise", divide="raise", invalid="raise"):
                standardized_change = (
                    np.abs(current[order_index, order_mask] - previous[order_index, order_mask])
                    / noise[order_index, order_mask]
                )
                per_order[order_index] = float(np.median(standardized_change))
        except FloatingPointError as exc:
            raise ConvergenceDataError("D_T calculation overflowed") from exc
    aggregate_value = (
        float(np.median(per_order)) if aggregate == "median" else float(np.max(per_order))
    )
    if not np.all(np.isfinite(per_order)) or not np.isfinite(aggregate_value):
        raise ConvergenceDataError("D_T became non-finite")
    return TemplateChangeMetric(
        per_order=_readonly_float_array(per_order),
        aggregate=aggregate_value,
        aggregate_method=aggregate,
        valid_pixel_counts=_readonly_int_array(counts),
    )


def rv_change_metric(
    previous_rv: ArrayLike,
    current_rv: ArrayLike,
    *,
    valid_mask: ArrayLike | None = None,
) -> RVChangeMetric:
    """Compute zero-point-invariant adjacent-iteration RV change ``D_RV``.

    RV arrays have shape ``(epoch, order)``.  Each iteration's global median over the same
    common finite cells is removed independently, so adding an arbitrary constant to either
    complete iteration does not affect the result.
    """
    previous = _numeric_matrix(previous_rv, "previous_rv")
    current = _numeric_matrix(current_rv, "current_rv")
    if current.shape != previous.shape:
        raise ConvergenceDataError("RV shape changed between adjacent iterations")
    active = _common_active_mask(previous, current, valid_mask, "valid_mask")
    if np.any(np.sum(active, axis=1) == 0):
        raise ConvergenceDataError("every epoch must retain at least one common valid order")
    if np.any(np.sum(active, axis=0) == 0):
        raise ConvergenceDataError("every order must retain at least one common valid epoch")

    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            previous_zero_point = float(np.median(previous[active]))
            current_zero_point = float(np.median(current[active]))
            adjacent_change = (current[active] - current_zero_point) - (
                previous[active] - previous_zero_point
            )
            value = float(np.median(np.abs(adjacent_change)))
    except FloatingPointError as exc:
        raise ConvergenceDataError("D_RV calculation overflowed") from exc
    if not all(np.isfinite(item) for item in (previous_zero_point, current_zero_point, value)):
        raise ConvergenceDataError("D_RV became non-finite")
    return RVChangeMetric(
        value=value,
        previous_zero_point=previous_zero_point,
        current_zero_point=current_zero_point,
        valid_cell_count=int(np.count_nonzero(active)),
    )


def _invalid_result(
    policy: ConvergencePolicy,
    reason: str,
    history: list[ConvergenceUpdate] | None = None,
) -> ConvergenceResult:
    return ConvergenceResult(
        converged=False,
        converged_iteration=None,
        failure_code="invalid_data",
        failure_reason=reason,
        history=tuple(history or ()),
        policy=policy,
    )


def _numeric_cube(value: ArrayLike, name: str) -> FloatArray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConvergenceDataError(f"{name} must be a rectangular numeric array") from exc
    if array.ndim != 3 or 0 in array.shape:
        raise ConvergenceDataError(f"{name} must be a non-empty three-dimensional array")
    return array


def evaluate_convergence(
    template_states: ArrayLike,
    adjacent_template_noise_scales: ArrayLike,
    rv_states: ArrayLike,
    policy: ConvergencePolicy,
    *,
    template_valid_mask: ArrayLike | None = None,
    rv_valid_mask: ArrayLike | None = None,
) -> ConvergenceResult:
    """Evaluate adjacent updates and stop at the first policy-defined convergence.

    ``template_states`` has shape ``(state, order, pixel)`` and ``rv_states`` has shape
    ``(state, epoch, order)``.  The state and order counts must match.  Noise scales have
    shape ``(state - 1, order, pixel)``, one for every adjacent template difference.

    If fewer than ``k_max`` updates are supplied, they may still converge; otherwise the
    result explicitly reports insufficient updates rather than claiming non-convergence.
    Invalid shapes, masks, or non-finite valid data return ``failure_code='invalid_data'``.
    """
    if not isinstance(policy, ConvergencePolicy):
        raise TypeError("policy must be a ConvergencePolicy")
    try:
        templates = _numeric_cube(template_states, "template_states")
        noises = _numeric_cube(
            adjacent_template_noise_scales,
            "adjacent_template_noise_scales",
        )
        rvs = _numeric_cube(rv_states, "rv_states")
    except ConvergenceDataError as exc:
        return _invalid_result(policy, str(exc))

    if templates.shape[0] < 2:
        return _invalid_result(policy, "at least two template states are required")
    if rvs.shape[0] != templates.shape[0]:
        return _invalid_result(policy, "template and RV state counts differ")
    if rvs.shape[2] != templates.shape[1]:
        return _invalid_result(policy, "template and RV order counts differ")
    available_updates = templates.shape[0] - 1
    expected_noise_shape = (available_updates, *templates.shape[1:])
    if noises.shape != expected_noise_shape:
        return _invalid_result(
            policy,
            f"adjacent_template_noise_scales must have shape {expected_noise_shape}",
        )

    history: list[ConvergenceUpdate] = []
    consecutive = 0
    updates_to_evaluate = min(available_updates, policy.k_max)
    for state_index in range(1, updates_to_evaluate + 1):
        iteration = state_index
        try:
            template_metric = template_change_metric(
                templates[state_index - 1],
                templates[state_index],
                noises[state_index - 1],
                aggregate=policy.template_aggregate,
                valid_mask=template_valid_mask,
            )
        except ConvergenceDataError as exc:
            history.append(
                ConvergenceUpdate(
                    iteration=iteration,
                    template_metric=None,
                    rv_metric=None,
                    template_passed=False,
                    rv_passed=False,
                    jointly_passed=False,
                    consecutive_joint_passes=0,
                    failure_reason=str(exc),
                )
            )
            return _invalid_result(policy, f"iteration {iteration}: {exc}", history)

        try:
            rv_metric = rv_change_metric(
                rvs[state_index - 1],
                rvs[state_index],
                valid_mask=rv_valid_mask,
            )
        except ConvergenceDataError as exc:
            history.append(
                ConvergenceUpdate(
                    iteration=iteration,
                    template_metric=template_metric,
                    rv_metric=None,
                    template_passed=template_metric.aggregate <= policy.d_template_limit,
                    rv_passed=False,
                    jointly_passed=False,
                    consecutive_joint_passes=0,
                    failure_reason=str(exc),
                )
            )
            return _invalid_result(policy, f"iteration {iteration}: {exc}", history)

        template_passed = template_metric.aggregate <= policy.d_template_limit
        rv_passed = rv_metric.value <= policy.d_rv_limit
        jointly_passed = template_passed and rv_passed
        consecutive = consecutive + 1 if jointly_passed else 0
        history.append(
            ConvergenceUpdate(
                iteration=iteration,
                template_metric=template_metric,
                rv_metric=rv_metric,
                template_passed=template_passed,
                rv_passed=rv_passed,
                jointly_passed=jointly_passed,
                consecutive_joint_passes=consecutive,
            )
        )
        if consecutive >= policy.q_conv:
            return ConvergenceResult(
                converged=True,
                converged_iteration=iteration,
                failure_code=None,
                failure_reason=None,
                history=tuple(history),
                policy=policy,
            )

    if available_updates < policy.k_max:
        return ConvergenceResult(
            converged=False,
            converged_iteration=None,
            failure_code="insufficient_updates",
            failure_reason=(
                f"only {available_updates} updates were supplied before k_max={policy.k_max}"
            ),
            history=tuple(history),
            policy=policy,
        )
    return ConvergenceResult(
        converged=False,
        converged_iteration=None,
        failure_code="maximum_iterations",
        failure_reason=f"convergence was not reached by k_max={policy.k_max}",
        history=tuple(history),
        policy=policy,
    )
