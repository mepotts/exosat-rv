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
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
from statistics import NormalDist
from types import MappingProxyType
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
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DIAGNOSTIC = re.compile(r"diagnostic_sha256:[0-9a-f]{64}\Z")
_DIAGNOSTIC_FALLBACK = hashlib.sha256(b"m38-safe-diagnostic-unavailable-v1").hexdigest()
_NULL_FAILURE_CODES = frozenset({"conditional_null_trial_failure"})
_PIPELINE_FAILURE_CODES = frozenset(
    {
        "pipeline_callback_exception",
        "pipeline_outcome_details_invalid",
        "pipeline_outcome_nonfinite",
        "pipeline_outcome_stale",
        "pipeline_outcome_statistic_type",
        "pipeline_outcome_trial_id_type",
        "pipeline_outcome_type",
        "recovery_rule_exception",
    }
)
_PIPELINE_FAILURE_STAGE = {
    "pipeline_callback_exception": "pipeline",
    "pipeline_outcome_details_invalid": "outcome",
    "pipeline_outcome_nonfinite": "outcome",
    "pipeline_outcome_stale": "outcome",
    "pipeline_outcome_statistic_type": "outcome",
    "pipeline_outcome_trial_id_type": "outcome",
    "pipeline_outcome_type": "outcome",
    "recovery_rule_exception": "recovery_rule",
}
_NUMPY_INTEGER_TYPES = frozenset(
    np.dtype(name).type
    for name in (
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
    )
)
_NUMPY_FLOAT_TYPES = frozenset(
    np.dtype(name).type for name in ("float16", "float32", "float64", "longdouble")
)
_NUMPY_REAL_TYPES = _NUMPY_INTEGER_TYPES | _NUMPY_FLOAT_TYPES


class PeriodSearchError(ValueError):
    """Base class for deterministic period-search validation and fit failures."""


class RankDeficiencyError(PeriodSearchError):
    """Raised when a declared null or periodic design is not full column rank."""


class NumericalFitError(PeriodSearchError):
    """Raised when weighted least squares produces a non-finite/inconsistent result."""


class IncompleteCalibrationError(RuntimeError):
    """Raised when a failed null trial makes a calibrated probability unavailable."""


def _readonly_float_array(
    values: ArrayLike,
    name: str = "array",
    *,
    allow_nan: bool = False,
) -> FloatArray:
    result = np.array(
        _strict_real_array(values, name, allow_nan=allow_nan),
        dtype=np.float64,
        copy=True,
        order="C",
    )
    # A normal owning ndarray can be made writable again with ``setflags``.  Rebuild from
    # immutable bytes so public evidence arrays cannot be re-enabled and modified in place.
    return np.frombuffer(result.tobytes(order="C"), dtype=np.float64).reshape(result.shape)


def _readonly_int_array(values: ArrayLike, name: str = "array") -> IntArray:
    result = np.array(_strict_int_array(values, name), dtype=np.int64, copy=True, order="C")
    return np.frombuffer(result.tobytes(order="C"), dtype=np.int64).reshape(result.shape)


def _float_vector(values: ArrayLike, name: str, *, nonempty: bool = True) -> FloatArray:
    result = _strict_real_array(values, name)
    if result.ndim != 1:
        raise PeriodSearchError(f"{name} must be one-dimensional")
    if nonempty and result.size == 0:
        raise PeriodSearchError(f"{name} must not be empty")
    if not np.all(np.isfinite(result)):
        raise PeriodSearchError(f"{name} must contain only finite values")
    return result


def _positive_int(value: int, name: str) -> int:
    if type(value) is not int and type(value) not in _NUMPY_INTEGER_TYPES:
        raise ValueError(f"{name} must be a positive integer")
    if int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _nonnegative_int(value: int, name: str) -> int:
    if type(value) is not int and type(value) not in _NUMPY_INTEGER_TYPES:
        raise ValueError(f"{name} must be a non-negative integer")
    if int(value) < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def _seed(value: int, name: str) -> int:
    return _nonnegative_int(value, name)


