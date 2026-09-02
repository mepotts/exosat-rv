"""Target-free wiring contracts for cross-fitted iterative template chains.

This module is generic infrastructure.  It contains no instrument configuration, control
identity, order choice, convergence limit, velocity design, or target loader.  Callers provide
all of those decisions explicitly.  A chain can use either one disjoint train/evaluation split
or exact leave-one-epoch-out folds.  In both cases an evaluation epoch is structurally absent
from the exposures supplied to its template builder.

Velocity injection is applied to decomposed stellar components before an adapter session is
created and therefore before template iteration zero.  Every injection plan, arm, and fold gets
a distinct session object and token.  Cache artifacts are deliberately rejected: a later
production cache would need a separately audited, exact content-binding contract and must never
weaken the fresh-chain requirement for injections.

The adapter protocol is only a wiring boundary.  A distinct Python facade does not prove that
an adapter performed a cold rebuild or avoided shared internal state.  This module is not an OS
sandbox and cannot make an untrusted adapter blind.  Process isolation and audited adapter I/O
remain external requirements.  The companion ``synthetic_controls`` module supplies a small
toy adapter for exercising this boundary without real spectra or scientific claims.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, Protocol, TypeAlias

import numpy as np
from numpy.typing import ArrayLike, NDArray

from exosat_rv.m38.convergence import (
    ConvergencePolicy,
    ConvergenceResult,
    ConvergenceUpdate,
    RVChangeMetric,
    TemplateChangeMetric,
    evaluate_convergence,
)
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.spectral import (
    DecomposedSpectralExposure,
    check_injection_invariants,
    convolve_fixed_lsf,
    inject_stellar_velocity,
)

FloatArray: TypeAlias = NDArray[np.float64]
BoolArray: TypeAlias = NDArray[np.bool_]
FoldStrategy: TypeAlias = Literal["disjoint", "leave_one_out"]
TemplateOrderMode: TypeAlias = Literal["common", "arm_specific"]
RVRole: TypeAlias = Literal["training", "evaluation"]


class TemplateChainError(RuntimeError):
    """Base class for template-chain failures."""


class TemplateChainDataError(TemplateChainError, ValueError):
    """Raised when an identity, shape, mask, or lineage contract fails closed."""


class TemplateChainExecutionError(TemplateChainError):
    """Raised when an adapter violates the declared execution contract."""


def _native_label(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise TemplateChainDataError(f"{name} must be a non-empty native string")
    return value


def _labels(
    values: Sequence[str],
    name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TemplateChainDataError(f"{name} must be a sequence of labels")
    result = tuple(values)
    if not result and not allow_empty:
        raise TemplateChainDataError(f"{name} must not be empty")
    for value in result:
        _native_label(value, name)
    if len(set(result)) != len(result):
        raise TemplateChainDataError(f"{name} must not contain duplicates")
    return result


def _digest(value: str, name: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise TemplateChainDataError(f"{name} must be a lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise TemplateChainDataError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _native_index(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TemplateChainDataError(f"{name} must be a non-negative native integer")
    return value


def _finite_native_float(value: float, name: str) -> float:
    if type(value) is not float or not np.isfinite(value):
        raise TemplateChainDataError(f"{name} must be a finite native float")
    return value


def _canonical_zero(value: float) -> float:
    """Collapse both IEEE-754 zero spellings onto one physical identity."""
    return 0.0 if value == 0.0 else value


class WorkflowFreshnessRegistry:
    """Caller-owned, workflow-lifetime evidence of Python session freshness.

    One registry must be retained for the complete workflow that may launch multiple
    ensembles.  Reservations are deliberately not rolled back after an execution failure: a
    nonce, session object, or token that participated in an attempted chain is spent.  Strong
    references prevent Python object-ID reuse from weakening the object-identity check.

    This in-memory registry is wiring evidence only.  It cannot attest to process isolation, a
    cold adapter rebuild, or the absence of shared state behind an adapter facade.
    """

    __slots__ = (
        "_lock",
        "_session_objects",
        "_session_tokens",
        "_used_ensemble_nonces",
    )

    def __init__(self) -> None:
        self._lock = Lock()
        self._session_objects: list[object] = []
        self._session_tokens: set[str] = set()
        self._used_ensemble_nonces: set[str] = set()

    def reserve_ensemble_nonce(self, ensemble_nonce: str) -> str:
        """Atomically spend one caller-supplied ensemble nonce digest."""
        nonce = _digest(ensemble_nonce, "ensemble_nonce")
        with self._lock:
            if nonce in self._used_ensemble_nonces:
                raise TemplateChainExecutionError(
                    "ensemble nonce was already used in this workflow freshness registry"
                )
            self._used_ensemble_nonces.add(nonce)
        return nonce

    def reserve_session(self, session: object, session_token: str) -> str:
        """Atomically reject an object or token observed anywhere in this workflow."""
        token = _native_label(session_token, "session_token")
        with self._lock:
            if any(session is prior for prior in self._session_objects):
                raise TemplateChainExecutionError(
                    "adapter factory reused a session object across the workflow"
                )
            if token in self._session_tokens:
                raise TemplateChainExecutionError(
                    "adapter factory reused a session token across the workflow"
                )
            self._session_objects.append(session)
            self._session_tokens.add(token)
        return token


def _immutable_array(value: NDArray) -> NDArray:
    contiguous = np.ascontiguousarray(value)
    frozen = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )
    if frozen.flags.writeable:
        raise TemplateChainDataError("failed to create immutable array storage")
    return frozen


def _float_vector(value: ArrayLike, name: str) -> FloatArray:
    try:
        array = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise TemplateChainDataError(f"{name} must be a numeric vector") from exc
    if array.ndim != 1 or array.size == 0:
        raise TemplateChainDataError(f"{name} must be a non-empty numeric vector")
    return _immutable_array(array)


def _float_matrix(value: ArrayLike, name: str) -> FloatArray:
    try:
        array = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise TemplateChainDataError(f"{name} must be a rectangular numeric matrix") from exc
    if array.ndim != 2 or 0 in array.shape:
        raise TemplateChainDataError(f"{name} must be a non-empty numeric matrix")
    return _immutable_array(array)


def _bool_matrix(value: ArrayLike, name: str, shape: tuple[int, int]) -> BoolArray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TemplateChainDataError(f"{name} must be a boolean matrix with shape {shape}") from exc
    if array.dtype.kind != "b" or array.shape != shape:
        raise TemplateChainDataError(f"{name} must be a boolean matrix with shape {shape}")
    return _immutable_array(np.array(array, dtype=np.bool_, copy=True, order="C"))


def _array_identity(array: NDArray) -> dict[str, object]:
    contiguous = np.ascontiguousarray(array)
    return {
        "dtype": contiguous.dtype.str,
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
    }


def _policy_identity(policy: ConvergencePolicy) -> str:
    if not isinstance(policy, ConvergencePolicy):
        raise TypeError("convergence_policy must be a ConvergencePolicy")
    return canonical_sha256(
        {
            "d_rv_limit_hex": policy.d_rv_limit.hex(),
            "d_template_limit_hex": policy.d_template_limit.hex(),
            "k_max": policy.k_max,
            "q_conv": policy.q_conv,
            "template_aggregate": policy.template_aggregate,
        }
    )


@dataclass(frozen=True, slots=True)
class FrozenSpectralExposure:
    """One decomposed epoch/order exposure copied onto immutable byte buffers."""

    epoch_id: str
    order_id: str
    wavelength: FloatArray
    stellar_flux: FloatArray
    telluric_transmission: FloatArray
    lsf_kernel: FloatArray
    noise: FloatArray
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        epoch_id = _native_label(self.epoch_id, "epoch_id")
        order_id = _native_label(self.order_id, "order_id")
        validated = DecomposedSpectralExposure(
            wavelength=self.wavelength,
            stellar_flux=self.stellar_flux,
            telluric_transmission=self.telluric_transmission,
            lsf_kernel=self.lsf_kernel,
            noise=self.noise,
        )
        arrays = {
            "wavelength": _immutable_array(np.asarray(validated.wavelength)),
            "stellar_flux": _immutable_array(np.asarray(validated.stellar_flux)),
            "telluric_transmission": _immutable_array(np.asarray(validated.telluric_transmission)),
            "lsf_kernel": _immutable_array(np.asarray(validated.lsf_kernel)),
            "noise": _immutable_array(np.asarray(validated.noise)),
        }
        for name, array in arrays.items():
            object.__setattr__(self, name, array)
        object.__setattr__(self, "epoch_id", epoch_id)
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "content_sha256", self.recompute_sha256())

    @classmethod
    def from_decomposed(
        cls,
        epoch_id: str,
        order_id: str,
        exposure: DecomposedSpectralExposure,
    ) -> FrozenSpectralExposure:
        if not isinstance(exposure, DecomposedSpectralExposure):
            raise TypeError("exposure must be a DecomposedSpectralExposure")
        return cls(
            epoch_id=epoch_id,
            order_id=order_id,
            wavelength=exposure.wavelength,
            stellar_flux=exposure.stellar_flux,
            telluric_transmission=exposure.telluric_transmission,
            lsf_kernel=exposure.lsf_kernel,
            noise=exposure.noise,
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "epoch_id": self.epoch_id,
                "lsf_kernel": _array_identity(self.lsf_kernel),
                "noise": _array_identity(self.noise),
                "order_id": self.order_id,
                "stellar_flux": _array_identity(self.stellar_flux),
                "telluric_transmission": _array_identity(self.telluric_transmission),
                "wavelength": _array_identity(self.wavelength),
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.content_sha256:
            raise TemplateChainDataError("frozen exposure content hash mismatch")

    def to_decomposed(self) -> DecomposedSpectralExposure:
        self.verify_integrity()
        return DecomposedSpectralExposure(
            wavelength=self.wavelength,
            stellar_flux=self.stellar_flux,
            telluric_transmission=self.telluric_transmission,
            lsf_kernel=self.lsf_kernel,
            noise=self.noise,
        )

    def observed_flux(self) -> FloatArray:
        self.verify_integrity()
        try:
            with np.errstate(over="raise", invalid="raise"):
                pre_lsf = self.stellar_flux * self.telluric_transmission
                observed = convolve_fixed_lsf(pre_lsf, self.lsf_kernel) + self.noise
        except FloatingPointError as exc:
            raise TemplateChainDataError("exposure reconstruction became non-finite") from exc
        if not np.all(np.isfinite(observed)):
            raise TemplateChainDataError("exposure reconstruction became non-finite")
        return _immutable_array(np.asarray(observed, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class ExposureSet:
    """A complete rectangular epoch-by-order set in canonical row-major order."""

    epoch_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    records: tuple[FrozenSpectralExposure, ...]
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        epoch_ids = _labels(self.epoch_ids, "epoch_ids")
        order_ids = _labels(self.order_ids, "order_ids")
        records = tuple(self.records)
        expected_pairs = tuple((epoch, order) for epoch in epoch_ids for order in order_ids)
        supplied_pairs: list[tuple[str, str]] = []
        for record in records:
            if type(record) is not FrozenSpectralExposure:
                raise TemplateChainDataError(
                    "records must contain exact FrozenSpectralExposure values"
                )
            record.verify_integrity()
            supplied_pairs.append((record.epoch_id, record.order_id))
        if tuple(supplied_pairs) != expected_pairs:
            raise TemplateChainDataError(
                "records must exactly match epoch_ids x order_ids in canonical row-major order"
            )
        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "order_ids", order_ids)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "content_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "epoch_ids": list(self.epoch_ids),
                "order_ids": list(self.order_ids),
                "record_sha256": [record.recompute_sha256() for record in self.records],
            }
        )

    def verify_integrity(self) -> None:
        for record in self.records:
            record.verify_integrity()
        if self.recompute_sha256() != self.content_sha256:
            raise TemplateChainDataError("exposure-set content hash mismatch")

    def get(self, epoch_id: str, order_id: str) -> FrozenSpectralExposure:
        epoch = _native_label(epoch_id, "epoch_id")
        order = _native_label(order_id, "order_id")
        try:
            epoch_index = self.epoch_ids.index(epoch)
            order_index = self.order_ids.index(order)
        except ValueError as exc:
            raise TemplateChainDataError("requested exposure is outside the frozen set") from exc
        return self.records[epoch_index * len(self.order_ids) + order_index]

    def subset(
        self,
        epoch_ids: Sequence[str],
        order_ids: Sequence[str],
    ) -> ExposureSet:
        self.verify_integrity()
        epochs = _labels(epoch_ids, "subset epoch_ids")
        orders = _labels(order_ids, "subset order_ids")
        if not set(epochs).issubset(self.epoch_ids):
            raise TemplateChainDataError("subset contains an unknown epoch")
        if not set(orders).issubset(self.order_ids):
            raise TemplateChainDataError("subset contains an unknown order")
        return ExposureSet(
            epoch_ids=epochs,
            order_ids=orders,
            records=tuple(self.get(epoch, order) for epoch in epochs for order in orders),
        )


@dataclass(frozen=True, slots=True)
class TemplateFold:
    """One explicit template-training and evaluation split."""

    fold_id: str
    training_epoch_ids: tuple[str, ...]
    evaluation_epoch_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        fold_id = _native_label(self.fold_id, "fold_id")
        training = _labels(self.training_epoch_ids, "training_epoch_ids")
        evaluation = _labels(self.evaluation_epoch_ids, "evaluation_epoch_ids")
        if not set(training).isdisjoint(evaluation):
            raise TemplateChainDataError(
                "training and evaluation epochs must be disjoint within every fold"
            )
        object.__setattr__(self, "fold_id", fold_id)
        object.__setattr__(self, "training_epoch_ids", training)
        object.__setattr__(self, "evaluation_epoch_ids", evaluation)


@dataclass(frozen=True, slots=True)
class FoldPlan:
    """Exact disjoint or leave-one-out fold construction."""

    strategy: FoldStrategy
    epoch_ids: tuple[str, ...]
    folds: tuple[TemplateFold, ...]
    plan_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.strategy) is not str or self.strategy not in ("disjoint", "leave_one_out"):
            raise TemplateChainDataError("strategy must be 'disjoint' or 'leave_one_out'")
        epoch_ids = _labels(self.epoch_ids, "epoch_ids")
        if len(epoch_ids) < 2:
            raise TemplateChainDataError("a fold plan requires at least two epochs")
        folds = tuple(self.folds)
        if not folds or any(type(fold) is not TemplateFold for fold in folds):
            raise TemplateChainDataError("folds must contain exact TemplateFold values")
        if len({fold.fold_id for fold in folds}) != len(folds):
            raise TemplateChainDataError("fold IDs must be unique")
        known = set(epoch_ids)
        for fold in folds:
            if not set(fold.training_epoch_ids).issubset(known) or not set(
                fold.evaluation_epoch_ids
            ).issubset(known):
                raise TemplateChainDataError("a fold references an unknown epoch")

        if self.strategy == "disjoint":
            if len(folds) != 1:
                raise TemplateChainDataError("disjoint strategy requires exactly one fold")
            covered = set(folds[0].training_epoch_ids) | set(folds[0].evaluation_epoch_ids)
            if covered != known:
                raise TemplateChainDataError(
                    "a disjoint fold must partition every declared epoch exactly once"
                )
        else:
            if len(folds) != len(epoch_ids):
                raise TemplateChainDataError("leave-one-out requires one fold per epoch")
            expected_evaluations = tuple((epoch,) for epoch in epoch_ids)
            actual_evaluations = tuple(fold.evaluation_epoch_ids for fold in folds)
            if actual_evaluations != expected_evaluations:
                raise TemplateChainDataError(
                    "leave-one-out evaluation folds must follow the declared epoch order"
                )
            for fold, evaluation_epoch in zip(folds, epoch_ids, strict=True):
                expected_training = tuple(epoch for epoch in epoch_ids if epoch != evaluation_epoch)
                if fold.training_epoch_ids != expected_training:
                    raise TemplateChainDataError(
                        "leave-one-out training must contain every non-evaluation epoch"
                    )

        object.__setattr__(self, "epoch_ids", epoch_ids)
        object.__setattr__(self, "folds", folds)
        object.__setattr__(
            self,
            "plan_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "epoch_ids": list(self.epoch_ids),
                "folds": [
                    {
                        "evaluation_epoch_ids": list(fold.evaluation_epoch_ids),
                        "fold_id": fold.fold_id,
                        "training_epoch_ids": list(fold.training_epoch_ids),
                    }
                    for fold in self.folds
                ],
                "strategy": self.strategy,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.plan_sha256:
            raise TemplateChainDataError("fold plan content hash mismatch")


def make_disjoint_fold_plan(
    training_epoch_ids: Sequence[str],
    evaluation_epoch_ids: Sequence[str],
    *,
    fold_id: str,
) -> FoldPlan:
    """Build one exact disjoint train/evaluation partition."""
    training = _labels(training_epoch_ids, "training_epoch_ids")
    evaluation = _labels(evaluation_epoch_ids, "evaluation_epoch_ids")
    return FoldPlan(
        strategy="disjoint",
        epoch_ids=(*training, *evaluation),
        folds=(
            TemplateFold(
                fold_id=fold_id,
                training_epoch_ids=training,
                evaluation_epoch_ids=evaluation,
            ),
        ),
    )


def make_leave_one_out_fold_plan(epoch_ids: Sequence[str]) -> FoldPlan:
    """Build exact leave-one-out folds in the caller's declared epoch order."""
    epochs = _labels(epoch_ids, "epoch_ids")
    return FoldPlan(
        strategy="leave_one_out",
        epoch_ids=epochs,
        folds=tuple(
            TemplateFold(
                fold_id=f"loo-{index:04d}",
                training_epoch_ids=tuple(candidate for candidate in epochs if candidate != epoch),
                evaluation_epoch_ids=(epoch,),
            )
            for index, epoch in enumerate(epochs)
        ),
    )


