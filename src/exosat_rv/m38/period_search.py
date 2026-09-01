"""Paper-independent period-search and adaptive-pipeline calibration primitives.

This module is deliberately limited to numerical infrastructure for simulations and
declared controls.  It performs no I/O, chooses no period grid or baseline bound, and has no
target-specific execution path.  In particular, :func:`calibrate_global_max_statistic`
calibrates a *fixed* design and period grid.  It is not a familywise calibration of an
adaptive extraction workflow; :func:`run_adaptive_pipeline_calibration` exists to exercise
such a workflow through a caller-owned whole-pipeline callback.

The callback harness can guarantee a separate invocation and unique trial identifier for
every planned trial, and it rejects an outcome carrying a stale identifier.  It cannot inspect
the callback's internals, so the caller remains responsible for constructing fresh state,
injecting signals before any adaptive/template work, and replaying the complete frozen
pipeline on every invocation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from statistics import NormalDist
from typing import Literal, Protocol, TypeAlias

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray: TypeAlias = NDArray[np.float64]
IntArray: TypeAlias = NDArray[np.int64]
TrialKind: TypeAlias = Literal["null", "signal"]
FailureStage: TypeAlias = Literal["pipeline", "outcome", "recovery_rule"]
IntervalMethod: TypeAlias = Literal["wilson"]
InterpolationPolicy: TypeAlias = Literal["none", "linear"]

_CONDITIONAL_NULL_SEED_DOMAIN = 0x434E554C
_ADAPTIVE_NULL_SEED_DOMAIN = 0x414E554C
_ADAPTIVE_SIGNAL_SEED_DOMAIN = 0x41534947
_STRICT_JSON_MAX_DEPTH = 64


class PeriodSearchError(ValueError):
    """Base class for deterministic period-search validation and fit failures."""


class RankDeficiencyError(PeriodSearchError):
    """Raised when a declared null or periodic design is not full column rank."""


class NumericalFitError(PeriodSearchError):
    """Raised when weighted least squares produces a non-finite/inconsistent result."""


class IncompleteCalibrationError(RuntimeError):
    """Raised when a failed null trial makes a calibrated probability unavailable."""


def _readonly_float_array(values: ArrayLike) -> FloatArray:
    result = np.array(values, dtype=np.float64, copy=True, order="C")
    result.setflags(write=False)
    return result


def _readonly_int_array(values: ArrayLike) -> IntArray:
    result = np.array(values, dtype=np.int64, copy=True, order="C")
    result.setflags(write=False)
    return result


def _float_vector(values: ArrayLike, name: str, *, nonempty: bool = True) -> FloatArray:
    try:
        result = np.array(values, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise PeriodSearchError(f"{name} must be a one-dimensional numeric array") from exc
    if result.ndim != 1:
        raise PeriodSearchError(f"{name} must be one-dimensional")
    if nonempty and result.size == 0:
        raise PeriodSearchError(f"{name} must not be empty")
    if not np.all(np.isfinite(result)):
        raise PeriodSearchError(f"{name} must contain only finite values")
    return result


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _seed(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def _spawn_seeds(seed: int, count: int, *, domain: int) -> tuple[int, ...]:
    """Derive a deterministic, domain-separated stream of auditable child seeds."""

    root = np.random.SeedSequence([seed, domain])
    children = tuple(
        int(child.generate_state(1, dtype=np.uint64)[0]) for child in root.spawn(count)
    )
    if len(set(children)) != count:
        raise RuntimeError("child-seed derivation produced a duplicate within one domain")
    return children


def _strict_json_copy(value: object, *, path: str = "plan_metadata") -> object:
    """Return a detached JSON-native value without encoder coercions or recursion leaks."""

    active_containers: set[int] = set()

    def visit(item: object, *, item_path: str, depth: int) -> object:
        if depth > _STRICT_JSON_MAX_DEPTH:
            raise ValueError(
                f"{item_path} exceeds the strict-JSON maximum depth of {_STRICT_JSON_MAX_DEPTH}"
            )
        if item is None or type(item) in {str, bool}:
            return item
        if isinstance(item, Integral):
            return int(item)
        if isinstance(item, (float, np.floating)):
            number = float(item)
            if not np.isfinite(number):
                raise ValueError(f"{item_path} contains a non-finite number")
            return number
        if isinstance(item, (Mapping, list)):
            container_id = id(item)
            if container_id in active_containers:
                raise ValueError(f"{item_path} contains a cyclic JSON container")
            active_containers.add(container_id)
            try:
                if isinstance(item, Mapping):
                    result: dict[str, object] = {}
                    for key, child in item.items():
                        if type(key) is not str:
                            raise TypeError(f"{item_path} mappings must use string keys")
                        result[key] = visit(
                            child,
                            item_path=f"{item_path}.{key}",
                            depth=depth + 1,
                        )
                    return result
                return [
                    visit(
                        child,
                        item_path=f"{item_path}[{index}]",
                        depth=depth + 1,
                    )
                    for index, child in enumerate(item)
                ]
            finally:
                active_containers.remove(container_id)
        raise TypeError(f"{item_path} contains a non-JSON value of type {type(item).__name__}")

    return visit(value, item_path=path, depth=0)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_rcond(rcond: float | None) -> float | None:
    if rcond is None:
        return None
    value = float(rcond)
    if not np.isfinite(value) or value <= 0.0:
        raise PeriodSearchError("rcond must be finite and positive when supplied")
    return value


def build_null_design_matrix(
    n_observations: int,
    nuisance_regressors: ArrayLike | None = None,
    *,
    include_intercept: bool = True,
) -> FloatArray:
    """Build the explicit null-model matrix ``[intercept?, nuisance...]``.

    A one-dimensional nuisance regressor is treated as one column; a two-dimensional input
    preserves caller column order.  Rank is checked during fitting because it depends on the
    complete matrix.  The returned matrix is an owned, read-only array.
    """

    n_rows = _positive_int(n_observations, "n_observations")
    if not isinstance(include_intercept, (bool, np.bool_)):
        raise PeriodSearchError("include_intercept must be boolean")

    if nuisance_regressors is None:
        nuisance = np.empty((n_rows, 0), dtype=np.float64)
    else:
        try:
            nuisance = np.array(nuisance_regressors, dtype=np.float64, copy=True)
        except (TypeError, ValueError) as exc:
            raise PeriodSearchError("nuisance_regressors must be a numeric matrix") from exc
        if nuisance.ndim == 1:
            nuisance = nuisance[:, np.newaxis]
        if nuisance.ndim != 2:
            raise PeriodSearchError("nuisance_regressors must be one- or two-dimensional")
        if nuisance.shape[0] != n_rows:
            raise PeriodSearchError("nuisance_regressors row count must match the observations")
        if not np.all(np.isfinite(nuisance)):
            raise PeriodSearchError("nuisance_regressors must contain only finite values")

    parts: list[FloatArray] = []
    if include_intercept:
        parts.append(np.ones((n_rows, 1), dtype=np.float64))
    if nuisance.shape[1]:
        parts.append(nuisance)
    if parts:
        design = np.column_stack(parts)
    else:
        design = np.empty((n_rows, 0), dtype=np.float64)
    return _readonly_float_array(design)


def build_periodic_design_matrix(
    times: ArrayLike,
    period: float,
    null_design_matrix: ArrayLike,
    *,
    reference_time: float | None = None,
) -> FloatArray:
    """Build ``[null..., sin(omega dt), cos(omega dt)]`` for one period.

    If ``reference_time`` is omitted, the smallest supplied time is used.  The chosen origin
    changes sinusoid phase coefficients but not their quadrature amplitude or model span.
    """

    time_values = _float_vector(times, "times")
    period_value = float(period)
    if not np.isfinite(period_value) or period_value <= 0.0:
        raise PeriodSearchError("period must be finite and positive")
    try:
        null_design = np.array(null_design_matrix, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise PeriodSearchError("null_design_matrix must be a numeric matrix") from exc
    if null_design.ndim != 2 or null_design.shape[0] != time_values.size:
        raise PeriodSearchError(
            "null_design_matrix must be two-dimensional with one row per observation"
        )
    if not np.all(np.isfinite(null_design)):
        raise PeriodSearchError("null_design_matrix must contain only finite values")

    origin = float(np.min(time_values)) if reference_time is None else float(reference_time)
    if not np.isfinite(origin):
        raise PeriodSearchError("reference_time must be finite")
    phase = (2.0 * np.pi / period_value) * (time_values - origin)
    if not np.all(np.isfinite(phase)):
        raise PeriodSearchError("periodic phase calculation produced non-finite values")
    design = np.column_stack((null_design, np.sin(phase), np.cos(phase)))
    if not np.all(np.isfinite(design)):
        raise PeriodSearchError("periodic design matrix contains non-finite values")
    return _readonly_float_array(design)


@dataclass(frozen=True, slots=True)
class WeightedLinearFit:
    """One full-rank weighted linear fit."""

    coefficients: FloatArray
    fitted_values: FloatArray
    residuals: FloatArray
    chi2: float
    rank: int
    dof: int


@dataclass(frozen=True, slots=True)
class PeriodSearchResult:
    """Complete landscape for a caller-supplied period grid.

    ``periodic_coefficients`` columns follow the explicit periodic design: all null columns,
    then sine and cosine.  ``amplitudes`` is the sine/cosine quadrature norm.  Ties in
    ``best_index`` are resolved by the first period in the supplied (strictly increasing)
    grid.
    """

    times: FloatArray
    values: FloatArray
    uncertainties: FloatArray
    periods: FloatArray
    reference_time: float
    null_design_matrix: FloatArray
    null_fit: WeightedLinearFit
    periodic_coefficients: FloatArray
    chi2: FloatArray
    delta_chi2: FloatArray
    amplitudes: FloatArray
    ranks: IntArray
    dof: IntArray

    @property
    def best_index(self) -> int:
        """Index of the deterministic maximum improvement."""

        return int(np.argmax(self.delta_chi2))

    @property
    def best_period(self) -> float:
        """Period at the maximum improvement."""

        return float(self.periods[self.best_index])

    @property
    def max_statistic(self) -> float:
        """Maximum ``delta_chi2`` across the complete declared grid."""

        return float(self.delta_chi2[self.best_index])

    def periodic_design_matrix(self, index: int) -> FloatArray:
        """Reconstruct the explicit periodic matrix for one landscape row."""

        if isinstance(index, bool) or not isinstance(index, Integral):
            raise IndexError("period index must be an integer")
        position = int(index)
        if position < 0 or position >= self.periods.size:
            raise IndexError("period index out of range")
        return build_periodic_design_matrix(
            self.times,
            float(self.periods[position]),
            self.null_design_matrix,
            reference_time=self.reference_time,
        )


def _weighted_fit(
    design: FloatArray,
    values: FloatArray,
    uncertainties: FloatArray,
    *,
    rcond: float | None,
    model_label: str,
) -> WeightedLinearFit:
    n_rows, n_columns = design.shape
    if n_rows <= n_columns:
        raise RankDeficiencyError(
            f"{model_label} requires positive residual degrees of freedom "
            f"({n_rows} rows, {n_columns} columns)"
        )

    if n_columns == 0:
        coefficients = np.empty(0, dtype=np.float64)
        fitted = np.zeros(n_rows, dtype=np.float64)
        rank = 0
    else:
        try:
            with np.errstate(over="raise", divide="raise", invalid="raise"):
                weighted_design = design / uncertainties[:, np.newaxis]
                weighted_values = values / uncertainties
            coefficients, _, rank, _ = np.linalg.lstsq(
                weighted_design, weighted_values, rcond=rcond
            )
        except (FloatingPointError, np.linalg.LinAlgError) as exc:
            raise NumericalFitError(f"{model_label} weighted least squares failed") from exc
        if int(rank) != n_columns:
            raise RankDeficiencyError(
                f"{model_label} design is rank deficient: rank {rank}, expected {n_columns}"
            )
        fitted = design @ coefficients

    residuals = values - fitted
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            weighted_residuals = residuals / uncertainties
            chi2 = float(np.dot(weighted_residuals, weighted_residuals))
    except FloatingPointError as exc:
        raise NumericalFitError(f"{model_label} chi-square calculation failed") from exc
    if (
        not np.all(np.isfinite(coefficients))
        or not np.all(np.isfinite(fitted))
        or not np.all(np.isfinite(residuals))
        or not np.isfinite(chi2)
        or chi2 < 0.0
    ):
        raise NumericalFitError(f"{model_label} fit produced a non-finite result")

    return WeightedLinearFit(
        coefficients=_readonly_float_array(coefficients),
        fitted_values=_readonly_float_array(fitted),
        residuals=_readonly_float_array(residuals),
        chi2=chi2,
        rank=int(rank),
        dof=n_rows - int(rank),
    )


def weighted_sinusoid_search(
    times: ArrayLike,
    values: ArrayLike,
    uncertainties: ArrayLike,
    periods: ArrayLike,
    *,
    nuisance_regressors: ArrayLike | None = None,
    include_intercept: bool = True,
    reference_time: float | None = None,
    rcond: float | None = None,
) -> PeriodSearchResult:
    """Fit a weighted sinusoid at every period in an explicit caller-owned grid.

    No grid or baseline policy is inferred.  Callers must construct the exact grid (and apply
    any baseline-derived upper bound) before this function is called.  Every declared grid
    point must yield a finite, full-column-rank periodic design with positive residual degrees
    of freedom; otherwise the entire search fails closed.
    """

    time_values = _float_vector(times, "times")
    observations = _float_vector(values, "values")
    sigma = _float_vector(uncertainties, "uncertainties")
    period_grid = _float_vector(periods, "periods")
    if observations.size != time_values.size or sigma.size != time_values.size:
        raise PeriodSearchError("times, values, and uncertainties must have identical lengths")
    if np.any(sigma <= 0.0):
        raise PeriodSearchError("uncertainties must be strictly positive")
    if np.any(period_grid <= 0.0):
        raise PeriodSearchError("periods must be strictly positive")
    if period_grid.size > 1 and np.any(np.diff(period_grid) <= 0.0):
        raise PeriodSearchError("periods must be strictly increasing with no duplicates")
    rcond_value = _validate_rcond(rcond)

    origin = float(np.min(time_values)) if reference_time is None else float(reference_time)
    if not np.isfinite(origin):
        raise PeriodSearchError("reference_time must be finite")
    null_design = build_null_design_matrix(
        time_values.size,
        nuisance_regressors,
        include_intercept=include_intercept,
    )
    null_fit = _weighted_fit(
        null_design,
        observations,
        sigma,
        rcond=rcond_value,
        model_label="null model",
    )

    coefficient_count = null_design.shape[1] + 2
    coefficients = np.empty((period_grid.size, coefficient_count), dtype=np.float64)
    chi2 = np.empty(period_grid.size, dtype=np.float64)
    amplitudes = np.empty(period_grid.size, dtype=np.float64)
    ranks = np.empty(period_grid.size, dtype=np.int64)
    dof = np.empty(period_grid.size, dtype=np.int64)

    for index, period in enumerate(period_grid):
        design = build_periodic_design_matrix(
            time_values,
            float(period),
            null_design,
            reference_time=origin,
        )
        fit = _weighted_fit(
            design,
            observations,
            sigma,
            rcond=rcond_value,
            model_label=f"periodic model at grid index {index}",
        )
        coefficients[index] = fit.coefficients
        chi2[index] = fit.chi2
        amplitudes[index] = float(np.hypot(fit.coefficients[-2], fit.coefficients[-1]))
        ranks[index] = fit.rank
        dof[index] = fit.dof

    delta_chi2 = null_fit.chi2 - chi2
    tolerance = 1e-10 * max(1.0, null_fit.chi2)
    if not np.all(np.isfinite(delta_chi2)):
        raise NumericalFitError("period landscape contains a non-finite improvement")
    if np.any(delta_chi2 < -tolerance):
        raise NumericalFitError("a nested periodic fit is worse than the fitted null model")
    delta_chi2 = np.maximum(delta_chi2, 0.0)

    return PeriodSearchResult(
        times=_readonly_float_array(time_values),
        values=_readonly_float_array(observations),
        uncertainties=_readonly_float_array(sigma),
        periods=_readonly_float_array(period_grid),
        reference_time=origin,
        null_design_matrix=null_design,
        null_fit=null_fit,
        periodic_coefficients=_readonly_float_array(coefficients),
        chi2=_readonly_float_array(chi2),
        delta_chi2=_readonly_float_array(delta_chi2),
        amplitudes=_readonly_float_array(amplitudes),
        ranks=_readonly_int_array(ranks),
        dof=_readonly_int_array(dof),
    )


@dataclass(frozen=True, slots=True)
class NullSimulationFailure:
    """One failed conditional-Gaussian null simulation."""

    trial_index: int
    trial_seed: int
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class GlobalNullCalibration:
    """Max-statistic calibration for one fixed search design and period grid."""

    observed_search: PeriodSearchResult
    seed: int
    requested_simulations: int
    simulation_seeds: tuple[int, ...]
    simulation_statistics: FloatArray
    failures: tuple[NullSimulationFailure, ...]
    exceedance_count: int | None
    p_value: float | None

    @property
    def complete(self) -> bool:
        """Whether all requested simulations completed and the p-value is valid."""

        return not self.failures and self.p_value is not None


def calibrate_global_max_statistic(
    times: ArrayLike,
    values: ArrayLike,
    uncertainties: ArrayLike,
    periods: ArrayLike,
    *,
    simulations: int,
    seed: int,
    nuisance_regressors: ArrayLike | None = None,
    include_intercept: bool = True,
    reference_time: float | None = None,
    rcond: float | None = None,
) -> GlobalNullCalibration:
    """Conditionally calibrate the period-grid maximum under a fitted Gaussian null.

    The null mean is the fitted explicit null design, uncertainties and regressors are held
    fixed, and each simulation is searched over the complete declared grid.  The returned
    p-value is ``(1 + count(T_sim >= T_obs)) / (simulations + 1)``.  If any requested trial
    fails, its statistic remains ``NaN``, the failure is recorded, and both the exceedance
    count and p-value are unavailable rather than being computed from a successful subset.
    """

    simulation_count = _positive_int(simulations, "simulations")
    master_seed = _seed(seed, "seed")
    observed = weighted_sinusoid_search(
        times,
        values,
        uncertainties,
        periods,
        nuisance_regressors=nuisance_regressors,
        include_intercept=include_intercept,
        reference_time=reference_time,
        rcond=rcond,
    )
    trial_seeds = _spawn_seeds(
        master_seed,
        simulation_count,
        domain=_CONDITIONAL_NULL_SEED_DOMAIN,
    )
    statistics = np.full(simulation_count, np.nan, dtype=np.float64)
    failures: list[NullSimulationFailure] = []

    for index, trial_seed in enumerate(trial_seeds):
        rng = np.random.default_rng(trial_seed)
        simulated_values = observed.null_fit.fitted_values + rng.normal(
            loc=0.0, scale=observed.uncertainties
        )
        try:
            simulated_search = weighted_sinusoid_search(
                observed.times,
                simulated_values,
                observed.uncertainties,
                observed.periods,
                nuisance_regressors=(
                    observed.null_design_matrix[:, int(include_intercept) :]
                    if observed.null_design_matrix.shape[1] > int(include_intercept)
                    else None
                ),
                include_intercept=include_intercept,
                reference_time=observed.reference_time,
                rcond=rcond,
            )
        except Exception as exc:  # noqa: BLE001 - every failed simulation must be recorded.
            failures.append(
                NullSimulationFailure(
                    trial_index=index,
                    trial_seed=trial_seed,
                    exception_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        statistics[index] = simulated_search.max_statistic

    if failures:
        exceedance_count = None
        p_value = None
    else:
        exceedance_count = int(np.count_nonzero(statistics >= observed.max_statistic))
        p_value = (exceedance_count + 1.0) / (simulation_count + 1.0)

    return GlobalNullCalibration(
        observed_search=observed,
        seed=master_seed,
        requested_simulations=simulation_count,
        simulation_seeds=trial_seeds,
        simulation_statistics=_readonly_float_array(statistics),
        failures=tuple(failures),
        exceedance_count=exceedance_count,
        p_value=p_value,
    )


@dataclass(frozen=True, slots=True)
class PipelineTrial:
    """Immutable request for one fresh whole-pipeline invocation."""

    trial_id: str
    plan_id: str
    kind: TrialKind
    trial_seed: int
    replicate_index: int
    amplitude_index: int | None = None
    phase_index: int | None = None
    amplitude: float | None = None
    phase: float | None = None


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """Minimal auditable outcome returned by a whole-pipeline callback.

    ``max_statistic`` must be the final frozen grid maximum after all adaptive choices.  The
    strict-JSON ``details`` value can carry period/orbit estimates needed by a caller-owned,
    paper-independent recovery rule.  The harness validates and detaches it before recording
    the outcome or passing it to that rule.
    """

    trial_id: str
    max_statistic: float
    details: object | None = None


class WholePipelineCallback(Protocol):
    """Callable that constructs fresh state and runs the complete pipeline once."""

    def __call__(self, trial: PipelineTrial, /) -> PipelineOutcome: ...


class RecoveryRule(Protocol):
    """Paper-independent association/recovery decision for one signal outcome."""

    def __call__(self, trial: PipelineTrial, outcome: PipelineOutcome, /) -> bool: ...


@dataclass(frozen=True, slots=True)
class PipelineTrialFailure:
    """Auditable failure of a planned pipeline or recovery-rule trial."""

    trial_id: str
    kind: TrialKind
    stage: FailureStage
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class PipelineTrialRecord:
    """One planned trial, including outcome, decision, and any failure."""

    trial: PipelineTrial
    outcome: PipelineOutcome | None
    recovered: bool | None
    failure: PipelineTrialFailure | None


@dataclass(frozen=True, slots=True)
class PipelineNullCalibration:
    """Full-pipeline null max statistics with no successful-subset fallback."""

    plan_id: str
    seed: int
    requested_trials: int
    records: tuple[PipelineTrialRecord, ...]
    statistics: FloatArray
    failures: tuple[PipelineTrialFailure, ...]

    @property
    def complete(self) -> bool:
        """Whether every planned null invocation returned a valid outcome."""

        return not self.failures and len(self.records) == self.requested_trials

    def plus_one_p_value(self, observed_max_statistic: float) -> float:
        """Return the global plus-one empirical p-value for a supplied statistic.

        An incomplete ensemble raises instead of silently dropping failed trials.
        """

        observed = float(observed_max_statistic)
        if not np.isfinite(observed):
            raise ValueError("observed_max_statistic must be finite")
        if not self.complete:
            raise IncompleteCalibrationError(
                "full-pipeline null calibration has failed trials; p-value unavailable"
            )
        exceedances = int(np.count_nonzero(self.statistics >= observed))
        return (exceedances + 1.0) / (self.requested_trials + 1.0)


@dataclass(frozen=True, slots=True)
class BinomialInterval:
    """Two-sided binomial proportion interval metadata."""

    lower: float
    upper: float
    confidence_level: float
    method: IntervalMethod


@dataclass(frozen=True, slots=True)
class AmplitudeCompleteness:
    """Completeness and failure accounting for one declared amplitude."""

    amplitude: float
    planned_trials: int
    recovered_trials: int
    failed_trials: int
    completeness: float
    interval: BinomialInterval
    records: tuple[PipelineTrialRecord, ...]


@dataclass(frozen=True, slots=True)
class DetectionCompleteness:
    """Full fixed-grid signal ensemble and per-amplitude completeness."""

    plan_id: str
    seed: int
    amplitudes: FloatArray
    phases: FloatArray
    replicates_per_cell: int
    evidence_threshold: float
    confidence_level: float
    interval_method: IntervalMethod
    interpolation_policy: InterpolationPolicy
    points: tuple[AmplitudeCompleteness, ...]
    records: tuple[PipelineTrialRecord, ...]
    failures: tuple[PipelineTrialFailure, ...]

    @property
    def complete(self) -> bool:
        """Whether every signal callback and recovery decision completed."""

        return not self.failures

    def completeness_at(self, amplitude: float) -> float:
        """Return a grid value, or a linearly interpolated value only if predeclared.

        Linear interpolation applies only to the point estimate.  No interval or sensitivity
        bound is inferred between grid points.
        """

        value = float(amplitude)
        if not np.isfinite(value):
            raise ValueError("amplitude must be finite")
        matches = np.flatnonzero(self.amplitudes == value)
        if matches.size:
            return self.points[int(matches[0])].completeness
        if self.interpolation_policy == "none":
            raise ValueError("amplitude was not evaluated and interpolation is disabled")
        if value < self.amplitudes[0] or value > self.amplitudes[-1]:
            raise ValueError("linear interpolation is limited to the evaluated amplitude grid")
        estimates = np.array([point.completeness for point in self.points], dtype=np.float64)
        return float(np.interp(value, self.amplitudes, estimates))


@dataclass(frozen=True, slots=True)
class AdaptivePipelineCalibration:
    """Combined full-pipeline null calibration and signal completeness experiment."""

    plan_id: str
    null: PipelineNullCalibration
    completeness: DetectionCompleteness

    @property
    def complete(self) -> bool:
        """Whether both planned ensembles completed without failures."""

        return self.null.complete and self.completeness.complete

    def false_alarm_probability_at_threshold(self) -> float:
        """Plus-one null tail probability at the frozen evidence threshold."""

        return self.null.plus_one_p_value(self.completeness.evidence_threshold)


def wilson_interval(
    successes: int,
    trials: int,
    *,
    confidence_level: float,
) -> BinomialInterval:
    """Compute a two-sided Wilson score interval for a binomial proportion."""

    n_trials = _positive_int(trials, "trials")
    if isinstance(successes, bool) or not isinstance(successes, Integral):
        raise TypeError("successes must be an integer")
    n_successes = int(successes)
    if n_successes < 0 or n_successes > n_trials:
        raise ValueError("successes must lie between zero and trials")
    level = float(confidence_level)
    if not np.isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError("confidence_level must lie strictly between zero and one")

    z_value = NormalDist().inv_cdf(0.5 + level / 2.0)
    proportion = n_successes / n_trials
    z_squared = z_value * z_value
    denominator = 1.0 + z_squared / n_trials
    centre = (proportion + z_squared / (2.0 * n_trials)) / denominator
    half_width = (
        z_value
        * np.sqrt(
            proportion * (1.0 - proportion) / n_trials + z_squared / (4.0 * n_trials * n_trials)
        )
        / denominator
    )
    return BinomialInterval(
        lower=max(0.0, float(centre - half_width)),
        upper=min(1.0, float(centre + half_width)),
        confidence_level=level,
        method="wilson",
    )


def _pipeline_invocation(
    callback: WholePipelineCallback,
    trial: PipelineTrial,
) -> tuple[PipelineOutcome | None, PipelineTrialFailure | None]:
    try:
        outcome = callback(trial)
    except Exception as exc:  # noqa: BLE001 - callback failures are auditable trial outcomes.
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="pipeline",
            exception_type=type(exc).__name__,
            message=str(exc),
        )
    if type(outcome) is not PipelineOutcome:
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type="TypeError",
            message="whole-pipeline callback must return PipelineOutcome",
        )
    try:
        details = _strict_json_copy(
            outcome.details,
            path="pipeline outcome details",
        )
    except (TypeError, ValueError) as exc:
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=type(exc).__name__,
            message=str(exc),
        )
    if type(outcome.trial_id) is not str:
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type="TypeError",
            message="pipeline outcome trial_id must be a native string",
        )
    try:
        statistic = float(outcome.max_statistic)
    except (TypeError, ValueError, OverflowError) as exc:
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=type(exc).__name__,
            message="pipeline max_statistic must be a finite scalar",
        )
    if not np.isfinite(statistic):
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type="NonFiniteStatistic",
            message="pipeline max_statistic must be finite",
        )
    normalized = PipelineOutcome(
        trial_id=outcome.trial_id,
        max_statistic=statistic,
        details=details,
    )
    if outcome.trial_id != trial.trial_id:
        return normalized, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type="StaleTrialOutcome",
            message="pipeline outcome trial_id does not match the fresh request",
        )
    return normalized, None


def _signal_grid(values: ArrayLike, name: str, *, nonnegative: bool) -> FloatArray:
    result = _float_vector(values, name)
    if nonnegative and np.any(result < 0.0):
        raise ValueError(f"{name} must be non-negative")
    if name == "amplitudes" and result.size > 1 and np.any(np.diff(result) <= 0.0):
        raise ValueError("amplitudes must be strictly increasing with no duplicates")
    if name == "phases" and np.unique(result).size != result.size:
        raise ValueError("phases must not contain duplicates")
    return result


def _pipeline_trial_id(
    *,
    plan_id: str,
    kind: TrialKind,
    trial_seed: int,
    replicate_index: int,
    amplitude_index: int | None = None,
    phase_index: int | None = None,
    amplitude: float | None = None,
    phase: float | None = None,
) -> str:
    """Bind a trial ID to its full plan digest and canonical trial descriptor."""

    descriptor = {
        "amplitude": amplitude,
        "amplitude_index": amplitude_index,
        "kind": kind,
        "phase": phase,
        "phase_index": phase_index,
        "plan_id": plan_id,
        "replicate_index": replicate_index,
        "trial_seed": trial_seed,
    }
    return f"{kind}:{plan_id}:{_canonical_sha256(descriptor)}"


def run_adaptive_pipeline_calibration(
    whole_pipeline: WholePipelineCallback,
    recovery_rule: RecoveryRule,
    *,
    null_trials: int,
    amplitudes: ArrayLike,
    phases: ArrayLike,
    replicates_per_cell: int,
    null_seed: int,
    signal_seed: int,
    evidence_threshold: float,
    confidence_level: float,
    interval_method: IntervalMethod,
    pipeline_identity: str,
    recovery_rule_identity: str,
    plan_metadata: Mapping[str, object] | None = None,
    interpolation_policy: InterpolationPolicy = "none",
) -> AdaptivePipelineCalibration:
    """Replay a caller-owned adaptive pipeline for fixed null and signal ensembles.

    The callback is invoked exactly once for every planned null trial and for every Cartesian
    product element of ``amplitudes x phases x replicates_per_cell``.  Requests carry unique,
    deterministic IDs and domain-separated child seeds.  Every ID binds a canonical digest
    of the complete declared plan and the trial's actual values, not merely grid indices.
    ``pipeline_identity`` and ``recovery_rule_identity`` must be frozen content/version
    identities; additional orbital-family or association policy can be bound through strict
    JSON ``plan_metadata``.  Signal recovery requires both
    ``outcome.max_statistic >= evidence_threshold`` and a true caller-supplied recovery rule.
    Callback, stale-outcome, invalid/non-finite-outcome, and recovery-rule failures are all
    recorded; signal failures count as non-recoveries in the planned denominator.  A failed
    null ensemble cannot produce a calibrated p-value.

    This harness validates accounting and callback isolation only.  It does not establish
    that a callback really injected before template iteration zero or replayed every adaptive
    stage, and using it alone does not calibrate any real workflow.
    """

    n_null = _positive_int(null_trials, "null_trials")
    n_replicates = _positive_int(replicates_per_cell, "replicates_per_cell")
    null_master_seed = _seed(null_seed, "null_seed")
    signal_master_seed = _seed(signal_seed, "signal_seed")
    amplitude_grid = _signal_grid(amplitudes, "amplitudes", nonnegative=True)
    phase_grid = _signal_grid(phases, "phases", nonnegative=False)
    threshold = float(evidence_threshold)
    level = float(confidence_level)
    if not np.isfinite(threshold):
        raise ValueError("evidence_threshold must be finite")
    if not np.isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError("confidence_level must lie strictly between zero and one")
    if interval_method != "wilson":
        raise ValueError("the supported interval_method is 'wilson'")
    if interpolation_policy not in ("none", "linear"):
        raise ValueError("interpolation_policy must be 'none' or 'linear'")
    if not callable(whole_pipeline) or not callable(recovery_rule):
        raise TypeError("whole_pipeline and recovery_rule must be callable")

    identities = {
        "pipeline_identity": pipeline_identity,
        "recovery_rule_identity": recovery_rule_identity,
    }
    for name, identity in identities.items():
        if type(identity) is not str:
            raise TypeError(f"{name} must be a string")
        if not identity:
            raise ValueError(f"{name} must not be empty")
    if plan_metadata is not None and not isinstance(plan_metadata, Mapping):
        raise TypeError("plan_metadata must be a mapping when supplied")
    metadata = _strict_json_copy(dict(plan_metadata or {}))
    signal_trial_count = int(amplitude_grid.size * phase_grid.size * n_replicates)
    plan_payload = {
        "amplitudes": amplitude_grid.tolist(),
        "confidence_level": level,
        "evidence_threshold": threshold,
        "harness_plan_schema": 1,
        "interpolation_policy": interpolation_policy,
        "interval_method": interval_method,
        "null_seed": null_master_seed,
        "null_trials": n_null,
        "phases": phase_grid.tolist(),
        "pipeline_identity": pipeline_identity,
        "plan_metadata": metadata,
        "recovery_rule_identity": recovery_rule_identity,
        "replicates_per_cell": n_replicates,
        "seed_derivation": {
            "algorithm": "numpy-seed-sequence-uint64-v1",
            "null_domain": _ADAPTIVE_NULL_SEED_DOMAIN,
            "signal_domain": _ADAPTIVE_SIGNAL_SEED_DOMAIN,
        },
        "signal_seed": signal_master_seed,
        "signal_trials": signal_trial_count,
    }
    plan_id = _canonical_sha256(plan_payload)

    null_seeds = _spawn_seeds(
        null_master_seed,
        n_null,
        domain=_ADAPTIVE_NULL_SEED_DOMAIN,
    )
    signal_seed_values = _spawn_seeds(
        signal_master_seed,
        signal_trial_count,
        domain=_ADAPTIVE_SIGNAL_SEED_DOMAIN,
    )
    if set(null_seeds) & set(signal_seed_values):
        raise RuntimeError("null and signal child-seed domains unexpectedly overlap")

    null_records: list[PipelineTrialRecord] = []
    null_statistics = np.full(n_null, np.nan, dtype=np.float64)
    trial_ids: set[str] = set()
    for index, trial_seed in enumerate(null_seeds):
        trial_id = _pipeline_trial_id(
            plan_id=plan_id,
            kind="null",
            trial_seed=trial_seed,
            replicate_index=index,
        )
        if trial_id in trial_ids:
            raise RuntimeError("trial-ID derivation produced a duplicate")
        trial_ids.add(trial_id)
        trial = PipelineTrial(
            trial_id=trial_id,
            plan_id=plan_id,
            kind="null",
            trial_seed=trial_seed,
            replicate_index=index,
        )
        outcome, failure = _pipeline_invocation(whole_pipeline, trial)
        if failure is None and outcome is not None:
            null_statistics[index] = float(outcome.max_statistic)
        null_records.append(
            PipelineTrialRecord(
                trial=trial,
                outcome=outcome,
                recovered=None,
                failure=failure,
            )
        )

    signal_seeds = iter(signal_seed_values)
    signal_records: list[PipelineTrialRecord] = []
    amplitude_records: list[list[PipelineTrialRecord]] = [[] for _ in range(amplitude_grid.size)]
    for amplitude_index, amplitude in enumerate(amplitude_grid):
        for phase_index, phase in enumerate(phase_grid):
            for replicate_index in range(n_replicates):
                trial_seed = next(signal_seeds)
                trial_id = _pipeline_trial_id(
                    plan_id=plan_id,
                    kind="signal",
                    trial_seed=trial_seed,
                    replicate_index=replicate_index,
                    amplitude_index=amplitude_index,
                    phase_index=phase_index,
                    amplitude=float(amplitude),
                    phase=float(phase),
                )
                if trial_id in trial_ids:
                    raise RuntimeError("trial-ID derivation produced a duplicate")
                trial_ids.add(trial_id)
                trial = PipelineTrial(
                    trial_id=trial_id,
                    plan_id=plan_id,
                    kind="signal",
                    trial_seed=trial_seed,
                    replicate_index=replicate_index,
                    amplitude_index=amplitude_index,
                    phase_index=phase_index,
                    amplitude=float(amplitude),
                    phase=float(phase),
                )
                outcome, failure = _pipeline_invocation(whole_pipeline, trial)
                recovered = False
                if failure is None and outcome is not None:
                    try:
                        # The rule receives its own detached view so it cannot rewrite the
                        # callback evidence retained in the trial record.
                        recovery_outcome = PipelineOutcome(
                            trial_id=outcome.trial_id,
                            max_statistic=outcome.max_statistic,
                            details=_strict_json_copy(
                                outcome.details,
                                path="recovery-rule outcome details",
                            ),
                        )
                        associated = recovery_rule(trial, recovery_outcome)
                        if not isinstance(associated, (bool, np.bool_)):
                            raise TypeError("recovery_rule must return a boolean")
                        recovered = bool(outcome.max_statistic >= threshold and bool(associated))
                    except Exception as exc:  # noqa: BLE001 - rule failures remain in trials.
                        failure = PipelineTrialFailure(
                            trial_id=trial.trial_id,
                            kind=trial.kind,
                            stage="recovery_rule",
                            exception_type=type(exc).__name__,
                            message=str(exc),
                        )
                        recovered = False
                record = PipelineTrialRecord(
                    trial=trial,
                    outcome=outcome,
                    recovered=recovered,
                    failure=failure,
                )
                signal_records.append(record)
                amplitude_records[amplitude_index].append(record)

    completeness_points: list[AmplitudeCompleteness] = []
    for amplitude, records in zip(amplitude_grid, amplitude_records, strict=True):
        planned = len(records)
        recovered_count = sum(record.recovered is True for record in records)
        failed_count = sum(record.failure is not None for record in records)
        completeness_points.append(
            AmplitudeCompleteness(
                amplitude=float(amplitude),
                planned_trials=planned,
                recovered_trials=recovered_count,
                failed_trials=failed_count,
                completeness=recovered_count / planned,
                interval=wilson_interval(
                    recovered_count,
                    planned,
                    confidence_level=level,
                ),
                records=tuple(records),
            )
        )

    null_failures = tuple(record.failure for record in null_records if record.failure is not None)
    signal_failures = tuple(
        record.failure for record in signal_records if record.failure is not None
    )
    null_calibration = PipelineNullCalibration(
        plan_id=plan_id,
        seed=null_master_seed,
        requested_trials=n_null,
        records=tuple(null_records),
        statistics=_readonly_float_array(null_statistics),
        failures=null_failures,
    )
    completeness = DetectionCompleteness(
        plan_id=plan_id,
        seed=signal_master_seed,
        amplitudes=_readonly_float_array(amplitude_grid),
        phases=_readonly_float_array(phase_grid),
        replicates_per_cell=n_replicates,
        evidence_threshold=threshold,
        confidence_level=level,
        interval_method=interval_method,
        interpolation_policy=interpolation_policy,
        points=tuple(completeness_points),
        records=tuple(signal_records),
        failures=signal_failures,
    )
    return AdaptivePipelineCalibration(
        plan_id=plan_id,
        null=null_calibration,
        completeness=completeness,
    )


__all__ = [
    "AdaptivePipelineCalibration",
    "AmplitudeCompleteness",
    "BinomialInterval",
    "DetectionCompleteness",
    "GlobalNullCalibration",
    "IncompleteCalibrationError",
    "InterpolationPolicy",
    "IntervalMethod",
    "NullSimulationFailure",
    "NumericalFitError",
    "PeriodSearchError",
    "PeriodSearchResult",
    "PipelineNullCalibration",
    "PipelineOutcome",
    "PipelineTrial",
    "PipelineTrialFailure",
    "PipelineTrialRecord",
    "RankDeficiencyError",
    "RecoveryRule",
    "TrialKind",
    "WeightedLinearFit",
    "WholePipelineCallback",
    "build_null_design_matrix",
    "build_periodic_design_matrix",
    "calibrate_global_max_statistic",
    "run_adaptive_pipeline_calibration",
    "weighted_sinusoid_search",
    "wilson_interval",
]