def _native_string(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise TypeError(f"{name} must be a non-empty native string without edge space")
    return value


def _sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _finite_real(value: object, name: str) -> float:
    if type(value) not in {int, float} and type(value) not in _NUMPY_REAL_TYPES:
        raise TypeError(f"{name} must be a native or NumPy real scalar")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _strict_real_array(
    values: ArrayLike,
    name: str,
    *,
    allow_nan: bool = False,
) -> FloatArray:
    try:
        # Object conversion preserves each caller-supplied scalar's actual type.  A normal
        # numeric coercion here would turn custom ``float`` subclasses and booleans into
        # accepted float64 values before the elementwise trust-boundary check.
        raw = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise PeriodSearchError(f"{name} must be a numeric array") from exc
    normalized: list[float] = []
    for index, item in enumerate(raw.flat):
        item_name = f"{name}[{index}]"
        if type(item) not in {int, float} and type(item) not in _NUMPY_REAL_TYPES:
            raise TypeError(f"{item_name} must be a native or NumPy real scalar")
        number = float(item)
        if not np.isfinite(number) and not (allow_nan and np.isnan(number)):
            raise ValueError(f"{item_name} must be finite")
        normalized.append(number)
    return np.asarray(normalized, dtype=np.float64).reshape(raw.shape)


def _strict_int_array(values: ArrayLike, name: str) -> IntArray:
    try:
        raw = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise PeriodSearchError(f"{name} must be an integer array") from exc
    normalized: list[int] = []
    for index, item in enumerate(raw.flat):
        if type(item) is not int and type(item) not in _NUMPY_INTEGER_TYPES:
            raise TypeError(f"{name}[{index}] must be a native or NumPy integer scalar")
        normalized.append(int(item))
    return np.asarray(normalized, dtype=np.int64).reshape(raw.shape)


def _safe_diagnostic_sha256(exc: BaseException | None, *, failure_code: str) -> str:
    """Hash bounded primitive diagnostics without invoking exception rendering hooks."""

    try:
        digest = hashlib.sha256()
        digest.update(failure_code.encode("ascii", errors="strict")[:128])
        if exc is not None:
            exc_type = type(exc)
            for value in (
                getattr(exc_type, "__module__", None),
                getattr(exc_type, "__qualname__", None),
            ):
                if type(value) is str:
                    digest.update(value[:128].encode("utf-8", errors="surrogatepass"))
            args = BaseException.args.__get__(exc)
            if type(args) is tuple:
                for argument in args[:8]:
                    if type(argument) is str:
                        digest.update(argument[:512].encode("utf-8", errors="surrogatepass"))
                    elif type(argument) is bytes:
                        digest.update(argument[:512])
                    elif argument is None or type(argument) in {bool, int, float}:
                        digest.update(
                            json.dumps(
                                argument,
                                allow_nan=False,
                                separators=(",", ":"),
                            ).encode("ascii")
                        )
                    else:
                        argument_type = type(argument)
                        for value in (
                            getattr(argument_type, "__module__", None),
                            getattr(argument_type, "__qualname__", None),
                        ):
                            if type(value) is str:
                                digest.update(value[:128].encode("utf-8", errors="surrogatepass"))
        return digest.hexdigest()
    except BaseException:  # noqa: BLE001 - diagnostic fallback must itself be fail-safe.
        return _DIAGNOSTIC_FALLBACK


def _diagnostic_message(exc: BaseException | None, *, failure_code: str) -> str:
    return f"diagnostic_sha256:{_safe_diagnostic_sha256(exc, failure_code=failure_code)}"


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
        if type(item) is int or type(item) in _NUMPY_INTEGER_TYPES:
            return int(item)
        if type(item) is float or type(item) in _NUMPY_FLOAT_TYPES:
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


def _strict_json_snapshot(value: object, *, path: str) -> object:
    return _freeze_json(_strict_json_copy(value, path=path))


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
    value = _finite_real(rcond, "rcond")
    if value <= 0.0:
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
    if type(include_intercept) not in {bool, np.bool_}:
        raise PeriodSearchError("include_intercept must be boolean")

    if nuisance_regressors is None:
        nuisance = np.empty((n_rows, 0), dtype=np.float64)
    else:
        nuisance = _strict_real_array(nuisance_regressors, "nuisance_regressors")
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
    period_value = _finite_real(period, "period")
    if period_value <= 0.0:
        raise PeriodSearchError("period must be finite and positive")
    null_design = _strict_real_array(null_design_matrix, "null_design_matrix")
    if null_design.ndim != 2 or null_design.shape[0] != time_values.size:
        raise PeriodSearchError(
            "null_design_matrix must be two-dimensional with one row per observation"
        )
    if not np.all(np.isfinite(null_design)):
        raise PeriodSearchError("null_design_matrix must contain only finite values")

    origin = (
        float(np.min(time_values))
        if reference_time is None
        else _finite_real(reference_time, "reference_time")
    )
    phase = (2.0 * np.pi / period_value) * (time_values - origin)
    if not np.all(np.isfinite(phase)):
        raise PeriodSearchError("periodic phase calculation produced non-finite values")
    design = np.column_stack((null_design, np.sin(phase), np.cos(phase)))
    if not np.all(np.isfinite(design)):
        raise PeriodSearchError("periodic design matrix contains non-finite values")
    return _readonly_float_array(design)


@dataclass(frozen=True, slots=True)
class WeightedLinearFit:
    """One replay-validated, full-rank weighted linear fit."""

    design_matrix: FloatArray
    observed_values: FloatArray
    uncertainties: FloatArray
    rcond: float | None
    coefficients: FloatArray
    fitted_values: FloatArray
    residuals: FloatArray
    chi2: float
    rank: int
    dof: int

    def __post_init__(self) -> None:
        design = _readonly_float_array(self.design_matrix, "fit design_matrix")
        observed = _readonly_float_array(self.observed_values, "fit observed_values")
        uncertainties = _readonly_float_array(self.uncertainties, "fit uncertainties")
        coefficients = _readonly_float_array(self.coefficients, "fit coefficients")
        fitted = _readonly_float_array(self.fitted_values, "fit fitted_values")
        residuals = _readonly_float_array(self.residuals, "fit residuals")
        rcond = _validate_rcond(self.rcond)
        if design.ndim != 2:
            raise ValueError("fit design_matrix must be two-dimensional")
        if observed.ndim != 1 or observed.size == 0:
            raise ValueError("fit observed_values must be a non-empty vector")
        if uncertainties.ndim != 1 or uncertainties.shape != observed.shape:
            raise ValueError("fit uncertainties must match observed_values")
        if np.any(uncertainties <= 0.0):
            raise ValueError("fit uncertainties must be strictly positive")
        if design.shape[0] != observed.size:
            raise ValueError("fit design_matrix must have one row per observed value")
        if coefficients.ndim != 1:
            raise ValueError("fit coefficients must be one-dimensional")
        if coefficients.size != design.shape[1]:
            raise ValueError("fit coefficients must match the design columns")
        if fitted.ndim != 1 or fitted.size == 0:
            raise ValueError("fit fitted_values must be a non-empty vector")
        if fitted.shape != observed.shape:
            raise ValueError("fit fitted_values must match observed_values")
        if residuals.ndim != 1 or residuals.shape != fitted.shape:
            raise ValueError("fit residuals must match fitted_values")
        chi2 = _finite_real(self.chi2, "fit chi2")
        if chi2 < 0.0:
            raise ValueError("fit chi2 must be non-negative")
        rank = _nonnegative_int(self.rank, "fit rank")
        dof = _positive_int(self.dof, "fit dof")
        if rank != coefficients.size:
            raise ValueError("full-rank fit rank must equal its coefficient count")
        if dof != fitted.size - rank:
            raise ValueError("fit dof does not match observations minus rank")

        if design.shape[1] == 0:
            expected_coefficients = np.empty(0, dtype=np.float64)
            expected_rank = 0
        else:
            try:
                with np.errstate(over="raise", divide="raise", invalid="raise"):
                    weighted_design = design / uncertainties[:, np.newaxis]
                    weighted_values = observed / uncertainties
                expected_coefficients, _, expected_rank, _ = np.linalg.lstsq(
                    weighted_design,
                    weighted_values,
                    rcond=rcond,
                )
            except (FloatingPointError, np.linalg.LinAlgError) as exc:
                raise NumericalFitError("retained weighted fit replay failed") from exc
        if int(expected_rank) != design.shape[1]:
            raise RankDeficiencyError("retained weighted fit design is rank deficient")
        expected_fitted = design @ expected_coefficients
        expected_residuals = observed - expected_fitted
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            weighted_residuals = expected_residuals / uncertainties
            expected_chi2 = float(np.dot(weighted_residuals, weighted_residuals))
        expected_dof = observed.size - int(expected_rank)
        replayed = (
            (coefficients, expected_coefficients, "coefficients"),
            (fitted, expected_fitted, "fitted_values"),
            (residuals, expected_residuals, "residuals"),
        )
        for supplied, expected, name in replayed:
            if not np.array_equal(supplied, expected):
                raise ValueError(f"fit {name} does not replay from retained evidence")
        if chi2 != expected_chi2:
            raise ValueError("fit chi2 does not replay from retained evidence")
        if rank != int(expected_rank) or dof != expected_dof:
            raise ValueError("fit rank/dof do not replay from retained evidence")

        object.__setattr__(self, "design_matrix", design)
        object.__setattr__(self, "observed_values", observed)
        object.__setattr__(self, "uncertainties", uncertainties)
        object.__setattr__(self, "rcond", rcond)
        object.__setattr__(self, "coefficients", coefficients)
        object.__setattr__(self, "fitted_values", fitted)
        object.__setattr__(self, "residuals", residuals)
        object.__setattr__(self, "chi2", chi2)
        object.__setattr__(self, "rank", rank)
        object.__setattr__(self, "dof", dof)

    @property
    def identity(self) -> str:
        """Canonical identity of the complete immutable fit result."""

        return _canonical_sha256(
            {
                "chi2": self.chi2,
                "coefficients": self.coefficients.tolist(),
                "design_matrix": self.design_matrix.tolist(),
                "dof": self.dof,
                "fitted_values": self.fitted_values.tolist(),
                "observed_values": self.observed_values.tolist(),
                "rank": self.rank,
                "rcond": self.rcond,
                "residuals": self.residuals.tolist(),
                "schema": 2,
                "uncertainties": self.uncertainties.tolist(),
            }
        )


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
    rcond: float | None
    null_design_matrix: FloatArray
    null_fit: WeightedLinearFit
    periodic_coefficients: FloatArray
    chi2: FloatArray
    delta_chi2: FloatArray
    amplitudes: FloatArray
    ranks: IntArray
    dof: IntArray

    def __post_init__(self) -> None:
        times = _readonly_float_array(self.times, "search times")
        values = _readonly_float_array(self.values, "search values")
        uncertainties = _readonly_float_array(self.uncertainties, "search uncertainties")
        periods = _readonly_float_array(self.periods, "search periods")
        if any(array.ndim != 1 or array.size == 0 for array in (times, values, uncertainties)):
            raise ValueError("search observations must be non-empty vectors")
        if values.shape != times.shape or uncertainties.shape != times.shape:
            raise ValueError("search observation vectors must have identical lengths")
        if np.any(uncertainties <= 0.0):
            raise ValueError("search uncertainties must be strictly positive")
        if periods.ndim != 1 or periods.size == 0:
            raise ValueError("search periods must be a non-empty vector")
        if np.any(periods <= 0.0) or (periods.size > 1 and np.any(np.diff(periods) <= 0.0)):
            raise ValueError("search periods must be positive and strictly increasing")
        reference_time = _finite_real(self.reference_time, "search reference_time")
        rcond = _validate_rcond(self.rcond)
        null_design = _readonly_float_array(self.null_design_matrix, "null design matrix")
        if null_design.ndim != 2 or null_design.shape[0] != times.size:
            raise ValueError("null design matrix must have one row per observation")
        if times.size <= null_design.shape[1] + 2:
            raise ValueError("periodic design must have positive residual degrees of freedom")
        if type(self.null_fit) is not WeightedLinearFit:
            raise TypeError("null_fit must be an exact WeightedLinearFit")

        coefficient_count = null_design.shape[1] + 2
        periodic_coefficients = _readonly_float_array(
            self.periodic_coefficients,
            "periodic coefficients",
        )
        chi2 = _readonly_float_array(self.chi2, "period chi2")
        delta_chi2 = _readonly_float_array(self.delta_chi2, "period delta_chi2")
        amplitudes = _readonly_float_array(self.amplitudes, "period amplitudes")
        ranks = _readonly_int_array(self.ranks, "period ranks")
        dof = _readonly_int_array(self.dof, "period dof")
        expected_vector_shape = periods.shape
        if periodic_coefficients.shape != (periods.size, coefficient_count):
            raise ValueError("periodic coefficient landscape has the wrong shape")
        if any(
            array.shape != expected_vector_shape
            for array in (chi2, delta_chi2, amplitudes, ranks, dof)
        ):
            raise ValueError("period landscape vectors must match the period grid")

        expected_null = _weighted_fit(
            null_design,
            values,
            uncertainties,
            rcond=rcond,
            model_label="replayed null model",
        )
        if self.null_fit.identity != expected_null.identity:
            raise ValueError("null fit does not replay from the frozen design and observations")

        replayed_coefficients = np.empty_like(periodic_coefficients)
        replayed_chi2 = np.empty_like(chi2)
        replayed_amplitudes = np.empty_like(amplitudes)
        replayed_ranks = np.empty_like(ranks)
        replayed_dof = np.empty_like(dof)
        for index, period in enumerate(periods):
            design = build_periodic_design_matrix(
                times,
                period,
                null_design,
                reference_time=reference_time,
            )
            fit = _weighted_fit(
                design,
                values,
                uncertainties,
                rcond=rcond,
                model_label=f"replayed periodic model at grid index {index}",
            )
            replayed_coefficients[index] = fit.coefficients
            replayed_chi2[index] = fit.chi2
            replayed_amplitudes[index] = np.hypot(fit.coefficients[-2], fit.coefficients[-1])
            replayed_ranks[index] = fit.rank
            replayed_dof[index] = fit.dof
        replayed_delta = np.maximum(expected_null.chi2 - replayed_chi2, 0.0)
        replayed = (
            (periodic_coefficients, replayed_coefficients, "periodic coefficients"),
            (chi2, replayed_chi2, "period chi2"),
            (delta_chi2, replayed_delta, "period delta_chi2"),
            (amplitudes, replayed_amplitudes, "period amplitudes"),
            (ranks, replayed_ranks, "period ranks"),
            (dof, replayed_dof, "period dof"),
        )
        for supplied, expected, name in replayed:
            if not np.array_equal(supplied, expected):
                raise ValueError(f"{name} does not replay from the frozen search design")

        object.__setattr__(self, "times", times)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "uncertainties", uncertainties)
        object.__setattr__(self, "periods", periods)
        object.__setattr__(self, "reference_time", reference_time)
        object.__setattr__(self, "rcond", rcond)
        object.__setattr__(self, "null_design_matrix", null_design)
        object.__setattr__(self, "null_fit", expected_null)
        object.__setattr__(self, "periodic_coefficients", periodic_coefficients)
        object.__setattr__(self, "chi2", chi2)
        object.__setattr__(self, "delta_chi2", delta_chi2)
        object.__setattr__(self, "amplitudes", amplitudes)
        object.__setattr__(self, "ranks", ranks)
        object.__setattr__(self, "dof", dof)

    @property
    def design_identity(self) -> str:
        """Canonical identity of the frozen search design and observations' weights."""

        return _canonical_sha256(
            {
                "null_design_matrix": self.null_design_matrix.tolist(),
                "periods": self.periods.tolist(),
                "rcond": self.rcond,
                "reference_time": self.reference_time,
                "schema": 1,
                "times": self.times.tolist(),
                "uncertainties": self.uncertainties.tolist(),
            }
        )

    @property
    def result_identity(self) -> str:
        """Canonical identity of the replay-validated complete search result."""

        return _canonical_sha256(
            {
                "amplitudes": self.amplitudes.tolist(),
                "chi2": self.chi2.tolist(),
                "delta_chi2": self.delta_chi2.tolist(),
                "design_identity": self.design_identity,
                "dof": self.dof.tolist(),
                "null_fit_identity": self.null_fit.identity,
                "periodic_coefficients": self.periodic_coefficients.tolist(),
                "ranks": self.ranks.tolist(),
                "schema": 1,
                "values": self.values.tolist(),
            }
        )

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

        if type(index) is not int and type(index) not in _NUMPY_INTEGER_TYPES:
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
        design_matrix=_readonly_float_array(design),
        observed_values=_readonly_float_array(values),
        uncertainties=_readonly_float_array(uncertainties),
        rcond=rcond,
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

    origin = (
        float(np.min(time_values))
        if reference_time is None
        else _finite_real(reference_time, "reference_time")
    )
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
        rcond=rcond_value,
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_index", _nonnegative_int(self.trial_index, "trial_index"))
        object.__setattr__(self, "trial_seed", _seed(self.trial_seed, "trial_seed"))
        object.__setattr__(
            self, "exception_type", _native_string(self.exception_type, "exception_type")
        )
        if self.exception_type not in _NULL_FAILURE_CODES:
            raise ValueError("unsupported conditional-null failure code")
        if type(self.message) is not str or _DIAGNOSTIC.fullmatch(self.message) is None:
            raise ValueError("failure message must be a safe diagnostic SHA-256")


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

    def __post_init__(self) -> None:
        if type(self.observed_search) is not PeriodSearchResult:
            raise TypeError("observed_search must be an exact PeriodSearchResult")
        observed_search = PeriodSearchResult(
            times=self.observed_search.times,
            values=self.observed_search.values,
            uncertainties=self.observed_search.uncertainties,
            periods=self.observed_search.periods,
            reference_time=self.observed_search.reference_time,
            rcond=self.observed_search.rcond,
            null_design_matrix=self.observed_search.null_design_matrix,
            null_fit=self.observed_search.null_fit,
            periodic_coefficients=self.observed_search.periodic_coefficients,
            chi2=self.observed_search.chi2,
            delta_chi2=self.observed_search.delta_chi2,
            amplitudes=self.observed_search.amplitudes,
            ranks=self.observed_search.ranks,
            dof=self.observed_search.dof,
        )
        master_seed = _seed(self.seed, "seed")
        requested = _positive_int(self.requested_simulations, "requested_simulations")
        if type(self.simulation_seeds) is not tuple or len(self.simulation_seeds) != requested:
            raise ValueError("simulation_seeds must cover every requested simulation")
        seeds = tuple(_seed(value, "simulation seed") for value in self.simulation_seeds)
        expected_seeds = _spawn_seeds(
            master_seed,
            requested,
            domain=_CONDITIONAL_NULL_SEED_DOMAIN,
        )
        if seeds != expected_seeds:
            raise ValueError("simulation_seeds do not match the declared seed plan")
        if type(self.failures) is not tuple or any(
            type(failure) is not NullSimulationFailure for failure in self.failures
        ):
            raise TypeError("failures must be a tuple of NullSimulationFailure values")
        failure_indices = tuple(failure.trial_index for failure in self.failures)
        if len(set(failure_indices)) != len(failure_indices):
            raise ValueError("null simulation failure indices must be unique")
        for failure in self.failures:
            if failure.trial_index >= requested:
                raise ValueError("null simulation failure index is outside the plan")
            if failure.trial_seed != seeds[failure.trial_index]:
                raise ValueError("null simulation failure seed does not match the plan")
        statistics = _readonly_float_array(
            self.simulation_statistics,
            "simulation_statistics",
            allow_nan=True,
        )
        if statistics.ndim != 1 or statistics.size != requested:
            raise ValueError("simulation_statistics must cover every requested simulation")
        failure_set = set(failure_indices)
        for index, statistic in enumerate(statistics):
            if index in failure_set:
                if not np.isnan(statistic):
                    raise ValueError("failed null simulations must retain a NaN statistic")
            elif not np.isfinite(statistic):
                raise ValueError("successful null simulations must retain a finite statistic")
            else:
                rng = np.random.default_rng(seeds[index])
                simulated_values = observed_search.null_fit.fitted_values + rng.normal(
                    loc=0.0,
                    scale=observed_search.uncertainties,
                )
                replayed = weighted_sinusoid_search(
                    observed_search.times,
                    simulated_values,
                    observed_search.uncertainties,
                    observed_search.periods,
                    nuisance_regressors=(
                        observed_search.null_design_matrix
                        if observed_search.null_design_matrix.shape[1]
                        else None
                    ),
                    include_intercept=False,
                    reference_time=observed_search.reference_time,
                    rcond=observed_search.rcond,
                )
                if statistic != replayed.max_statistic:
                    raise ValueError(
                        "successful null statistic does not replay from retained seed evidence"
                    )

        if self.failures:
            if self.exceedance_count is not None or self.p_value is not None:
                raise ValueError("an incomplete null ensemble cannot carry a calibrated p-value")
        else:
            expected_exceedances = int(
                np.count_nonzero(statistics >= observed_search.max_statistic)
            )
            if type(self.exceedance_count) is not int or (
                self.exceedance_count != expected_exceedances
            ):
                raise ValueError("exceedance_count does not match the retained statistics")
            expected_p = (expected_exceedances + 1.0) / (requested + 1.0)
            if type(self.p_value) is not float or self.p_value != expected_p:
                raise ValueError("p_value does not match the complete plus-one calibration")

        object.__setattr__(self, "observed_search", observed_search)
        object.__setattr__(self, "seed", master_seed)
        object.__setattr__(self, "requested_simulations", requested)
        object.__setattr__(self, "simulation_seeds", seeds)
        object.__setattr__(self, "simulation_statistics", statistics)

    @property
    def complete(self) -> bool:
        """Whether all requested simulations completed and the p-value is valid."""

        return not self.failures and self.p_value is not None

    @property
    def result_identity(self) -> str:
        """Canonical identity of the replay-validated complete calibration evidence."""

        return _canonical_sha256(
            {
                "exceedance_count": self.exceedance_count,
                "failures": [
                    {
                        "exception_type": failure.exception_type,
                        "message": failure.message,
                        "trial_index": failure.trial_index,
                        "trial_seed": failure.trial_seed,
                    }
                    for failure in self.failures
                ],
                "observed_result_identity": self.observed_search.result_identity,
                "p_value": self.p_value,
                "requested_simulations": self.requested_simulations,
                "schema": 1,
                "seed": self.seed,
                "simulation_seeds": list(self.simulation_seeds),
                "simulation_statistics": [
                    None if np.isnan(value) else float(value)
                    for value in self.simulation_statistics
                ],
            }
        )

    def verify_integrity(self) -> GlobalNullCalibration:
        """Reconstruct and replay every retained successful seed statistic."""

        return GlobalNullCalibration(
            observed_search=self.observed_search,
            seed=self.seed,
            requested_simulations=self.requested_simulations,
            simulation_seeds=self.simulation_seeds,
            simulation_statistics=self.simulation_statistics,
            failures=self.failures,
            exceedance_count=self.exceedance_count,
            p_value=self.p_value,
        )


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
            failure_code = "conditional_null_trial_failure"
            failures.append(
                NullSimulationFailure(
                    trial_index=index,
                    trial_seed=trial_seed,
                    exception_type=failure_code,
                    message=_diagnostic_message(exc, failure_code=failure_code),
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
        simulation_statistics=_readonly_float_array(
            statistics,
            "simulation_statistics",
            allow_nan=True,
        ),
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
    signal_indices: tuple[int, ...] | None = None
    signal_parameters: tuple[tuple[str, float], ...] | None = None

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        if type(self.kind) is not str or self.kind not in {"null", "signal"}:
            raise TypeError("trial kind must be exactly 'null' or 'signal'")
        trial_seed = _seed(self.trial_seed, "trial_seed")
        replicate_index = _nonnegative_int(self.replicate_index, "replicate_index")
        amplitude_index = self.amplitude_index
        phase_index = self.phase_index
        amplitude = self.amplitude
        phase = self.phase
        signal_indices = self.signal_indices
        signal_parameters = self.signal_parameters

        if self.kind == "null":
            if any(
                value is not None
                for value in (
                    amplitude_index,
                    phase_index,
                    amplitude,
                    phase,
                    signal_indices,
                    signal_parameters,
                )
            ):
                raise ValueError("null trials cannot carry signal coordinates")
        elif signal_indices is None and signal_parameters is None:
            amplitude_index = _nonnegative_int(amplitude_index, "amplitude_index")
            phase_index = _nonnegative_int(phase_index, "phase_index")
            amplitude = _finite_real(amplitude, "amplitude")
            phase = _finite_real(phase, "phase")
        else:
            if any(value is not None for value in (amplitude_index, phase_index, amplitude, phase)):
                raise ValueError("multi-axis signal trials cannot carry legacy coordinates")
            if type(signal_indices) is not tuple or not signal_indices:
                raise TypeError("signal_indices must be a non-empty tuple")
            signal_indices = tuple(
                _nonnegative_int(index, "signal index") for index in signal_indices
            )
            if type(signal_parameters) is not tuple or not signal_parameters:
                raise TypeError("signal_parameters must be a non-empty tuple")
            normalized_parameters: list[tuple[str, float]] = []
            for item in signal_parameters:
                if type(item) is not tuple or len(item) != 2:
                    raise TypeError("signal parameters must be (name, value) tuples")
                normalized_parameters.append(
                    (
                        _native_string(item[0], "signal parameter name"),
                        _finite_real(item[1], "signal parameter value"),
                    )
                )
            signal_parameters = tuple(normalized_parameters)
            if len(signal_indices) != len(signal_parameters):
                raise ValueError("signal indices and parameters must have the same length")
            names = tuple(name for name, _ in signal_parameters)
            if len(set(names)) != len(names):
                raise ValueError("signal parameter names must be unique")

        expected_id = _pipeline_trial_id(
            plan_id=plan_id,
            kind=self.kind,
            trial_seed=trial_seed,
            replicate_index=replicate_index,
            amplitude_index=amplitude_index,
            phase_index=phase_index,
            amplitude=amplitude,
            phase=phase,
            signal_indices=signal_indices,
            signal_parameters=signal_parameters,
        )
        if type(self.trial_id) is not str or self.trial_id != expected_id:
            raise ValueError("trial_id does not bind the complete trial descriptor")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "trial_seed", trial_seed)
        object.__setattr__(self, "replicate_index", replicate_index)
        object.__setattr__(self, "amplitude_index", amplitude_index)
        object.__setattr__(self, "phase_index", phase_index)
        object.__setattr__(self, "amplitude", amplitude)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "signal_indices", signal_indices)
        object.__setattr__(self, "signal_parameters", signal_parameters)