@dataclass(frozen=True, slots=True)
class ExtractionArm:
    """One caller-named arm and its explicit fitting order identities."""

    arm_id: str
    fit_order_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arm_id", _native_label(self.arm_id, "arm_id"))
        object.__setattr__(self, "fit_order_ids", _labels(self.fit_order_ids, "fit_order_ids"))


@dataclass(frozen=True, slots=True)
class OrderPropagationPlan:
    """Freeze common-template or arm-specific template order propagation."""

    mode: TemplateOrderMode
    available_order_ids: tuple[str, ...]
    arms: tuple[ExtractionArm, ...]
    common_template_order_ids: tuple[str, ...] | None
    plan_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in ("common", "arm_specific"):
            raise TemplateChainDataError("mode must be 'common' or 'arm_specific'")
        available = _labels(self.available_order_ids, "available_order_ids")
        arms = tuple(self.arms)
        if not arms or any(type(arm) is not ExtractionArm for arm in arms):
            raise TemplateChainDataError("arms must contain exact ExtractionArm values")
        if len({arm.arm_id for arm in arms}) != len(arms):
            raise TemplateChainDataError("arm IDs must be unique")
        available_set = set(available)
        for arm in arms:
            if not set(arm.fit_order_ids).issubset(available_set):
                raise TemplateChainDataError("an arm references an unavailable order")

        common: tuple[str, ...] | None
        if self.mode == "common":
            if self.common_template_order_ids is None:
                raise TemplateChainDataError(
                    "common mode requires explicit common_template_order_ids"
                )
            common = _labels(self.common_template_order_ids, "common_template_order_ids")
            if not set(common).issubset(available_set):
                raise TemplateChainDataError("common template references an unavailable order")
            for arm in arms:
                if not set(arm.fit_order_ids).issubset(common):
                    raise TemplateChainDataError(
                        "every arm fitting order must be present in the common template"
                    )
        else:
            if self.common_template_order_ids is not None:
                raise TemplateChainDataError("arm_specific mode forbids common_template_order_ids")
            common = None

        object.__setattr__(self, "available_order_ids", available)
        object.__setattr__(self, "arms", arms)
        object.__setattr__(self, "common_template_order_ids", common)
        object.__setattr__(
            self,
            "plan_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "arms": [
                    {"arm_id": arm.arm_id, "fit_order_ids": list(arm.fit_order_ids)}
                    for arm in self.arms
                ],
                "available_order_ids": list(self.available_order_ids),
                "common_template_order_ids": None
                if self.common_template_order_ids is None
                else list(self.common_template_order_ids),
                "mode": self.mode,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.plan_sha256:
            raise TemplateChainDataError("order propagation plan content hash mismatch")

    def template_order_ids_for(self, arm: ExtractionArm) -> tuple[str, ...]:
        if type(arm) is not ExtractionArm or arm not in self.arms:
            raise TemplateChainDataError("arm is outside the frozen order plan")
        if self.mode == "common":
            assert self.common_template_order_ids is not None
            return self.common_template_order_ids
        return arm.fit_order_ids