@dataclass(frozen=True, slots=True)
class SignalAxis:
    """One explicit numerical axis in a caller-declared signal ensemble."""

    name: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if type(self.name) is not str:
            raise TypeError("signal-axis name must be a native string")
        if not self.name or self.name.strip() != self.name:
            raise ValueError("signal-axis name must be non-empty with no surrounding whitespace")
        if type(self.values) is not tuple:
            raise TypeError("signal-axis values must be a tuple")
        if not self.values:
            raise ValueError("signal-axis values must not be empty")
        normalized: list[float] = []
        for index, item in enumerate(self.values):
            normalized.append(_finite_real(item, f"signal-axis value {index}"))
        if len(set(normalized)) != len(normalized):
            raise ValueError("signal-axis values must not contain duplicates")
        object.__setattr__(self, "values", tuple(normalized))


@dataclass(frozen=True, slots=True)
class SignalTrialPlan:
    """Hashable Cartesian signal plan with no implicit orbital defaults."""

    axes: tuple[SignalAxis, ...]
    replicates_per_cell: int

    def __post_init__(self) -> None:
        if type(self.axes) is not tuple or not self.axes:
            raise TypeError("signal-plan axes must be a non-empty tuple")
        if any(type(axis) is not SignalAxis for axis in self.axes):
            raise TypeError("every signal-plan axis must be a SignalAxis")
        names = tuple(axis.name for axis in self.axes)
        if len(set(names)) != len(names):
            raise ValueError("signal-plan axis names must be unique")
        object.__setattr__(
            self,
            "replicates_per_cell",
            _positive_int(self.replicates_per_cell, "replicates_per_cell"),
        )

    @property
    def cell_count(self) -> int:
        """Number of Cartesian parameter cells, excluding replicates."""

        result = 1
        for axis in self.axes:
            result *= len(axis.values)
        return result

    @property
    def trial_count(self) -> int:
        """Total number of planned signal trials."""

        return self.cell_count * self.replicates_per_cell

    @property
    def identity(self) -> str:
        """Canonical content identity of the signal-only plan."""

        return _canonical_sha256(
            {
                "axes": [{"name": axis.name, "values": list(axis.values)} for axis in self.axes],
                "replicates_per_cell": self.replicates_per_cell,
                "schema": 1,
            }
        )


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", _native_string(self.trial_id, "failure trial_id"))
        if type(self.kind) is not str or self.kind not in {"null", "signal"}:
            raise TypeError("failure kind must be exactly 'null' or 'signal'")
        if type(self.stage) is not str or self.stage not in {
            "pipeline",
            "outcome",
            "recovery_rule",
        }:
            raise TypeError("failure stage is not supported")
        object.__setattr__(
            self, "exception_type", _native_string(self.exception_type, "exception_type")
        )
        if self.exception_type not in _PIPELINE_FAILURE_CODES:
            raise ValueError("unsupported pipeline failure code")
        if _PIPELINE_FAILURE_STAGE[self.exception_type] != self.stage:
            raise ValueError("pipeline failure code does not match its stage")
        if type(self.message) is not str or _DIAGNOSTIC.fullmatch(self.message) is None:
            raise ValueError("failure message must be a safe diagnostic SHA-256")


@dataclass(frozen=True, slots=True)
class PipelineTrialRecord:
    """One planned trial, including outcome, decision, and any failure."""

    trial: PipelineTrial
    outcome: PipelineOutcome | None
    recovered: bool | None
    failure: PipelineTrialFailure | None

    def __post_init__(self) -> None:
        if type(self.trial) is not PipelineTrial:
            raise TypeError("trial must be an exact PipelineTrial")
        if self.outcome is not None:
            if type(self.outcome) is not PipelineOutcome:
                raise TypeError("outcome must be an exact PipelineOutcome when present")
            normalized_outcome = PipelineOutcome(
                trial_id=_native_string(self.outcome.trial_id, "outcome trial_id"),
                max_statistic=_finite_real(
                    self.outcome.max_statistic,
                    "pipeline max_statistic",
                ),
                details=_strict_json_snapshot(
                    _thaw_json(self.outcome.details),
                    path="pipeline outcome details",
                ),
            )
            object.__setattr__(self, "outcome", normalized_outcome)
        if self.failure is not None and type(self.failure) is not PipelineTrialFailure:
            raise TypeError("failure must be an exact PipelineTrialFailure when present")
        if self.trial.kind == "null":
            if self.recovered is not None:
                raise ValueError("null records cannot carry a recovery decision")
        elif type(self.recovered) is not bool:
            raise TypeError("signal records must carry a native boolean recovery decision")
        elif self.failure is not None and self.recovered:
            raise ValueError("failed signal records must be unrecovered")
        if self.failure is None:
            if self.outcome is None or self.outcome.trial_id != self.trial.trial_id:
                raise ValueError("successful records require a fresh matching outcome")
        else:
            if self.failure.trial_id != self.trial.trial_id or self.failure.kind != self.trial.kind:
                raise ValueError("failure identity does not match its planned trial")
            if self.failure.stage == "pipeline" and self.outcome is not None:
                raise ValueError("pipeline invocation failures cannot carry an outcome")
            if self.failure.stage == "recovery_rule" and self.outcome is None:
                raise ValueError("recovery-rule failures must retain the pipeline outcome")