@dataclass(frozen=True, slots=True)
class ChainRosterEntry:
    """One canonical arm/fold semantic slot shared by every injection trial."""

    arm_id: str
    fold_id: str
    training_epoch_ids: tuple[str, ...]
    evaluation_epoch_ids: tuple[str, ...]
    template_order_ids: tuple[str, ...]
    fit_order_ids: tuple[str, ...]
    entry_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        arm = _native_label(self.arm_id, "arm_id")
        fold = _native_label(self.fold_id, "fold_id")
        training = _labels(self.training_epoch_ids, "training_epoch_ids")
        evaluation = _labels(self.evaluation_epoch_ids, "evaluation_epoch_ids")
        template_orders = _labels(self.template_order_ids, "template_order_ids")
        fit_orders = _labels(self.fit_order_ids, "fit_order_ids")
        if not set(training).isdisjoint(evaluation):
            raise TemplateChainDataError("roster training/evaluation epochs overlap")
        for name, value in (
            ("arm_id", arm),
            ("fold_id", fold),
            ("training_epoch_ids", training),
            ("evaluation_epoch_ids", evaluation),
            ("template_order_ids", template_orders),
            ("fit_order_ids", fit_orders),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "entry_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "arm_id": self.arm_id,
                "evaluation_epoch_ids": list(self.evaluation_epoch_ids),
                "fit_order_ids": list(self.fit_order_ids),
                "fold_id": self.fold_id,
                "template_order_ids": list(self.template_order_ids),
                "training_epoch_ids": list(self.training_epoch_ids),
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.entry_sha256:
            raise TemplateChainDataError("chain roster entry content hash mismatch")


@dataclass(frozen=True, slots=True)
class TemplateChainRoster:
    """Complete canonical arm/fold roster derived from the two frozen plans."""

    fold_plan: FoldPlan
    order_plan: OrderPropagationPlan
    entries: tuple[ChainRosterEntry, ...] = field(init=False)
    roster_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.fold_plan) is not FoldPlan:
            raise TemplateChainDataError("fold_plan must be an exact FoldPlan")
        if type(self.order_plan) is not OrderPropagationPlan:
            raise TemplateChainDataError("order_plan must be an exact OrderPropagationPlan")
        self.fold_plan.verify_integrity()
        self.order_plan.verify_integrity()
        entries = tuple(
            ChainRosterEntry(
                arm_id=arm.arm_id,
                fold_id=fold.fold_id,
                training_epoch_ids=fold.training_epoch_ids,
                evaluation_epoch_ids=fold.evaluation_epoch_ids,
                template_order_ids=self.order_plan.template_order_ids_for(arm),
                fit_order_ids=arm.fit_order_ids,
            )
            for arm in self.order_plan.arms
            for fold in self.fold_plan.folds
        )
        identities = tuple(entry.entry_sha256 for entry in entries)
        if len(set(identities)) != len(identities):
            raise TemplateChainDataError("arm/fold roster entries must be unique")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(
            self,
            "roster_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "entry_sha256": [entry.recompute_sha256() for entry in self.entries],
                "fold_plan_sha256": self.fold_plan.recompute_sha256(),
                "order_plan_sha256": self.order_plan.recompute_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        self.fold_plan.verify_integrity()
        self.order_plan.verify_integrity()
        for entry in self.entries:
            entry.verify_integrity()
        if self.recompute_sha256() != self.roster_sha256:
            raise TemplateChainDataError("template chain roster content hash mismatch")


@dataclass(frozen=True, slots=True)
class CrossInjectionMaskContract:
    """Explicitly select the trial whose complete mask roster is authoritative.

    The selected trial is not a scientific truth claim.  It is only the caller-bound
    semantic reference against which every other injection's template, training-RV, and
    available evaluation-RV masks are compared exactly.
    """

    reference_plan_sha256: str
    roster_sha256: str
    contract_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        reference = _digest(self.reference_plan_sha256, "reference_plan_sha256")
        roster = _digest(self.roster_sha256, "roster_sha256")
        object.__setattr__(self, "reference_plan_sha256", reference)
        object.__setattr__(self, "roster_sha256", roster)
        object.__setattr__(
            self,
            "contract_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "reference_plan_sha256": self.reference_plan_sha256,
                "roster_sha256": self.roster_sha256,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.contract_sha256:
            raise TemplateChainDataError("cross-injection mask contract content hash mismatch")


@dataclass(frozen=True, slots=True)
class EpochVelocity:
    """One explicit pre-template stellar velocity injection."""

    epoch_id: str
    velocity_m_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _native_label(self.epoch_id, "epoch_id"))
        velocity = _finite_native_float(self.velocity_m_s, "velocity_m_s")
        object.__setattr__(
            self,
            "velocity_m_s",
            _canonical_zero(velocity),
        )


@dataclass(frozen=True, slots=True)
class PreTemplateInjectionPlan:
    """A complete epoch-labeled velocity plan applied before iteration zero.

    ``replicate_identity_sha256`` is retained as legacy provenance metadata only.  It never
    authorizes a duplicate schedule in this single-source runner and is deliberately excluded
    from the physical/semantic application identity.
    """

    plan_label: str
    epoch_ids: tuple[str, ...]
    velocities: tuple[EpochVelocity, ...]
    replicate_identity_sha256: str | None = None
    velocity_pattern_sha256: str = field(init=False)
    plan_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        label = _native_label(self.plan_label, "plan_label")
        epochs = _labels(self.epoch_ids, "epoch_ids")
        velocities = tuple(self.velocities)
        if any(type(item) is not EpochVelocity for item in velocities):
            raise TemplateChainDataError("velocities must contain exact EpochVelocity values")
        if tuple(item.epoch_id for item in velocities) != epochs:
            raise TemplateChainDataError(
                "velocities must exactly follow the complete declared epoch order"
            )
        replicate_identity = self.replicate_identity_sha256
        if replicate_identity is not None:
            replicate_identity = _digest(
                replicate_identity,
                "replicate_identity_sha256",
            )
        velocity_pattern_sha256 = canonical_sha256(
            {
                "epoch_velocity": [
                    {
                        "epoch_id": item.epoch_id,
                        "velocity_m_s_hex": item.velocity_m_s.hex(),
                    }
                    for item in velocities
                ]
            }
        )
        object.__setattr__(self, "plan_label", label)
        object.__setattr__(self, "epoch_ids", epochs)
        object.__setattr__(self, "velocities", velocities)
        object.__setattr__(self, "replicate_identity_sha256", replicate_identity)
        object.__setattr__(self, "velocity_pattern_sha256", velocity_pattern_sha256)
        object.__setattr__(
            self,
            "plan_sha256",
            self.recompute_sha256(),
        )

    def recompute_velocity_pattern_sha256(self) -> str:
        return canonical_sha256(
            {
                "epoch_velocity": [
                    {
                        "epoch_id": item.epoch_id,
                        "velocity_m_s_hex": item.velocity_m_s.hex(),
                    }
                    for item in self.velocities
                ]
            }
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "plan_label": self.plan_label,
                "replicate_identity_sha256": self.replicate_identity_sha256,
                "velocity_pattern_sha256": self.recompute_velocity_pattern_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        if tuple(item.epoch_id for item in self.velocities) != self.epoch_ids:
            raise TemplateChainDataError("injection velocity roster changed")
        if self.recompute_velocity_pattern_sha256() != self.velocity_pattern_sha256:
            raise TemplateChainDataError("velocity pattern content hash mismatch")
        if self.recompute_sha256() != self.plan_sha256:
            raise TemplateChainDataError("injection plan content hash mismatch")


@dataclass(frozen=True, slots=True)
class AppliedInjection:
    """Replay-verified result of applying a complete plan to an immutable source set."""

    plan: PreTemplateInjectionPlan
    source: ExposureSet
    exposures: ExposureSet
    source_exposure_sha256: str = field(init=False)
    semantic_application_sha256: str = field(init=False)
    application_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.plan) is not PreTemplateInjectionPlan:
            raise TemplateChainDataError("plan must be a PreTemplateInjectionPlan")
        self.plan.verify_integrity()
        if type(self.source) is not ExposureSet:
            raise TemplateChainDataError("source must be an ExposureSet")
        self.source.verify_integrity()
        if type(self.exposures) is not ExposureSet:
            raise TemplateChainDataError("exposures must be an ExposureSet")
        self.exposures.verify_integrity()
        if self.exposures.epoch_ids != self.plan.epoch_ids:
            raise TemplateChainDataError("applied exposures do not match the injection epochs")
        expected = _apply_injection_exposures(self.source, self.plan)
        if expected.content_sha256 != self.exposures.content_sha256:
            raise TemplateChainDataError(
                "applied exposures do not exactly replay from the retained source and plan"
            )
        object.__setattr__(
            self,
            "source_exposure_sha256",
            self.source.content_sha256,
        )
        semantic_application_sha256 = self.recompute_semantic_application_sha256()
        object.__setattr__(
            self,
            "semantic_application_sha256",
            semantic_application_sha256,
        )
        object.__setattr__(
            self,
            "application_sha256",
            self.recompute_sha256(),
        )

    def recompute_semantic_application_sha256(self) -> str:
        return canonical_sha256(
            {
                "applied_exposure_sha256": self.exposures.recompute_sha256(),
                "source_exposure_sha256": self.source.recompute_sha256(),
                "velocity_pattern_sha256": self.plan.recompute_velocity_pattern_sha256(),
            }
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "applied_exposure_sha256": self.exposures.recompute_sha256(),
                "injection_plan_sha256": self.plan.recompute_sha256(),
                "semantic_application_sha256": self.recompute_semantic_application_sha256(),
                "source_exposure_sha256": self.source.recompute_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        self.plan.verify_integrity()
        self.source.verify_integrity()
        self.exposures.verify_integrity()
        if self.source.recompute_sha256() != self.source_exposure_sha256:
            raise TemplateChainDataError("retained injection source content hash mismatch")
        if self.exposures.epoch_ids != self.plan.epoch_ids:
            raise TemplateChainDataError("applied exposures do not match the injection epochs")
        expected = _apply_injection_exposures(self.source, self.plan)
        if expected.content_sha256 != self.exposures.content_sha256:
            raise TemplateChainDataError(
                "applied exposures do not exactly replay from the retained source and plan"
            )
        if self.recompute_semantic_application_sha256() != self.semantic_application_sha256:
            raise TemplateChainDataError("semantic injection application content hash mismatch")
        if self.recompute_sha256() != self.application_sha256:
            raise TemplateChainDataError("injection application content hash mismatch")


def _apply_injection_exposures(
    source: ExposureSet,
    plan: PreTemplateInjectionPlan,
) -> ExposureSet:
    if type(source) is not ExposureSet:
        raise TypeError("source must be an ExposureSet")
    if type(plan) is not PreTemplateInjectionPlan:
        raise TypeError("plan must be a PreTemplateInjectionPlan")
    source.verify_integrity()
    plan.verify_integrity()
    if plan.epoch_ids != source.epoch_ids:
        raise TemplateChainDataError("injection plan epochs do not match the source set")
    velocity_by_epoch = {item.epoch_id: item.velocity_m_s for item in plan.velocities}
    injected_records: list[FrozenSpectralExposure] = []
    for record in source.records:
        decomposed = record.to_decomposed()
        velocity = velocity_by_epoch[record.epoch_id]
        result = inject_stellar_velocity(decomposed, velocity)
        invariants = check_injection_invariants(
            decomposed,
            result,
            expected_velocity_m_s=velocity,
        )
        if not invariants.passed:
            raise TemplateChainExecutionError("stellar injection invariants failed")
        injected_records.append(
            FrozenSpectralExposure(
                epoch_id=record.epoch_id,
                order_id=record.order_id,
                wavelength=result.wavelength,
                stellar_flux=result.shifted_stellar_flux,
                telluric_transmission=result.telluric_transmission,
                lsf_kernel=result.lsf_kernel,
                noise=result.noise,
            )
        )
    source.verify_integrity()
    return ExposureSet(
        epoch_ids=source.epoch_ids,
        order_ids=source.order_ids,
        records=tuple(injected_records),
    )


def apply_pre_template_injection(
    source: ExposureSet,
    plan: PreTemplateInjectionPlan,
) -> AppliedInjection:
    """Apply every stellar injection before any template state can be created."""
    exposures = _apply_injection_exposures(source, plan)
    return AppliedInjection(
        plan=plan,
        source=source,
        exposures=exposures,
    )


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    """Content identity for one caller-supplied adapter implementation/configuration."""

    adapter_name: str
    adapter_version: str
    configuration_sha256: str
    identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        name = _native_label(self.adapter_name, "adapter_name")
        version = _native_label(self.adapter_version, "adapter_version")
        configuration = _digest(self.configuration_sha256, "configuration_sha256")
        object.__setattr__(self, "adapter_name", name)
        object.__setattr__(self, "adapter_version", version)
        object.__setattr__(self, "configuration_sha256", configuration)
        object.__setattr__(
            self,
            "identity_sha256",
            canonical_sha256(
                {
                    "adapter_name": name,
                    "adapter_version": version,
                    "configuration_sha256": configuration,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ChainInvocation:
    """Immutable lineage for one plan/arm/fold full template chain."""

    ensemble_nonce: str
    injection_plan_sha256: str
    applied_injection_sha256: str
    fold_plan_sha256: str
    order_plan_sha256: str
    convergence_policy_sha256: str
    adapter_identity_sha256: str
    roster_entry_sha256: str
    mask_contract_sha256: str
    arm_id: str
    fold_id: str
    training_epoch_ids: tuple[str, ...]
    evaluation_epoch_ids: tuple[str, ...]
    template_order_ids: tuple[str, ...]
    fit_order_ids: tuple[str, ...]
    invocation_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digest_fields = (
            "ensemble_nonce",
            "injection_plan_sha256",
            "applied_injection_sha256",
            "fold_plan_sha256",
            "order_plan_sha256",
            "convergence_policy_sha256",
            "adapter_identity_sha256",
            "roster_entry_sha256",
            "mask_contract_sha256",
        )
        for name in digest_fields:
            _digest(getattr(self, name), name)
        arm = _native_label(self.arm_id, "arm_id")
        fold = _native_label(self.fold_id, "fold_id")
        training = _labels(self.training_epoch_ids, "training_epoch_ids")
        evaluation = _labels(self.evaluation_epoch_ids, "evaluation_epoch_ids")
        template_orders = _labels(self.template_order_ids, "template_order_ids")
        fit_orders = _labels(self.fit_order_ids, "fit_order_ids")
        if not set(training).isdisjoint(evaluation):
            raise TemplateChainDataError("invocation training/evaluation epochs overlap")
        for name, value in (
            ("arm_id", arm),
            ("fold_id", fold),
            ("training_epoch_ids", training),
            ("evaluation_epoch_ids", evaluation),
            ("template_order_ids", template_orders),
            ("fit_order_ids", fit_orders),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "invocation_sha256",
            canonical_sha256(
                {
                    "adapter_identity_sha256": self.adapter_identity_sha256,
                    "applied_injection_sha256": self.applied_injection_sha256,
                    "arm_id": arm,
                    "convergence_policy_sha256": self.convergence_policy_sha256,
                    "ensemble_nonce": self.ensemble_nonce,
                    "evaluation_epoch_ids": list(evaluation),
                    "fit_order_ids": list(fit_orders),
                    "fold_id": fold,
                    "fold_plan_sha256": self.fold_plan_sha256,
                    "injection_plan_sha256": self.injection_plan_sha256,
                    "order_plan_sha256": self.order_plan_sha256,
                    "roster_entry_sha256": self.roster_entry_sha256,
                    "mask_contract_sha256": self.mask_contract_sha256,
                    "template_order_ids": list(template_orders),
                    "training_epoch_ids": list(training),
                }
            ),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "adapter_identity_sha256": self.adapter_identity_sha256,
                "applied_injection_sha256": self.applied_injection_sha256,
                "arm_id": self.arm_id,
                "convergence_policy_sha256": self.convergence_policy_sha256,
                "ensemble_nonce": self.ensemble_nonce,
                "evaluation_epoch_ids": list(self.evaluation_epoch_ids),
                "fit_order_ids": list(self.fit_order_ids),
                "fold_id": self.fold_id,
                "fold_plan_sha256": self.fold_plan_sha256,
                "injection_plan_sha256": self.injection_plan_sha256,
                "mask_contract_sha256": self.mask_contract_sha256,
                "order_plan_sha256": self.order_plan_sha256,
                "roster_entry_sha256": self.roster_entry_sha256,
                "template_order_ids": list(self.template_order_ids),
                "training_epoch_ids": list(self.training_epoch_ids),
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.invocation_sha256:
            raise TemplateChainDataError("chain invocation content hash mismatch")


@dataclass(frozen=True, slots=True)
class TemplateState:
    """One immutable, lineage-bound template state."""

    invocation_sha256: str
    state_index: int
    order_ids: tuple[str, ...]
    flux: FloatArray
    valid_mask: BoolArray
    state_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        invocation = _digest(self.invocation_sha256, "invocation_sha256")
        index = _native_index(self.state_index, "state_index")
        orders = _labels(self.order_ids, "order_ids")
        flux = _float_matrix(self.flux, "flux")
        if flux.shape[0] != len(orders):
            raise TemplateChainDataError("template order labels do not match the flux shape")
        mask = _bool_matrix(self.valid_mask, "valid_mask", flux.shape)
        if np.any(np.isinf(flux)):
            raise TemplateChainDataError("template flux cannot contain infinity")
        if np.any(mask & ~np.isfinite(flux)):
            raise TemplateChainDataError("valid template cells must be finite")
        if np.any(~mask & ~np.isnan(flux)):
            raise TemplateChainDataError("invalid template cells must use NaN sentinels")
        if np.any(np.sum(mask, axis=1) == 0):
            raise TemplateChainDataError("every template order must retain a valid pixel")
        object.__setattr__(self, "invocation_sha256", invocation)
        object.__setattr__(self, "state_index", index)
        object.__setattr__(self, "order_ids", orders)
        object.__setattr__(self, "flux", flux)
        object.__setattr__(self, "valid_mask", mask)
        object.__setattr__(self, "state_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "flux": _array_identity(self.flux),
                "invocation_sha256": self.invocation_sha256,
                "order_ids": list(self.order_ids),
                "state_index": self.state_index,
                "valid_mask": _array_identity(self.valid_mask),
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.state_sha256:
            raise TemplateChainDataError("template state content hash mismatch")


@dataclass(frozen=True, slots=True)
class RVState:
    """One immutable training or evaluation epoch-by-order RV state."""

    invocation_sha256: str
    state_index: int
    role: RVRole
    epoch_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    values: FloatArray
    valid_mask: BoolArray
    state_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        invocation = _digest(self.invocation_sha256, "invocation_sha256")
        index = _native_index(self.state_index, "state_index")
        if type(self.role) is not str or self.role not in ("training", "evaluation"):
            raise TemplateChainDataError("role must be 'training' or 'evaluation'")
        epochs = _labels(self.epoch_ids, "epoch_ids")
        orders = _labels(self.order_ids, "order_ids")
        values = _float_matrix(self.values, "values")
        if values.shape != (len(epochs), len(orders)):
            raise TemplateChainDataError("RV labels do not match the value shape")
        mask = _bool_matrix(self.valid_mask, "valid_mask", values.shape)
        if np.any(np.isinf(values)):
            raise TemplateChainDataError("RV values cannot contain infinity")
        if np.any(mask & ~np.isfinite(values)):
            raise TemplateChainDataError("valid RV cells must be finite")
        if np.any(~mask & ~np.isnan(values)):
            raise TemplateChainDataError("invalid RV cells must use NaN sentinels")
        if np.any(np.sum(mask, axis=1) == 0) or np.any(np.sum(mask, axis=0) == 0):
            raise TemplateChainDataError("every RV epoch and order must retain a valid cell")
        object.__setattr__(self, "invocation_sha256", invocation)
        object.__setattr__(self, "state_index", index)
        object.__setattr__(self, "epoch_ids", epochs)
        object.__setattr__(self, "order_ids", orders)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid_mask", mask)
        object.__setattr__(self, "state_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "epoch_ids": list(self.epoch_ids),
                "invocation_sha256": self.invocation_sha256,
                "order_ids": list(self.order_ids),
                "role": self.role,
                "state_index": self.state_index,
                "valid_mask": _array_identity(self.valid_mask),
                "values": _array_identity(self.values),
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.state_sha256:
            raise TemplateChainDataError("RV state content hash mismatch")


class TemplateChainSession(Protocol):
    """Fresh adapter session for exactly one lineage-bound full chain."""

    @property
    def session_token(self) -> str: ...

    def initial_template(
        self,
        training_data: ExposureSet,
        invocation: ChainInvocation,
    ) -> TemplateState: ...

    def fit_training(
        self,
        training_data: ExposureSet,
        template: TemplateState,
        invocation: ChainInvocation,
    ) -> RVState: ...

    def update_template(
        self,
        training_data: ExposureSet,
        previous_template: TemplateState,
        previous_rv: RVState,
        *,
        state_index: int,
        invocation: ChainInvocation,
    ) -> TemplateState: ...

    def adjacent_noise_scale(
        self,
        previous_template: TemplateState,
        current_template: TemplateState,
        invocation: ChainInvocation,
    ) -> ArrayLike: ...

    def fit_evaluation(
        self,
        evaluation_data: ExposureSet,
        template: TemplateState,
        invocation: ChainInvocation,
    ) -> RVState: ...


class TemplateChainAdapterFactory(Protocol):
    """Factory that must return a fresh session for each invocation."""

    @property
    def identity(self) -> AdapterIdentity: ...

    def create_session(self, invocation: ChainInvocation) -> TemplateChainSession: ...


def _convergence_identity(result: ConvergenceResult) -> str:
    if type(result) is not ConvergenceResult:
        raise TemplateChainDataError("convergence must be an exact ConvergenceResult")
    history: list[dict[str, object]] = []
    for update in result.history:
        template_metric = update.template_metric
        rv_metric = update.rv_metric
        history.append(
            {
                "consecutive_joint_passes": int(update.consecutive_joint_passes),
                "failure_reason": update.failure_reason,
                "iteration": int(update.iteration),
                "jointly_passed": bool(update.jointly_passed),
                "rv_metric": None
                if rv_metric is None
                else {
                    "current_zero_point_hex": rv_metric.current_zero_point.hex(),
                    "previous_zero_point_hex": rv_metric.previous_zero_point.hex(),
                    "valid_cell_count": rv_metric.valid_cell_count,
                    "value_hex": rv_metric.value.hex(),
                },
                "rv_passed": bool(update.rv_passed),
                "template_metric": None
                if template_metric is None
                else {
                    "aggregate_hex": template_metric.aggregate.hex(),
                    "aggregate_method": template_metric.aggregate_method,
                    "per_order": _array_identity(template_metric.per_order),
                    "valid_pixel_counts": _array_identity(template_metric.valid_pixel_counts),
                },
                "template_passed": bool(update.template_passed),
            }
        )
    return canonical_sha256(
        {
            "converged": bool(result.converged),
            "converged_iteration": result.converged_iteration,
            "failure_code": result.failure_code,
            "failure_reason": result.failure_reason,
            "history": history,
            "policy_sha256": _policy_identity(result.policy),
        }
    )


def _freeze_convergence(result: ConvergenceResult) -> ConvergenceResult:
    """Detach convergence evidence onto immutable buffers and native scalars."""
    if type(result) is not ConvergenceResult:
        raise TemplateChainDataError("convergence must be an exact ConvergenceResult")
    history: list[ConvergenceUpdate] = []
    for update in result.history:
        template_metric = update.template_metric
        frozen_template_metric = (
            None
            if template_metric is None
            else TemplateChangeMetric(
                per_order=_immutable_array(
                    np.array(template_metric.per_order, dtype=np.float64, copy=True)
                ),
                aggregate=float(template_metric.aggregate),
                aggregate_method=template_metric.aggregate_method,
                valid_pixel_counts=_immutable_array(
                    np.array(template_metric.valid_pixel_counts, dtype=np.int64, copy=True)
                ),
            )
        )
        rv_metric = update.rv_metric
        frozen_rv_metric = (
            None
            if rv_metric is None
            else RVChangeMetric(
                value=float(rv_metric.value),
                previous_zero_point=float(rv_metric.previous_zero_point),
                current_zero_point=float(rv_metric.current_zero_point),
                valid_cell_count=int(rv_metric.valid_cell_count),
            )
        )
        history.append(
            ConvergenceUpdate(
                iteration=int(update.iteration),
                template_metric=frozen_template_metric,
                rv_metric=frozen_rv_metric,
                template_passed=bool(update.template_passed),
                rv_passed=bool(update.rv_passed),
                jointly_passed=bool(update.jointly_passed),
                consecutive_joint_passes=int(update.consecutive_joint_passes),
                failure_reason=update.failure_reason,
            )
        )
    return ConvergenceResult(
        converged=bool(result.converged),
        converged_iteration=result.converged_iteration,
        failure_code=result.failure_code,
        failure_reason=result.failure_reason,
        history=tuple(history),
        policy=result.policy,
    )


@dataclass(frozen=True, slots=True)
class FoldChainResult:
    """Complete convergence history and optional evaluation fit for one fold."""

    invocation: ChainInvocation
    session_token: str
    template_states: tuple[TemplateState, ...]
    training_rv_states: tuple[RVState, ...]
    adjacent_template_noise_scales: tuple[FloatArray, ...]
    convergence: ConvergenceResult
    evaluation_rv: RVState | None
    convergence_sha256: str = field(init=False)
    result_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.invocation) is not ChainInvocation:
            raise TemplateChainDataError("invocation must be a ChainInvocation")
        self.invocation.verify_integrity()
        token = _native_label(self.session_token, "session_token")
        templates = tuple(self.template_states)
        rvs = tuple(self.training_rv_states)
        if not templates or len(templates) != len(rvs):
            raise TemplateChainDataError("template and training RV histories must align")
        if any(type(state) is not TemplateState for state in templates):
            raise TemplateChainDataError("template history contains an invalid state")
        if any(type(state) is not RVState for state in rvs):
            raise TemplateChainDataError("RV history contains an invalid state")
        for state in templates:
            state.verify_integrity()
        for state in rvs:
            state.verify_integrity()
        expected_indices = tuple(range(len(templates)))
        if (
            tuple(state.state_index for state in templates) != expected_indices
            or tuple(state.state_index for state in rvs) != expected_indices
        ):
            raise TemplateChainDataError("state histories must start at zero and be contiguous")
        if any(state.invocation_sha256 != self.invocation.invocation_sha256 for state in templates):
            raise TemplateChainDataError("template state lineage mismatch")
        if any(state.invocation_sha256 != self.invocation.invocation_sha256 for state in rvs):
            raise TemplateChainDataError("RV state lineage mismatch")
        if any(state.order_ids != self.invocation.template_order_ids for state in templates):
            raise TemplateChainDataError("template state order propagation mismatch")
        if any(
            state.role != "training"
            or state.epoch_ids != self.invocation.training_epoch_ids
            or state.order_ids != self.invocation.template_order_ids
            for state in rvs
        ):
            raise TemplateChainDataError("training RV epoch/order/role propagation mismatch")
        template_mask = templates[0].valid_mask
        training_mask = rvs[0].valid_mask
        if any(not np.array_equal(state.valid_mask, template_mask) for state in templates[1:]):
            raise TemplateChainDataError("template valid mask changed within the fold result")
        if any(not np.array_equal(state.valid_mask, training_mask) for state in rvs[1:]):
            raise TemplateChainDataError("training RV valid mask changed within the fold result")
        noises = tuple(self.adjacent_template_noise_scales)
        if len(noises) != len(templates) - 1:
            raise TemplateChainDataError("adjacent noise history must match template updates")
        frozen_mask = templates[0].valid_mask
        checked_noises = tuple(
            _noise_scale(noise, templates[0].flux.shape, frozen_mask) for noise in noises
        )
        frozen_convergence = _freeze_convergence(self.convergence)
        if _policy_identity(frozen_convergence.policy) != self.invocation.convergence_policy_sha256:
            raise TemplateChainDataError("convergence policy lineage mismatch")
        expected_iterations = tuple(range(1, len(templates)))
        if tuple(update.iteration for update in frozen_convergence.history) != expected_iterations:
            raise TemplateChainDataError(
                "convergence history must account for every contiguous template/RV update"
            )
        replayed = evaluate_convergence(
            np.stack([state.flux for state in templates]),
            np.stack(checked_noises),
            np.stack([state.values for state in rvs]),
            frozen_convergence.policy,
            template_valid_mask=templates[0].valid_mask,
            rv_valid_mask=rvs[0].valid_mask,
        )
        convergence_sha256 = _convergence_identity(frozen_convergence)
        if _convergence_identity(replayed) != convergence_sha256:
            raise TemplateChainDataError("stored convergence evidence does not replay exactly")
        if frozen_convergence.converged_iteration is not None and (
            frozen_convergence.converged_iteration != len(templates) - 1
        ):
            raise TemplateChainDataError("converged iteration does not identify the final state")
        evaluation = self.evaluation_rv
        if evaluation is not None:
            if type(evaluation) is not RVState or evaluation.role != "evaluation":
                raise TemplateChainDataError("evaluation_rv must be an evaluation RVState")
            if evaluation.invocation_sha256 != self.invocation.invocation_sha256:
                raise TemplateChainDataError("evaluation RV lineage mismatch")
            evaluation.verify_integrity()
            if (
                evaluation.state_index != frozen_convergence.converged_iteration
                or evaluation.epoch_ids != self.invocation.evaluation_epoch_ids
                or evaluation.order_ids != self.invocation.fit_order_ids
            ):
                raise TemplateChainDataError("evaluation RV state/epoch/order propagation mismatch")
        if frozen_convergence.converged != (evaluation is not None):
            raise TemplateChainDataError(
                "evaluation output must exist exactly when convergence succeeded"
            )
        object.__setattr__(self, "session_token", token)
        object.__setattr__(self, "template_states", templates)
        object.__setattr__(self, "training_rv_states", rvs)
        object.__setattr__(self, "adjacent_template_noise_scales", checked_noises)
        object.__setattr__(self, "convergence", frozen_convergence)
        object.__setattr__(self, "convergence_sha256", convergence_sha256)
        object.__setattr__(
            self,
            "result_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "converged": self.convergence.converged,
                "converged_iteration": self.convergence.converged_iteration,
                "evaluation_rv_sha256": None
                if self.evaluation_rv is None
                else self.evaluation_rv.recompute_sha256(),
                "failure_code": self.convergence.failure_code,
                "failure_reason": self.convergence.failure_reason,
                "invocation_sha256": self.invocation.recompute_sha256(),
                "noise_scale": [
                    _array_identity(noise) for noise in self.adjacent_template_noise_scales
                ],
                "session_token": self.session_token,
                "template_state_sha256": [
                    state.recompute_sha256() for state in self.template_states
                ],
                "training_rv_state_sha256": [
                    state.recompute_sha256() for state in self.training_rv_states
                ],
                "convergence_sha256": _convergence_identity(self.convergence),
            }
        )

    def verify_integrity(self) -> None:
        rebuilt = FoldChainResult(
            invocation=self.invocation,
            session_token=self.session_token,
            template_states=self.template_states,
            training_rv_states=self.training_rv_states,
            adjacent_template_noise_scales=self.adjacent_template_noise_scales,
            convergence=self.convergence,
            evaluation_rv=self.evaluation_rv,
        )
        if rebuilt.convergence_sha256 != self.convergence_sha256:
            raise TemplateChainDataError("fold convergence content hash mismatch")
        if rebuilt.result_sha256 != self.result_sha256:
            raise TemplateChainDataError("fold chain result content hash mismatch")


@dataclass(frozen=True, slots=True)
class InjectionTrialResult:
    """All arm/fold chains rebuilt from one fresh pre-template injection."""

    applied_injection: AppliedInjection
    roster: TemplateChainRoster
    mask_contract: CrossInjectionMaskContract
    fold_results: tuple[FoldChainResult, ...]
    result_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.applied_injection) is not AppliedInjection:
            raise TemplateChainDataError("applied_injection must be an AppliedInjection")
        if type(self.roster) is not TemplateChainRoster:
            raise TemplateChainDataError("roster must be a TemplateChainRoster")
        if type(self.mask_contract) is not CrossInjectionMaskContract:
            raise TemplateChainDataError("mask_contract must be a CrossInjectionMaskContract")
        self.applied_injection.verify_integrity()
        self.roster.verify_integrity()
        self.mask_contract.verify_integrity()
        if self.mask_contract.roster_sha256 != self.roster.roster_sha256:
            raise TemplateChainDataError("mask contract and trial roster identities differ")
        fold_results = tuple(self.fold_results)
        if not fold_results or any(type(item) is not FoldChainResult for item in fold_results):
            raise TemplateChainDataError("fold_results must contain FoldChainResult values")
        for item in fold_results:
            item.verify_integrity()
        if len(fold_results) != len(self.roster.entries):
            raise TemplateChainDataError("fold results do not form the complete arm/fold roster")
        plan_sha256 = self.applied_injection.plan.plan_sha256
        application_sha256 = self.applied_injection.application_sha256
        for result, entry in zip(fold_results, self.roster.entries, strict=True):
            invocation = result.invocation
            if (
                invocation.injection_plan_sha256 != plan_sha256
                or invocation.applied_injection_sha256 != application_sha256
            ):
                raise TemplateChainDataError("fold invocation is bound to another injection")
            if (
                invocation.fold_plan_sha256 != self.roster.fold_plan.plan_sha256
                or invocation.order_plan_sha256 != self.roster.order_plan.plan_sha256
                or invocation.mask_contract_sha256 != self.mask_contract.contract_sha256
            ):
                raise TemplateChainDataError("fold invocation plan/contract lineage mismatch")
            if (
                invocation.roster_entry_sha256 != entry.entry_sha256
                or invocation.arm_id != entry.arm_id
                or invocation.fold_id != entry.fold_id
                or invocation.training_epoch_ids != entry.training_epoch_ids
                or invocation.evaluation_epoch_ids != entry.evaluation_epoch_ids
                or invocation.template_order_ids != entry.template_order_ids
                or invocation.fit_order_ids != entry.fit_order_ids
            ):
                raise TemplateChainDataError("fold invocation does not match its semantic roster")
        if len({item.invocation.roster_entry_sha256 for item in fold_results}) != len(fold_results):
            raise TemplateChainDataError("fold result roster contains a duplicate entry")
        if len({item.session_token for item in fold_results}) != len(fold_results):
            raise TemplateChainDataError("session tokens must be unique within an injection trial")
        if len({item.invocation.ensemble_nonce for item in fold_results}) != 1:
            raise TemplateChainDataError("ensemble nonce changed within an injection trial")
        if len({item.invocation.adapter_identity_sha256 for item in fold_results}) != 1:
            raise TemplateChainDataError("adapter identity changed within an injection trial")
        if len({item.invocation.convergence_policy_sha256 for item in fold_results}) != 1:
            raise TemplateChainDataError("convergence policy changed within an injection trial")
        object.__setattr__(self, "fold_results", fold_results)
        object.__setattr__(
            self,
            "result_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "applied_injection_sha256": self.applied_injection.recompute_sha256(),
                "mask_contract_sha256": self.mask_contract.recompute_sha256(),
                "roster_sha256": self.roster.recompute_sha256(),
                "fold_result_sha256": [item.recompute_sha256() for item in self.fold_results],
            }
        )

    def verify_integrity(self) -> None:
        rebuilt = InjectionTrialResult(
            applied_injection=self.applied_injection,
            roster=self.roster,
            mask_contract=self.mask_contract,
            fold_results=self.fold_results,
        )
        if rebuilt.result_sha256 != self.result_sha256:
            raise TemplateChainDataError("injection trial result content hash mismatch")


@dataclass(frozen=True, slots=True)
class TemplateChainEnsembleResult:
    """Fresh-chain results for every supplied injection plan."""

    ensemble_nonce: str
    source_exposure_sha256: str
    roster: TemplateChainRoster
    mask_contract: CrossInjectionMaskContract
    trials: tuple[InjectionTrialResult, ...]
    reference_mask_roster_sha256: str = field(init=False)
    result_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        nonce = _digest(self.ensemble_nonce, "ensemble_nonce")
        source = _digest(self.source_exposure_sha256, "source_exposure_sha256")
        if type(self.roster) is not TemplateChainRoster:
            raise TemplateChainDataError("roster must be a TemplateChainRoster")
        if type(self.mask_contract) is not CrossInjectionMaskContract:
            raise TemplateChainDataError("mask_contract must be a CrossInjectionMaskContract")
        self.roster.verify_integrity()
        self.mask_contract.verify_integrity()
        if self.mask_contract.roster_sha256 != self.roster.roster_sha256:
            raise TemplateChainDataError("mask contract and ensemble roster identities differ")
        trials = tuple(self.trials)
        if not trials or any(type(item) is not InjectionTrialResult for item in trials):
            raise TemplateChainDataError("trials must contain InjectionTrialResult values")
        for item in trials:
            item.verify_integrity()
        if any(item.applied_injection.source_exposure_sha256 != source for item in trials):
            raise TemplateChainDataError("trial source lineage mismatch")
        if any(
            fold.invocation.ensemble_nonce != nonce
            for trial in trials
            for fold in trial.fold_results
        ):
            raise TemplateChainDataError("trial invocation ensemble nonce mismatch")
        if any(
            item.roster.roster_sha256 != self.roster.roster_sha256
            or item.mask_contract.contract_sha256 != self.mask_contract.contract_sha256
            for item in trials
        ):
            raise TemplateChainDataError("trials do not share the ensemble roster/mask contract")
        if len({item.result_sha256 for item in trials}) != len(trials):
            raise TemplateChainDataError("duplicate injection trial result")
        if len({item.applied_injection.plan.plan_sha256 for item in trials}) != len(trials):
            raise TemplateChainDataError("duplicate injection plan identity")
        if len({item.applied_injection.application_sha256 for item in trials}) != len(trials):
            raise TemplateChainDataError("duplicate applied injection identity")
        if len({item.applied_injection.exposures.content_sha256 for item in trials}) != len(trials):
            raise TemplateChainDataError("duplicate applied exposure content")
        if len({item.applied_injection.semantic_application_sha256 for item in trials}) != len(
            trials
        ):
            raise TemplateChainDataError("duplicate semantic injection application")
        if len({item.applied_injection.plan.velocity_pattern_sha256 for item in trials}) != len(
            trials
        ):
            raise TemplateChainDataError(
                "duplicate physical velocity schedules are forbidden in a single-source ensemble"
            )
        session_tokens = tuple(
            fold.session_token for trial in trials for fold in trial.fold_results
        )
        if len(set(session_tokens)) != len(session_tokens):
            raise TemplateChainDataError("session tokens must be unique across the ensemble")
        adapter_identities = {
            fold.invocation.adapter_identity_sha256
            for trial in trials
            for fold in trial.fold_results
        }
        policy_identities = {
            fold.invocation.convergence_policy_sha256
            for trial in trials
            for fold in trial.fold_results
        }
        if len(adapter_identities) != 1 or len(policy_identities) != 1:
            raise TemplateChainDataError(
                "adapter and convergence policy must remain identical across trials"
            )
        reference_trials = tuple(
            trial
            for trial in trials
            if trial.applied_injection.plan.plan_sha256 == self.mask_contract.reference_plan_sha256
        )
        if len(reference_trials) != 1:
            raise TemplateChainDataError(
                "mask contract reference plan must identify exactly one trial"
            )
        reference = reference_trials[0]
        reference_mask_entries: list[dict[str, object]] = []
        for roster_index, (entry, reference_fold) in enumerate(
            zip(self.roster.entries, reference.fold_results, strict=True)
        ):
            reference_evaluation = reference_fold.evaluation_rv
            reference_mask_entries.append(
                {
                    "evaluation_valid_mask": None
                    if reference_evaluation is None
                    else _array_identity(reference_evaluation.valid_mask),
                    "roster_entry_sha256": entry.entry_sha256,
                    "template_valid_mask": _array_identity(
                        reference_fold.template_states[0].valid_mask
                    ),
                    "training_rv_valid_mask": _array_identity(
                        reference_fold.training_rv_states[0].valid_mask
                    ),
                }
            )
            for trial in trials:
                current_fold = trial.fold_results[roster_index]
                if not np.array_equal(
                    current_fold.template_states[0].valid_mask,
                    reference_fold.template_states[0].valid_mask,
                ):
                    raise TemplateChainDataError(
                        "template mask drifted from the cross-injection reference roster"
                    )
                if not np.array_equal(
                    current_fold.training_rv_states[0].valid_mask,
                    reference_fold.training_rv_states[0].valid_mask,
                ):
                    raise TemplateChainDataError(
                        "training RV mask drifted from the cross-injection reference roster"
                    )
                current_evaluation = current_fold.evaluation_rv
                if current_evaluation is not None:
                    if reference_evaluation is None:
                        raise TemplateChainDataError(
                            "reference trial lacks an evaluation mask required by another trial"
                        )
                    if not np.array_equal(
                        current_evaluation.valid_mask,
                        reference_evaluation.valid_mask,
                    ):
                        raise TemplateChainDataError(
                            "evaluation RV mask drifted from the cross-injection reference roster"
                        )
        reference_mask_roster_sha256 = canonical_sha256(
            {
                "mask_contract_sha256": self.mask_contract.contract_sha256,
                "mask_entries": reference_mask_entries,
            }
        )
        object.__setattr__(self, "ensemble_nonce", nonce)
        object.__setattr__(self, "source_exposure_sha256", source)
        object.__setattr__(self, "trials", trials)
        object.__setattr__(
            self,
            "reference_mask_roster_sha256",
            reference_mask_roster_sha256,
        )
        object.__setattr__(
            self,
            "result_sha256",
            self.recompute_sha256(),
        )

    def _recompute_reference_mask_roster_sha256(self) -> str:
        reference_trials = tuple(
            trial
            for trial in self.trials
            if trial.applied_injection.plan.plan_sha256 == self.mask_contract.reference_plan_sha256
        )
        if len(reference_trials) != 1:
            raise TemplateChainDataError(
                "mask contract reference plan must identify exactly one trial"
            )
        reference = reference_trials[0]
        return canonical_sha256(
            {
                "mask_contract_sha256": self.mask_contract.recompute_sha256(),
                "mask_entries": [
                    {
                        "evaluation_valid_mask": None
                        if fold.evaluation_rv is None
                        else _array_identity(fold.evaluation_rv.valid_mask),
                        "roster_entry_sha256": entry.recompute_sha256(),
                        "template_valid_mask": _array_identity(fold.template_states[0].valid_mask),
                        "training_rv_valid_mask": _array_identity(
                            fold.training_rv_states[0].valid_mask
                        ),
                    }
                    for entry, fold in zip(
                        self.roster.entries,
                        reference.fold_results,
                        strict=True,
                    )
                ],
            }
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "ensemble_nonce": self.ensemble_nonce,
                "mask_contract_sha256": self.mask_contract.recompute_sha256(),
                "reference_mask_roster_sha256": (self._recompute_reference_mask_roster_sha256()),
                "roster_sha256": self.roster.recompute_sha256(),
                "source_exposure_sha256": self.source_exposure_sha256,
                "trial_result_sha256": [item.recompute_sha256() for item in self.trials],
            }
        )

    def verify_integrity(self) -> None:
        rebuilt = TemplateChainEnsembleResult(
            ensemble_nonce=self.ensemble_nonce,
            source_exposure_sha256=self.source_exposure_sha256,
            roster=self.roster,
            mask_contract=self.mask_contract,
            trials=self.trials,
        )
        if rebuilt.reference_mask_roster_sha256 != self.reference_mask_roster_sha256:
            raise TemplateChainDataError("ensemble reference mask roster content hash mismatch")
        if rebuilt.result_sha256 != self.result_sha256:
            raise TemplateChainDataError("template chain ensemble result content hash mismatch")


def _validate_template_state(
    state: TemplateState,
    invocation: ChainInvocation,
    state_index: int,
) -> TemplateState:
    if type(state) is not TemplateState:
        raise TemplateChainExecutionError("adapter must return an exact TemplateState")
    if state.invocation_sha256 != invocation.invocation_sha256:
        raise TemplateChainExecutionError("adapter returned stale template lineage")
    try:
        state.verify_integrity()
    except TemplateChainDataError as exc:
        raise TemplateChainExecutionError("adapter returned corrupt template content") from exc
    if state.state_index != state_index:
        raise TemplateChainExecutionError("adapter returned the wrong template state index")
    if state.order_ids != invocation.template_order_ids:
        raise TemplateChainExecutionError("adapter changed template order propagation")
    return state


def _validate_rv_state(
    state: RVState,
    invocation: ChainInvocation,
    state_index: int,
    *,
    role: RVRole,
) -> RVState:
    if type(state) is not RVState:
        raise TemplateChainExecutionError("adapter must return an exact RVState")
    if state.invocation_sha256 != invocation.invocation_sha256:
        raise TemplateChainExecutionError("adapter returned stale RV lineage")
    try:
        state.verify_integrity()
    except TemplateChainDataError as exc:
        raise TemplateChainExecutionError("adapter returned corrupt RV content") from exc
    if state.state_index != state_index or state.role != role:
        raise TemplateChainExecutionError("adapter returned the wrong RV state identity")
    expected_epochs = (
        invocation.training_epoch_ids if role == "training" else invocation.evaluation_epoch_ids
    )
    expected_orders = (
        invocation.template_order_ids if role == "training" else invocation.fit_order_ids
    )
    if state.epoch_ids != expected_epochs or state.order_ids != expected_orders:
        raise TemplateChainExecutionError("adapter changed epoch/order propagation")
    return state


def _noise_scale(
    value: ArrayLike,
    shape: tuple[int, int],
    active_mask: BoolArray,
) -> FloatArray:
    noise = _float_matrix(value, "adjacent_noise_scale")
    if noise.shape != shape:
        raise TemplateChainExecutionError("adjacent noise scale changed template shape")
    if np.any(np.isinf(noise)):
        raise TemplateChainExecutionError("adjacent noise scale contains infinity")
    if np.any(active_mask & (~np.isfinite(noise) | (noise <= 0.0))):
        raise TemplateChainExecutionError(
            "adjacent noise scale must be positive and finite on the frozen mask"
        )
    if np.any(~active_mask & ~np.isnan(noise)):
        raise TemplateChainExecutionError(
            "adjacent noise scale must use NaN outside the frozen mask"
        )
    return noise


def _run_fold_chain(
    training_data: ExposureSet,
    evaluation_data: ExposureSet,
    invocation: ChainInvocation,
    convergence_policy: ConvergencePolicy,
    factory: TemplateChainAdapterFactory,
    freshness_registry: WorkflowFreshnessRegistry,
) -> FoldChainResult:
    session = factory.create_session(invocation)
    token = getattr(session, "session_token", None)
    token = freshness_registry.reserve_session(session, token)

    initial_template = _validate_template_state(
        session.initial_template(training_data, invocation),
        invocation,
        0,
    )
    initial_rv = _validate_rv_state(
        session.fit_training(training_data, initial_template, invocation),
        invocation,
        0,
        role="training",
    )
    frozen_template_mask = initial_template.valid_mask
    frozen_rv_mask = initial_rv.valid_mask
    template_states = [initial_template]
    rv_states = [initial_rv]
    noise_scales: list[FloatArray] = []
    convergence: ConvergenceResult | None = None

    for state_index in range(1, convergence_policy.k_max + 1):
        current_template = _validate_template_state(
            session.update_template(
                training_data,
                template_states[-1],
                rv_states[-1],
                state_index=state_index,
                invocation=invocation,
            ),
            invocation,
            state_index,
        )
        if not np.array_equal(current_template.valid_mask, frozen_template_mask):
            raise TemplateChainExecutionError(
                "template valid mask changed within the frozen full chain"
            )
        current_rv = _validate_rv_state(
            session.fit_training(training_data, current_template, invocation),
            invocation,
            state_index,
            role="training",
        )
        if not np.array_equal(current_rv.valid_mask, frozen_rv_mask):
            raise TemplateChainExecutionError("RV valid mask changed within the frozen full chain")
        noise = _noise_scale(
            session.adjacent_noise_scale(template_states[-1], current_template, invocation),
            current_template.flux.shape,
            frozen_template_mask,
        )
        template_states.append(current_template)
        rv_states.append(current_rv)
        noise_scales.append(noise)
        convergence = evaluate_convergence(
            np.stack([state.flux for state in template_states]),
            np.stack(noise_scales),
            np.stack([state.values for state in rv_states]),
            convergence_policy,
            template_valid_mask=frozen_template_mask,
            rv_valid_mask=frozen_rv_mask,
        )
        if convergence.failure_code == "invalid_data":
            raise TemplateChainExecutionError(
                f"convergence inputs failed closed: {convergence.failure_reason}"
            )
        if convergence.converged:
            break

    if convergence is None:
        raise TemplateChainExecutionError("full chain produced no convergence update")
    evaluation_rv: RVState | None = None
    if convergence.converged:
        final_index = convergence.converged_iteration
        if final_index is None:
            raise TemplateChainExecutionError("converged result lacks an iteration identity")
        final_template = template_states[final_index]
        evaluation_rv = _validate_rv_state(
            session.fit_evaluation(evaluation_data, final_template, invocation),
            invocation,
            final_index,
            role="evaluation",
        )

    return FoldChainResult(
        invocation=invocation,
        session_token=token,
        template_states=tuple(template_states),
        training_rv_states=tuple(rv_states),
        adjacent_template_noise_scales=tuple(noise_scales),
        convergence=convergence,
        evaluation_rv=evaluation_rv,
    )


def run_template_chain_ensemble(
    source: ExposureSet,
    injection_plans: Sequence[PreTemplateInjectionPlan],
    fold_plan: FoldPlan,
    order_plan: OrderPropagationPlan,
    convergence_policy: ConvergencePolicy,
    adapter_factory: TemplateChainAdapterFactory,
    *,
    mask_contract: CrossInjectionMaskContract,
    ensemble_nonce: str,
    freshness_registry: WorkflowFreshnessRegistry,
    cached_artifacts: Sequence[object] | None = None,
) -> TemplateChainEnsembleResult:
    """Rebuild the full chain independently for every injection, arm, and fold.

    ``cached_artifacts`` exists only to make the failure mode explicit.  Any supplied artifact
    is rejected; this control-development runner never reuses a template, RV state, mask, or
    selected arm from another injection.  ``ensemble_nonce`` is a one-use SHA-256 digest and
    ``freshness_registry`` must be retained by the caller for the complete workflow lifetime.
    The registry rejects reused nonces, Python session objects, and tokens across ensemble calls.
    That state and each bound token are wiring evidence, not proof of process isolation or a cold
    rebuild inside an adapter implementation.
    """
    if type(source) is not ExposureSet:
        raise TypeError("source must be an ExposureSet")
    if type(fold_plan) is not FoldPlan:
        raise TypeError("fold_plan must be a FoldPlan")
    if type(order_plan) is not OrderPropagationPlan:
        raise TypeError("order_plan must be an OrderPropagationPlan")
    if type(mask_contract) is not CrossInjectionMaskContract:
        raise TypeError("mask_contract must be a CrossInjectionMaskContract")
    nonce = _digest(ensemble_nonce, "ensemble_nonce")
    if type(freshness_registry) is not WorkflowFreshnessRegistry:
        raise TypeError("freshness_registry must be a WorkflowFreshnessRegistry")
    if not isinstance(convergence_policy, ConvergencePolicy):
        raise TypeError("convergence_policy must be a ConvergencePolicy")
    if cached_artifacts is not None:
        if isinstance(cached_artifacts, (str, bytes)):
            raise TemplateChainDataError("cached_artifacts must be a sequence")
        if tuple(cached_artifacts):
            raise TemplateChainDataError(
                "cache reuse is forbidden; every injection requires a fresh full chain"
            )
    source.verify_integrity()
    if source.epoch_ids != fold_plan.epoch_ids:
        raise TemplateChainDataError("fold plan epochs do not exactly match the source set")
    if source.order_ids != order_plan.available_order_ids:
        raise TemplateChainDataError("order plan does not exactly match the source order set")
    roster = TemplateChainRoster(fold_plan=fold_plan, order_plan=order_plan)
    roster.verify_integrity()
    mask_contract.verify_integrity()
    if mask_contract.roster_sha256 != roster.roster_sha256:
        raise TemplateChainDataError("mask contract does not match the complete arm/fold roster")
    plans = tuple(injection_plans)
    if not plans or any(type(plan) is not PreTemplateInjectionPlan for plan in plans):
        raise TemplateChainDataError(
            "injection_plans must contain exact PreTemplateInjectionPlan values"
        )
    for plan in plans:
        plan.verify_integrity()
    if len({plan.plan_sha256 for plan in plans}) != len(plans):
        raise TemplateChainDataError("injection plans must have distinct content identities")
    if len({plan.velocity_pattern_sha256 for plan in plans}) != len(plans):
        raise TemplateChainDataError(
            "duplicate physical velocity schedules are forbidden in a single-source ensemble; "
            "caller-supplied replicate labels do not establish independent source content"
        )
    if any(plan.epoch_ids != source.epoch_ids for plan in plans):
        raise TemplateChainDataError("an injection plan does not match the source epochs")
    if sum(plan.plan_sha256 == mask_contract.reference_plan_sha256 for plan in plans) != 1:
        raise TemplateChainDataError(
            "mask contract reference plan must identify exactly one supplied plan"
        )
    identity = getattr(adapter_factory, "identity", None)
    if type(identity) is not AdapterIdentity:
        raise TemplateChainDataError("adapter_factory must expose an exact AdapterIdentity")
    convergence_identity = _policy_identity(convergence_policy)
    applied_injections = tuple(apply_pre_template_injection(source, plan) for plan in plans)
    if len({item.exposures.content_sha256 for item in applied_injections}) != len(
        applied_injections
    ):
        raise TemplateChainDataError(
            "duplicate applied exposure content is forbidden in a single-source ensemble"
        )
    freshness_registry.reserve_ensemble_nonce(nonce)
    trials: list[InjectionTrialResult] = []

    for plan, applied in zip(plans, applied_injections, strict=True):
        fold_results: list[FoldChainResult] = []
        roster_index = 0
        for arm in order_plan.arms:
            template_orders = order_plan.template_order_ids_for(arm)
            for fold in fold_plan.folds:
                roster_entry = roster.entries[roster_index]
                roster_index += 1
                invocation = ChainInvocation(
                    ensemble_nonce=nonce,
                    injection_plan_sha256=plan.plan_sha256,
                    applied_injection_sha256=applied.application_sha256,
                    fold_plan_sha256=fold_plan.plan_sha256,
                    order_plan_sha256=order_plan.plan_sha256,
                    convergence_policy_sha256=convergence_identity,
                    adapter_identity_sha256=identity.identity_sha256,
                    roster_entry_sha256=roster_entry.entry_sha256,
                    mask_contract_sha256=mask_contract.contract_sha256,
                    arm_id=arm.arm_id,
                    fold_id=fold.fold_id,
                    training_epoch_ids=fold.training_epoch_ids,
                    evaluation_epoch_ids=fold.evaluation_epoch_ids,
                    template_order_ids=template_orders,
                    fit_order_ids=arm.fit_order_ids,
                )
                training_data = applied.exposures.subset(
                    fold.training_epoch_ids,
                    template_orders,
                )
                evaluation_data = applied.exposures.subset(
                    fold.evaluation_epoch_ids,
                    arm.fit_order_ids,
                )
                fold_results.append(
                    _run_fold_chain(
                        training_data,
                        evaluation_data,
                        invocation,
                        convergence_policy,
                        adapter_factory,
                        freshness_registry,
                    )
                )
                current_identity = getattr(adapter_factory, "identity", None)
                if current_identity != identity:
                    raise TemplateChainExecutionError(
                        "adapter identity changed during the ensemble"
                    )
        trials.append(
            InjectionTrialResult(
                applied_injection=applied,
                roster=roster,
                mask_contract=mask_contract,
                fold_results=tuple(fold_results),
            )
        )
    source.verify_integrity()
    return TemplateChainEnsembleResult(
        ensemble_nonce=nonce,
        source_exposure_sha256=source.content_sha256,
        roster=roster,
        mask_contract=mask_contract,
        trials=tuple(trials),
    )


__all__ = [
    "AdapterIdentity",
    "AppliedInjection",
    "ChainInvocation",
    "ChainRosterEntry",
    "CrossInjectionMaskContract",
    "EpochVelocity",
    "ExposureSet",
    "ExtractionArm",
    "FoldChainResult",
    "FoldPlan",
    "FrozenSpectralExposure",
    "InjectionTrialResult",
    "OrderPropagationPlan",
    "PreTemplateInjectionPlan",
    "RVState",
    "TemplateChainAdapterFactory",
    "TemplateChainDataError",
    "TemplateChainEnsembleResult",
    "TemplateChainError",
    "TemplateChainExecutionError",
    "TemplateChainRoster",
    "TemplateChainSession",
    "TemplateFold",
    "TemplateState",
    "WorkflowFreshnessRegistry",
    "apply_pre_template_injection",
    "make_disjoint_fold_plan",
    "make_leave_one_out_fold_plan",
    "run_template_chain_ensemble",
]