def _validate_recovery_threshold(
    records: tuple[PipelineTrialRecord, ...],
    evidence_threshold: float,
) -> None:
    """Reject a claimed recovery that is not a successful above-threshold outcome."""

    for record in records:
        if record.recovered is not True:
            continue
        if (
            record.failure is not None
            or record.outcome is None
            or record.outcome.trial_id != record.trial.trial_id
        ):
            raise ValueError("recovered trials require a successful matching outcome")
        if record.outcome.max_statistic < evidence_threshold:
            raise ValueError("recovered trials must meet the declared evidence threshold")


@dataclass(frozen=True, slots=True)
class PipelineNullCalibration:
    """Full-pipeline null max statistics with no successful-subset fallback."""

    plan_id: str
    seed: int
    requested_trials: int
    records: tuple[PipelineTrialRecord, ...]
    statistics: FloatArray
    failures: tuple[PipelineTrialFailure, ...]

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        master_seed = _seed(self.seed, "seed")
        requested = _positive_int(self.requested_trials, "requested_trials")
        if (
            type(self.records) is not tuple
            or len(self.records) != requested
            or any(type(record) is not PipelineTrialRecord for record in self.records)
        ):
            raise ValueError("null records must cover every requested trial")
        if any(
            record.trial.plan_id != plan_id
            or record.trial.kind != "null"
            or record.trial.replicate_index != index
            for index, record in enumerate(self.records)
        ):
            raise ValueError("null records do not match the declared plan and order")
        if len({record.trial.trial_id for record in self.records}) != requested:
            raise ValueError("null records must have unique trial IDs")
        expected_seeds = _spawn_seeds(
            master_seed,
            requested,
            domain=_ADAPTIVE_NULL_SEED_DOMAIN,
        )
        if tuple(record.trial.trial_seed for record in self.records) != expected_seeds:
            raise ValueError("null trial seeds do not match the declared seed plan")
        statistics = _readonly_float_array(
            self.statistics,
            "pipeline null statistics",
            allow_nan=True,
        )
        if statistics.ndim != 1 or statistics.size != requested:
            raise ValueError("null statistics must cover every requested trial")
        derived_failures = tuple(
            record.failure for record in self.records if record.failure is not None
        )
        if type(self.failures) is not tuple or self.failures != derived_failures:
            raise ValueError("null failure list does not match retained records")
        for index, (record, statistic) in enumerate(zip(self.records, statistics, strict=True)):
            if record.failure is None:
                if record.outcome is None or not np.isfinite(statistic):
                    raise ValueError("successful null records require a finite statistic")
                if statistic != record.outcome.max_statistic:
                    raise ValueError("null statistic does not match its retained outcome")
            elif not np.isnan(statistic):
                raise ValueError(f"failed null trial {index} must retain a NaN statistic")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "seed", master_seed)
        object.__setattr__(self, "requested_trials", requested)
        object.__setattr__(self, "statistics", statistics)

    @property
    def complete(self) -> bool:
        """Whether every planned null invocation returned a valid outcome."""

        return not self.failures and len(self.records) == self.requested_trials

    def plus_one_p_value(self, observed_max_statistic: float) -> float:
        """Return the global plus-one empirical p-value for a supplied statistic.

        An incomplete ensemble raises instead of silently dropping failed trials.
        """

        observed = _finite_real(observed_max_statistic, "observed_max_statistic")
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

    def __post_init__(self) -> None:
        lower = _finite_real(self.lower, "interval lower bound")
        upper = _finite_real(self.upper, "interval upper bound")
        level = _finite_real(self.confidence_level, "interval confidence_level")
        if not 0.0 <= lower <= upper <= 1.0:
            raise ValueError("binomial interval bounds must lie in the unit interval")
        if not 0.0 < level < 1.0:
            raise ValueError("interval confidence_level must lie strictly between zero and one")
        if type(self.method) is not str or self.method != "wilson":
            raise ValueError("binomial interval method must be exactly 'wilson'")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "confidence_level", level)


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

    def __post_init__(self) -> None:
        amplitude = _finite_real(self.amplitude, "amplitude")
        planned = _positive_int(self.planned_trials, "planned_trials")
        recovered = _nonnegative_int(self.recovered_trials, "recovered_trials")
        failed = _nonnegative_int(self.failed_trials, "failed_trials")
        if recovered > planned or failed > planned:
            raise ValueError("recovered and failed counts cannot exceed planned trials")
        if (
            type(self.records) is not tuple
            or len(self.records) != planned
            or any(type(record) is not PipelineTrialRecord for record in self.records)
        ):
            raise ValueError("amplitude records must cover every planned trial")
        if any(
            record.trial.kind != "signal" or record.trial.amplitude != amplitude
            for record in self.records
        ):
            raise ValueError("amplitude records do not match the declared signal cell")
        if len({record.trial.trial_id for record in self.records}) != planned:
            raise ValueError("amplitude records must have unique trial IDs")
        derived_recovered = sum(record.recovered is True for record in self.records)
        derived_failed = sum(record.failure is not None for record in self.records)
        if recovered != derived_recovered or failed != derived_failed:
            raise ValueError("amplitude counts do not match retained trial records")
        completeness = recovered / planned
        if _finite_real(self.completeness, "completeness") != completeness:
            raise ValueError("amplitude completeness does not match the planned denominator")
        if type(self.interval) is not BinomialInterval:
            raise TypeError("interval must be an exact BinomialInterval")
        expected_interval = wilson_interval(
            recovered,
            planned,
            confidence_level=self.interval.confidence_level,
        )
        if self.interval != expected_interval:
            raise ValueError("amplitude interval does not match the retained counts")
        object.__setattr__(self, "amplitude", amplitude)
        object.__setattr__(self, "planned_trials", planned)
        object.__setattr__(self, "recovered_trials", recovered)
        object.__setattr__(self, "failed_trials", failed)
        object.__setattr__(self, "completeness", completeness)


@dataclass(frozen=True, slots=True)
class SignalCellCompleteness:
    """Completeness and failure accounting for one multi-axis parameter cell."""

    indices: tuple[int, ...]
    parameters: tuple[tuple[str, float], ...]
    planned_trials: int
    recovered_trials: int
    failed_trials: int
    completeness: float
    interval: BinomialInterval
    records: tuple[PipelineTrialRecord, ...]

    def __post_init__(self) -> None:
        if type(self.indices) is not tuple or not self.indices:
            raise TypeError("cell indices must be a non-empty tuple")
        indices = tuple(_nonnegative_int(index, "cell index") for index in self.indices)
        if type(self.parameters) is not tuple or not self.parameters:
            raise TypeError("cell parameters must be a non-empty tuple")
        parameters: list[tuple[str, float]] = []
        for item in self.parameters:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("cell parameters must be (name, value) tuples")
            parameters.append(
                (
                    _native_string(item[0], "cell parameter name"),
                    _finite_real(item[1], "cell value"),
                )
            )
        normalized_parameters = tuple(parameters)
        if len(indices) != len(normalized_parameters):
            raise ValueError("cell indices and parameters must have the same length")
        planned = _positive_int(self.planned_trials, "planned_trials")
        recovered = _nonnegative_int(self.recovered_trials, "recovered_trials")
        failed = _nonnegative_int(self.failed_trials, "failed_trials")
        if recovered > planned or failed > planned:
            raise ValueError("recovered and failed counts cannot exceed planned trials")
        if (
            type(self.records) is not tuple
            or len(self.records) != planned
            or any(type(record) is not PipelineTrialRecord for record in self.records)
        ):
            raise ValueError("cell records must cover every planned trial")
        if any(
            record.trial.kind != "signal"
            or record.trial.signal_indices != indices
            or record.trial.signal_parameters != normalized_parameters
            for record in self.records
        ):
            raise ValueError("cell records do not match the declared signal coordinates")
        if len({record.trial.trial_id for record in self.records}) != planned:
            raise ValueError("cell records must have unique trial IDs")
        derived_recovered = sum(record.recovered is True for record in self.records)
        derived_failed = sum(record.failure is not None for record in self.records)
        if recovered != derived_recovered or failed != derived_failed:
            raise ValueError("cell counts do not match retained trial records")
        completeness = recovered / planned
        if _finite_real(self.completeness, "completeness") != completeness:
            raise ValueError("cell completeness does not match the planned denominator")
        if type(self.interval) is not BinomialInterval:
            raise TypeError("interval must be an exact BinomialInterval")
        expected_interval = wilson_interval(
            recovered,
            planned,
            confidence_level=self.interval.confidence_level,
        )
        if self.interval != expected_interval:
            raise ValueError("cell interval does not match the retained counts")
        object.__setattr__(self, "indices", indices)
        object.__setattr__(self, "parameters", normalized_parameters)
        object.__setattr__(self, "planned_trials", planned)
        object.__setattr__(self, "recovered_trials", recovered)
        object.__setattr__(self, "failed_trials", failed)
        object.__setattr__(self, "completeness", completeness)


@dataclass(frozen=True, slots=True)
class MultiAxisDetectionCompleteness:
    """Complete caller-declared multi-axis signal ensemble.

    The object reports every Cartesian cell separately and deliberately provides no
    interpolation, sensitivity bound, winner, or preferred scientific design.
    """

    plan_id: str
    seed: int
    signal_plan: SignalTrialPlan
    evidence_threshold: float
    confidence_level: float
    interval_method: IntervalMethod
    cells: tuple[SignalCellCompleteness, ...]
    records: tuple[PipelineTrialRecord, ...]
    failures: tuple[PipelineTrialFailure, ...]

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        master_seed = _seed(self.seed, "seed")
        if type(self.signal_plan) is not SignalTrialPlan:
            raise TypeError("signal_plan must be an exact SignalTrialPlan")
        threshold = _finite_real(self.evidence_threshold, "evidence_threshold")
        level = _finite_real(self.confidence_level, "confidence_level")
        if not 0.0 < level < 1.0:
            raise ValueError("confidence_level must lie strictly between zero and one")
        if type(self.interval_method) is not str or self.interval_method != "wilson":
            raise ValueError("interval_method must be exactly 'wilson'")
        if (
            type(self.records) is not tuple
            or (len(self.records) != self.signal_plan.trial_count)
            or any(type(record) is not PipelineTrialRecord for record in self.records)
        ):
            raise ValueError("signal records must cover the complete declared plan")
        if len({record.trial.trial_id for record in self.records}) != len(self.records):
            raise ValueError("signal records must have unique trial IDs")
        expected_seeds = _spawn_seeds(
            master_seed,
            self.signal_plan.trial_count,
            domain=_ADAPTIVE_SIGNAL_SEED_DOMAIN,
        )
        if tuple(record.trial.trial_seed for record in self.records) != expected_seeds:
            raise ValueError("signal trial seeds do not match the declared seed plan")
        expected_descriptors: list[tuple[tuple[int, ...], tuple[tuple[str, float], ...], int]] = []
        index_ranges = tuple(range(len(axis.values)) for axis in self.signal_plan.axes)
        for indices in product(*index_ranges):
            parameters = tuple(
                (axis.name, axis.values[index])
                for axis, index in zip(self.signal_plan.axes, indices, strict=True)
            )
            for replicate_index in range(self.signal_plan.replicates_per_cell):
                expected_descriptors.append((indices, parameters, replicate_index))
        for record, descriptor in zip(self.records, expected_descriptors, strict=True):
            indices, parameters, replicate_index = descriptor
            if (
                record.trial.plan_id != plan_id
                or record.trial.kind != "signal"
                or record.trial.signal_indices != indices
                or record.trial.signal_parameters != parameters
                or record.trial.replicate_index != replicate_index
            ):
                raise ValueError("signal record does not match its declared Cartesian cell")
        _validate_recovery_threshold(self.records, threshold)
        derived_failures = tuple(
            record.failure for record in self.records if record.failure is not None
        )
        if type(self.failures) is not tuple or self.failures != derived_failures:
            raise ValueError("signal failure list does not match retained records")
        if (
            type(self.cells) is not tuple
            or len(self.cells) != self.signal_plan.cell_count
            or any(type(cell) is not SignalCellCompleteness for cell in self.cells)
        ):
            raise ValueError("signal cells must cover the complete Cartesian plan")
        offset = 0
        for cell, indices in zip(self.cells, product(*index_ranges), strict=True):
            parameters = tuple(
                (axis.name, axis.values[index])
                for axis, index in zip(self.signal_plan.axes, indices, strict=True)
            )
            cell_records = self.records[offset : offset + self.signal_plan.replicates_per_cell]
            offset += self.signal_plan.replicates_per_cell
            if (
                cell.indices != indices
                or cell.parameters != parameters
                or cell.records != cell_records
                or cell.interval.confidence_level != level
            ):
                raise ValueError("signal-cell summary does not match retained trial records")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "seed", master_seed)
        object.__setattr__(self, "evidence_threshold", threshold)
        object.__setattr__(self, "confidence_level", level)

    @property
    def complete(self) -> bool:
        """Whether every planned signal invocation and recovery rule completed."""

        return not self.failures and len(self.records) == self.signal_plan.trial_count

    def cell_at(self, **parameters: float) -> SignalCellCompleteness:
        """Return an exactly evaluated cell; implicit interpolation is forbidden."""

        expected_names = tuple(axis.name for axis in self.signal_plan.axes)
        if set(parameters) != set(expected_names) or len(parameters) != len(expected_names):
            raise ValueError("parameters must supply every declared signal axis exactly once")
        values: list[float] = []
        for name in expected_names:
            values.append(_finite_real(parameters[name], f"parameter {name!r}"))
        requested = tuple(zip(expected_names, values, strict=True))
        for cell in self.cells:
            if cell.parameters == requested:
                return cell
        raise ValueError("parameter cell was not evaluated; interpolation is not available")


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

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        master_seed = _seed(self.seed, "seed")
        amplitudes = _readonly_float_array(self.amplitudes)
        phases = _readonly_float_array(self.phases)
        if amplitudes.ndim != 1 or amplitudes.size == 0 or not np.all(np.isfinite(amplitudes)):
            raise ValueError("amplitudes must be a non-empty finite vector")
        if phases.ndim != 1 or phases.size == 0 or not np.all(np.isfinite(phases)):
            raise ValueError("phases must be a non-empty finite vector")
        if np.any(amplitudes < 0.0) or (amplitudes.size > 1 and np.any(np.diff(amplitudes) <= 0.0)):
            raise ValueError("amplitudes must be non-negative and strictly increasing")
        if np.unique(phases).size != phases.size:
            raise ValueError("phases must not contain duplicates")
        replicates = _positive_int(self.replicates_per_cell, "replicates_per_cell")
        threshold = _finite_real(self.evidence_threshold, "evidence_threshold")
        level = _finite_real(self.confidence_level, "confidence_level")
        if not 0.0 < level < 1.0:
            raise ValueError("confidence_level must lie strictly between zero and one")
        if type(self.interval_method) is not str or self.interval_method != "wilson":
            raise ValueError("interval_method must be exactly 'wilson'")
        if type(self.interpolation_policy) is not str or self.interpolation_policy not in {
            "none",
            "linear",
        }:
            raise ValueError("interpolation_policy must be exactly 'none' or 'linear'")
        expected_count = int(amplitudes.size * phases.size * replicates)
        if (
            type(self.records) is not tuple
            or len(self.records) != expected_count
            or any(type(record) is not PipelineTrialRecord for record in self.records)
        ):
            raise ValueError("signal records must cover every fixed-grid trial")
        if len({record.trial.trial_id for record in self.records}) != expected_count:
            raise ValueError("signal records must have unique trial IDs")
        expected_seeds = _spawn_seeds(
            master_seed,
            expected_count,
            domain=_ADAPTIVE_SIGNAL_SEED_DOMAIN,
        )
        if tuple(record.trial.trial_seed for record in self.records) != expected_seeds:
            raise ValueError("signal trial seeds do not match the declared seed plan")
        expected_index = 0
        grouped: list[tuple[PipelineTrialRecord, ...]] = []
        for amplitude_index, amplitude in enumerate(amplitudes):
            amplitude_records: list[PipelineTrialRecord] = []
            for phase_index, phase in enumerate(phases):
                for replicate_index in range(replicates):
                    record = self.records[expected_index]
                    expected_index += 1
                    if (
                        record.trial.plan_id != plan_id
                        or record.trial.kind != "signal"
                        or record.trial.amplitude_index != amplitude_index
                        or record.trial.phase_index != phase_index
                        or record.trial.replicate_index != replicate_index
                        or record.trial.amplitude != float(amplitude)
                        or record.trial.phase != float(phase)
                    ):
                        raise ValueError("signal record does not match its fixed-grid cell")
                    amplitude_records.append(record)
            grouped.append(tuple(amplitude_records))
        _validate_recovery_threshold(self.records, threshold)
        derived_failures = tuple(
            record.failure for record in self.records if record.failure is not None
        )
        if type(self.failures) is not tuple or self.failures != derived_failures:
            raise ValueError("signal failure list does not match retained records")
        if (
            type(self.points) is not tuple
            or len(self.points) != amplitudes.size
            or any(type(point) is not AmplitudeCompleteness for point in self.points)
        ):
            raise ValueError("amplitude summaries must cover the complete grid")
        for point, amplitude, records in zip(self.points, amplitudes, grouped, strict=True):
            if (
                point.amplitude != float(amplitude)
                or point.records != records
                or point.interval.confidence_level != level
            ):
                raise ValueError("amplitude summary does not match retained signal records")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "seed", master_seed)
        object.__setattr__(self, "amplitudes", amplitudes)
        object.__setattr__(self, "phases", phases)
        object.__setattr__(self, "replicates_per_cell", replicates)
        object.__setattr__(self, "evidence_threshold", threshold)
        object.__setattr__(self, "confidence_level", level)

    @property
    def complete(self) -> bool:
        """Whether every signal callback and recovery decision completed."""

        return not self.failures

    def completeness_at(self, amplitude: float) -> float:
        """Return a grid value, or a linearly interpolated value only if predeclared.

        Linear interpolation applies only to the point estimate.  No interval or sensitivity
        bound is inferred between grid points.
        """

        value = _finite_real(amplitude, "amplitude")
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

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        if (
            type(self.null) is not PipelineNullCalibration
            or type(self.completeness) is not DetectionCompleteness
        ):
            raise TypeError("adaptive calibration requires exact null and completeness reports")
        if self.null.plan_id != plan_id or self.completeness.plan_id != plan_id:
            raise ValueError("adaptive calibration components do not share the plan ID")
        object.__setattr__(self, "plan_id", plan_id)

    @property
    def complete(self) -> bool:
        """Whether both planned ensembles completed without failures."""

        return self.null.complete and self.completeness.complete

    def false_alarm_probability_at_threshold(self) -> float:
        """Plus-one null tail probability at the frozen evidence threshold."""

        return self.null.plus_one_p_value(self.completeness.evidence_threshold)


@dataclass(frozen=True, slots=True)
class AdaptivePipelineGridCalibration:
    """Full-pipeline null and caller-declared multi-axis signal calibration."""

    plan_id: str
    null: PipelineNullCalibration
    completeness: MultiAxisDetectionCompleteness

    def __post_init__(self) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        if (
            type(self.null) is not PipelineNullCalibration
            or type(self.completeness) is not MultiAxisDetectionCompleteness
        ):
            raise TypeError("grid calibration requires exact null and completeness reports")
        if self.null.plan_id != plan_id or self.completeness.plan_id != plan_id:
            raise ValueError("grid calibration components do not share the plan ID")
        object.__setattr__(self, "plan_id", plan_id)

    @property
    def complete(self) -> bool:
        """Whether both ensembles completed without a failed planned trial."""

        return self.null.complete and self.completeness.complete

    def false_alarm_probability_at_threshold(self) -> float:
        """Plus-one null tail probability at the declared evidence threshold."""

        return self.null.plus_one_p_value(self.completeness.evidence_threshold)


def wilson_interval(
    successes: int,
    trials: int,
    *,
    confidence_level: float,
) -> BinomialInterval:
    """Compute a two-sided Wilson score interval for a binomial proportion."""

    n_trials = _positive_int(trials, "trials")
    if type(successes) is not int and type(successes) not in _NUMPY_INTEGER_TYPES:
        raise TypeError("successes must be an integer")
    n_successes = int(successes)
    if n_successes < 0 or n_successes > n_trials:
        raise ValueError("successes must lie between zero and trials")
    level = _finite_real(confidence_level, "confidence_level")
    if not 0.0 < level < 1.0:
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
        failure_code = "pipeline_callback_exception"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="pipeline",
            exception_type=failure_code,
            message=_diagnostic_message(exc, failure_code=failure_code),
        )
    if type(outcome) is not PipelineOutcome:
        failure_code = "pipeline_outcome_type"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(None, failure_code=failure_code),
        )
    try:
        details = _strict_json_copy(
            outcome.details,
            path="pipeline outcome details",
        )
    except (TypeError, ValueError) as exc:
        failure_code = "pipeline_outcome_details_invalid"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(exc, failure_code=failure_code),
        )
    if type(outcome.trial_id) is not str:
        failure_code = "pipeline_outcome_trial_id_type"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(None, failure_code=failure_code),
        )
    if (
        type(outcome.max_statistic) not in {int, float}
        and type(outcome.max_statistic) not in _NUMPY_REAL_TYPES
    ):
        failure_code = "pipeline_outcome_statistic_type"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(None, failure_code=failure_code),
        )
    statistic = float(outcome.max_statistic)
    if not np.isfinite(statistic):
        failure_code = "pipeline_outcome_nonfinite"
        return None, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(None, failure_code=failure_code),
        )
    normalized = PipelineOutcome(
        trial_id=outcome.trial_id,
        max_statistic=statistic,
        details=details,
    )
    if outcome.trial_id != trial.trial_id:
        failure_code = "pipeline_outcome_stale"
        return normalized, PipelineTrialFailure(
            trial_id=trial.trial_id,
            kind=trial.kind,
            stage="outcome",
            exception_type=failure_code,
            message=_diagnostic_message(None, failure_code=failure_code),
        )
    return normalized, None


def _signal_grid(values: ArrayLike, name: str, *, nonnegative: bool) -> FloatArray:
    result = _readonly_float_array(_float_vector(values, name), name)
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
    signal_indices: tuple[int, ...] | None = None,
    signal_parameters: tuple[tuple[str, float], ...] | None = None,
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
        "signal_indices": list(signal_indices) if signal_indices is not None else None,
        "signal_parameters": (
            [[name, value] for name, value in signal_parameters]
            if signal_parameters is not None
            else None
        ),
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
    ``pipeline_identity`` and ``recovery_rule_identity`` must be SHA-256 identities of the exact
    executed artifacts; additional orbital-family or association policy can be bound through strict
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
    threshold = _finite_real(evidence_threshold, "evidence_threshold")
    level = _finite_real(confidence_level, "confidence_level")
    if not 0.0 < level < 1.0:
        raise ValueError("confidence_level must lie strictly between zero and one")
    if interval_method != "wilson":
        raise ValueError("the supported interval_method is 'wilson'")
    if interpolation_policy not in ("none", "linear"):
        raise ValueError("interpolation_policy must be 'none' or 'linear'")
    if not callable(whole_pipeline) or not callable(recovery_rule):
        raise TypeError("whole_pipeline and recovery_rule must be callable")

    pipeline_digest = _sha256(pipeline_identity, "pipeline_identity")
    recovery_digest = _sha256(recovery_rule_identity, "recovery_rule_identity")
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
        "pipeline_identity": pipeline_digest,
        "plan_metadata": metadata,
        "recovery_rule_identity": recovery_digest,
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
                                _thaw_json(outcome.details),
                                path="recovery-rule outcome details",
                            ),
                        )
                        associated = recovery_rule(trial, recovery_outcome)
                        if type(associated) not in {bool, np.bool_}:
                            raise TypeError("recovery_rule must return a boolean")
                        recovered = bool(outcome.max_statistic >= threshold and bool(associated))
                    except Exception as exc:  # noqa: BLE001 - rule failures remain in trials.
                        failure_code = "recovery_rule_exception"
                        failure = PipelineTrialFailure(
                            trial_id=trial.trial_id,
                            kind=trial.kind,
                            stage="recovery_rule",
                            exception_type=failure_code,
                            message=_diagnostic_message(exc, failure_code=failure_code),
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
        statistics=_readonly_float_array(
            null_statistics,
            "pipeline null statistics",
            allow_nan=True,
        ),
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


def run_adaptive_pipeline_grid_calibration(
    whole_pipeline: WholePipelineCallback,
    recovery_rule: RecoveryRule,
    *,
    null_trials: int,
    signal_plan: SignalTrialPlan,
    null_seed: int,
    signal_seed: int,
    evidence_threshold: float,
    confidence_level: float,
    interval_method: IntervalMethod,
    pipeline_identity: str,
    recovery_rule_identity: str,
    plan_metadata: Mapping[str, object] | None = None,
) -> AdaptivePipelineGridCalibration:
    """Replay a complete adaptive pipeline over an explicit multi-axis signal plan.

    Every axis, value, replicate, seed, identity, threshold, and metadata field is bound into
    the plan digest.  The function reports every Cartesian signal cell separately and retains
    every failed trial in its planned denominator.  It deliberately performs no interpolation,
    threshold optimization, grid refinement, candidate selection, or sensitivity-bound
    inference.  Scientific axes such as period, eccentricity, amplitude, phase, and nuisance
    parameters exist only when the caller explicitly supplies them.

    As with run_adaptive_pipeline_calibration, callback contents remain independently
    auditable: this harness proves complete invocation and accounting, not that the callback
    actually rebuilt templates or injected at the required upstream representation.
    """

    n_null = _positive_int(null_trials, "null_trials")
    if type(signal_plan) is not SignalTrialPlan:
        raise TypeError("signal_plan must be a SignalTrialPlan")
    null_master_seed = _seed(null_seed, "null_seed")
    signal_master_seed = _seed(signal_seed, "signal_seed")
    threshold = _finite_real(evidence_threshold, "evidence_threshold")
    level = _finite_real(confidence_level, "confidence_level")
    if not 0.0 < level < 1.0:
        raise ValueError("confidence_level must lie strictly between zero and one")
    if interval_method != "wilson":
        raise ValueError("the supported interval_method is 'wilson'")
    if not callable(whole_pipeline) or not callable(recovery_rule):
        raise TypeError("whole_pipeline and recovery_rule must be callable")
    pipeline_digest = _sha256(pipeline_identity, "pipeline_identity")
    recovery_digest = _sha256(recovery_rule_identity, "recovery_rule_identity")
    if plan_metadata is not None and not isinstance(plan_metadata, Mapping):
        raise TypeError("plan_metadata must be a mapping when supplied")
    metadata = _strict_json_copy(dict(plan_metadata or {}))

    plan_payload = {
        "confidence_level": level,
        "evidence_threshold": threshold,
        "harness_plan_schema": 2,
        "interval_method": interval_method,
        "null_seed": null_master_seed,
        "null_trials": n_null,
        "pipeline_identity": pipeline_digest,
        "plan_metadata": metadata,
        "recovery_rule_identity": recovery_digest,
        "seed_derivation": {
            "algorithm": "numpy-seed-sequence-uint64-v1",
            "null_domain": _ADAPTIVE_NULL_SEED_DOMAIN,
            "signal_domain": _ADAPTIVE_SIGNAL_SEED_DOMAIN,
        },
        "signal_plan": {
            "axes": [{"name": axis.name, "values": list(axis.values)} for axis in signal_plan.axes],
            "identity": signal_plan.identity,
            "replicates_per_cell": signal_plan.replicates_per_cell,
            "trial_count": signal_plan.trial_count,
        },
        "signal_seed": signal_master_seed,
    }
    plan_id = _canonical_sha256(plan_payload)

    null_seeds = _spawn_seeds(
        null_master_seed,
        n_null,
        domain=_ADAPTIVE_NULL_SEED_DOMAIN,
    )
    signal_seeds = _spawn_seeds(
        signal_master_seed,
        signal_plan.trial_count,
        domain=_ADAPTIVE_SIGNAL_SEED_DOMAIN,
    )
    if set(null_seeds) & set(signal_seeds):
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
            null_statistics[index] = outcome.max_statistic
        null_records.append(
            PipelineTrialRecord(
                trial=trial,
                outcome=outcome,
                recovered=None,
                failure=failure,
            )
        )

    seed_iter = iter(signal_seeds)
    signal_records: list[PipelineTrialRecord] = []
    cell_results: list[SignalCellCompleteness] = []
    indexed_axes = tuple(tuple(enumerate(axis.values)) for axis in signal_plan.axes)
    for cell in product(*indexed_axes):
        indices = tuple(index for index, _ in cell)
        parameters = tuple(
            (axis.name, float(indexed_value[1]))
            for axis, indexed_value in zip(signal_plan.axes, cell, strict=True)
        )
        cell_records: list[PipelineTrialRecord] = []
        for replicate_index in range(signal_plan.replicates_per_cell):
            trial_seed = next(seed_iter)
            trial_id = _pipeline_trial_id(
                plan_id=plan_id,
                kind="signal",
                trial_seed=trial_seed,
                replicate_index=replicate_index,
                signal_indices=indices,
                signal_parameters=parameters,
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
                signal_indices=indices,
                signal_parameters=parameters,
            )
            outcome, failure = _pipeline_invocation(whole_pipeline, trial)
            recovered = False
            if failure is None and outcome is not None:
                try:
                    recovery_outcome = PipelineOutcome(
                        trial_id=outcome.trial_id,
                        max_statistic=outcome.max_statistic,
                        details=_strict_json_copy(
                            _thaw_json(outcome.details),
                            path="recovery-rule outcome details",
                        ),
                    )
                    associated = recovery_rule(trial, recovery_outcome)
                    if type(associated) not in {bool, np.bool_}:
                        raise TypeError("recovery_rule must return a boolean")
                    recovered = bool(outcome.max_statistic >= threshold and bool(associated))
                except Exception as exc:  # noqa: BLE001 - every rule failure is recorded.
                    failure_code = "recovery_rule_exception"
                    failure = PipelineTrialFailure(
                        trial_id=trial.trial_id,
                        kind=trial.kind,
                        stage="recovery_rule",
                        exception_type=failure_code,
                        message=_diagnostic_message(exc, failure_code=failure_code),
                    )
                    recovered = False
            record = PipelineTrialRecord(
                trial=trial,
                outcome=outcome,
                recovered=recovered,
                failure=failure,
            )
            signal_records.append(record)
            cell_records.append(record)

        recovered_count = sum(record.recovered is True for record in cell_records)
        failed_count = sum(record.failure is not None for record in cell_records)
        planned_count = len(cell_records)
        cell_results.append(
            SignalCellCompleteness(
                indices=indices,
                parameters=parameters,
                planned_trials=planned_count,
                recovered_trials=recovered_count,
                failed_trials=failed_count,
                completeness=recovered_count / planned_count,
                interval=wilson_interval(
                    recovered_count,
                    planned_count,
                    confidence_level=level,
                ),
                records=tuple(cell_records),
            )
        )

    try:
        next(seed_iter)
    except StopIteration:
        pass
    else:  # pragma: no cover - guarded by the exact Cartesian trial count.
        raise RuntimeError("signal seed accounting left an unused planned seed")

    null_failures = tuple(record.failure for record in null_records if record.failure is not None)
    signal_failures = tuple(
        record.failure for record in signal_records if record.failure is not None
    )
    null_calibration = PipelineNullCalibration(
        plan_id=plan_id,
        seed=null_master_seed,
        requested_trials=n_null,
        records=tuple(null_records),
        statistics=_readonly_float_array(
            null_statistics,
            "pipeline null statistics",
            allow_nan=True,
        ),
        failures=null_failures,
    )
    completeness = MultiAxisDetectionCompleteness(
        plan_id=plan_id,
        seed=signal_master_seed,
        signal_plan=signal_plan,
        evidence_threshold=threshold,
        confidence_level=level,
        interval_method=interval_method,
        cells=tuple(cell_results),
        records=tuple(signal_records),
        failures=signal_failures,
    )
    return AdaptivePipelineGridCalibration(
        plan_id=plan_id,
        null=null_calibration,
        completeness=completeness,
    )


__all__ = [
    "AdaptivePipelineCalibration",
    "AdaptivePipelineGridCalibration",
    "AmplitudeCompleteness",
    "BinomialInterval",
    "DetectionCompleteness",
    "GlobalNullCalibration",
    "IncompleteCalibrationError",
    "InterpolationPolicy",
    "IntervalMethod",
    "MultiAxisDetectionCompleteness",
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
    "SignalAxis",
    "SignalCellCompleteness",
    "SignalTrialPlan",
    "TrialKind",
    "WeightedLinearFit",
    "WholePipelineCallback",
    "build_null_design_matrix",
    "build_periodic_design_matrix",
    "calibrate_global_max_statistic",
    "run_adaptive_pipeline_calibration",
    "run_adaptive_pipeline_grid_calibration",
    "weighted_sinusoid_search",
    "wilson_interval",
]
