"""Target-free integration helpers for synthetic M38 calibration campaigns.

This module connects the already-audited template-chain, selection, and period-search
components without choosing scientific thresholds.  It is intentionally limited to the
pure-Python toy controls in :mod:`exosat_rv.m38.synthetic_controls`; it is not a CRIRES+
extraction adapter and cannot qualify an observational control or authorise a target run.

All thresholds, injection banks, uncertainty scales, period grids, and signal-parameter
names are mandatory caller inputs.  The bridge retains the complete template-chain ensemble
and binds the derived selection objects to its content identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from exosat_rv.m38.convergence import ConvergencePolicy
from exosat_rv.m38.period_search import (
    PipelineOutcome,
    PipelineTrial,
    weighted_sinusoid_search,
)
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.selection import (
    ArmAssessment,
    ArmGates,
    ArmRosterEntry,
    AttritionPolicy,
    EquivalenceInterval,
    InjectedResponse,
    InjectionPlan,
    ReferenceResponse,
    SelectionContract,
    apply_hidden_validation,
    estimate_recovery_slope,
    score_injection_responses,
    select_winner,
)
from exosat_rv.m38.synthetic_controls import (
    ToyControlSpecification,
    ToyTemplateAdapterFactory,
    generate_toy_control,
)
from exosat_rv.m38.template_chain import (
    CrossInjectionMaskContract,
    EpochVelocity,
    FoldPlan,
    OrderPropagationPlan,
    PreTemplateInjectionPlan,
    TemplateChainEnsembleResult,
    TemplateChainRoster,
    WorkflowFreshnessRegistry,
    run_template_chain_ensemble,
)

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
OrderCombination = Literal["inverse_variance_mean"]

_SCHEMA_VERSION = 1
_SELECTION_BOOTSTRAP_DOMAIN = 0x4D333853
_HIDDEN_BOOTSTRAP_DOMAIN = 0x4D333848
_NOISE_SEED_DOMAIN = 0x4D33384E
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
_REAL_TYPES = frozenset({int, float}) | _NUMPY_INTEGER_TYPES | _NUMPY_FLOAT_TYPES


class SyntheticCampaignError(ValueError):
    """Raised when target-free campaign evidence is incomplete or inconsistent."""


def _native_label(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise SyntheticCampaignError(f"{name} must be a non-empty native string")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SyntheticCampaignError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _finite_float(value: object, name: str) -> float:
    if type(value) not in _REAL_TYPES:
        raise SyntheticCampaignError(f"{name} must be a finite real number")
    numeric = float(value)
    if not np.isfinite(numeric):
        raise SyntheticCampaignError(f"{name} must be a finite real number")
    return 0.0 if numeric == 0.0 else numeric


def _positive_float(value: object, name: str) -> float:
    numeric = _finite_float(value, name)
    if numeric <= 0.0:
        raise SyntheticCampaignError(f"{name} must be positive")
    return numeric


def _positive_int(value: object, name: str) -> int:
    if type(value) not in ({int} | _NUMPY_INTEGER_TYPES):
        raise SyntheticCampaignError(f"{name} must be a positive integer")
    numeric = int(value)
    if numeric < 1:
        raise SyntheticCampaignError(f"{name} must be a positive integer")
    return numeric


def _labels(values: object, name: str, *, unique: bool = True) -> tuple[str, ...]:
    if type(values) is not tuple or not values:
        raise SyntheticCampaignError(f"{name} must be a non-empty tuple")
    labels = tuple(_native_label(value, name) for value in values)
    if unique and len(set(labels)) != len(labels):
        raise SyntheticCampaignError(f"{name} must not contain duplicates")
    return labels


def _float_tuple(values: object, name: str) -> tuple[float, ...]:
    if type(values) is not tuple or not values:
        raise SyntheticCampaignError(f"{name} must be a non-empty tuple")
    return tuple(_finite_float(value, name) for value in values)


def _array_identity(value: NDArray[np.generic]) -> dict[str, object]:
    contiguous = np.ascontiguousarray(value)
    return {
        "dtype": contiguous.dtype.str,
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
    }


def _float_token(value: float) -> str:
    return (0.0 if value == 0.0 else value).hex()


def _velocity_pattern_identity(plan: InjectionPlan) -> str:
    return canonical_sha256(
        {
            "epoch_velocity": sorted(
                [
                    epoch_id,
                    _float_token(float(plan.velocities[index])),
                ]
                for index, epoch_id in enumerate(plan.epoch_ids)
            )
        }
    )


def selection_plan_identity(
    epoch_ids: tuple[str, ...],
    plans: tuple[InjectionPlan, ...],
) -> str:
    """Return the semantic selection-bank identity used by the selection scorer.

    Labels and input order do not distinguish physically identical velocity schedules.  This
    public helper exists so a hidden bank can be committed before its template chains run.
    """

    epochs = _labels(epoch_ids, "selection-plan epoch_ids")
    if type(plans) is not tuple or not plans:
        raise SyntheticCampaignError("selection plans must be a non-empty tuple")
    if any(type(plan) is not InjectionPlan for plan in plans):
        raise SyntheticCampaignError("selection plans must contain exact InjectionPlan values")
    if any(plan.epoch_ids != epochs for plan in plans):
        raise SyntheticCampaignError("a selection plan does not match the declared epoch roster")
    patterns = tuple(_velocity_pattern_identity(plan) for plan in plans)
    if len(set(patterns)) != len(patterns):
        raise SyntheticCampaignError("selection plans contain duplicate physical schedules")
    return canonical_sha256(
        {
            "epoch_ids": sorted(epochs),
            "velocity_patterns": sorted(patterns),
        }
    )


@dataclass(frozen=True, slots=True)
class RVFrameTransform:
    """Caller-declared conversion from one toy fold/order value to a common m/s frame.

    The toy template adapter emits centroid displacements in native pixel units.  A scale and
    offset are therefore mandatory for every fold/order used downstream.  Offsets must be
    fixed independently of injection content; this object only records that external choice.
    """

    fold_id: str
    order_id: str
    scale_m_s_per_native_unit: float
    offset_m_s: float
    transform_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        fold = _native_label(self.fold_id, "frame-transform fold_id")
        order = _native_label(self.order_id, "frame-transform order_id")
        scale = _positive_float(
            self.scale_m_s_per_native_unit,
            "scale_m_s_per_native_unit",
        )
        offset = _finite_float(self.offset_m_s, "offset_m_s")
        object.__setattr__(self, "fold_id", fold)
        object.__setattr__(self, "order_id", order)
        object.__setattr__(self, "scale_m_s_per_native_unit", scale)
        object.__setattr__(self, "offset_m_s", offset)
        object.__setattr__(self, "transform_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "fold_id": self.fold_id,
                "input_unit": "toy-centroid-pixel",
                "offset_m_s_hex": self.offset_m_s.hex(),
                "order_id": self.order_id,
                "output_unit": "m/s",
                "scale_m_s_per_native_unit_hex": (self.scale_m_s_per_native_unit.hex()),
                "schema_version": _SCHEMA_VERSION,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.transform_sha256:
            raise SyntheticCampaignError("RV-frame transform content hash mismatch")


@dataclass(frozen=True, slots=True)
class RVFrameContract:
    """Content-bound native-to-m/s transforms for one adapter and common frame.

    This is a unit/frame declaration, not a scientific wavelength solution.  In particular,
    leave-one-out folds require caller-derived offsets that place every fold in the same
    frame; the bridge never estimates or silently assumes those offsets.
    """

    adapter_identity_sha256: str
    common_frame_label: str
    transforms: tuple[RVFrameTransform, ...]
    contract_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        adapter = _sha256(self.adapter_identity_sha256, "adapter_identity_sha256")
        frame = _native_label(self.common_frame_label, "common_frame_label")
        transforms = tuple(self.transforms)
        if not transforms or any(type(item) is not RVFrameTransform for item in transforms):
            raise SyntheticCampaignError("transforms must contain exact RVFrameTransform values")
        for item in transforms:
            item.verify_integrity()
        keys = tuple((item.fold_id, item.order_id) for item in transforms)
        if len(set(keys)) != len(keys):
            raise SyntheticCampaignError("RV-frame transforms contain duplicate fold/order keys")
        object.__setattr__(self, "adapter_identity_sha256", adapter)
        object.__setattr__(self, "common_frame_label", frame)
        object.__setattr__(self, "transforms", transforms)
        object.__setattr__(self, "contract_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "adapter_identity_sha256": self.adapter_identity_sha256,
                "common_frame_label": self.common_frame_label,
                "output_unit": "m/s",
                "schema_version": _SCHEMA_VERSION,
                "transform_sha256": sorted(item.recompute_sha256() for item in self.transforms),
            }
        )

    def verify_integrity(self) -> None:
        for item in self.transforms:
            item.verify_integrity()
        if self.recompute_sha256() != self.contract_sha256:
            raise SyntheticCampaignError("RV-frame contract content hash mismatch")

    def transform_for(self, fold_id: str, order_id: str) -> RVFrameTransform:
        """Return the unique declared transform, failing closed on missing coverage."""

        self.verify_integrity()
        key = (
            _native_label(fold_id, "frame lookup fold_id"),
            _native_label(order_id, "frame lookup order_id"),
        )
        matches = tuple(item for item in self.transforms if (item.fold_id, item.order_id) == key)
        if len(matches) != 1:
            raise SyntheticCampaignError(
                f"RV-frame contract does not cover fold/order {key!r} exactly once"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class BridgeUncertaintyContract:
    """Explicit uniform toy uncertainties and epoch-cluster identities.

    Uniform scales keep this first integration slice bounded.  They are wiring inputs, not
    scientifically validated uncertainty estimates or recommended defaults.
    """

    epoch_ids: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    reference_uncertainty_m_s: float
    injected_uncertainty_m_s: float
    response_uncertainty_m_s: float
    contract_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        epochs = _labels(self.epoch_ids, "bridge epoch_ids")
        clusters = _labels(self.cluster_ids, "bridge cluster_ids", unique=False)
        if len(clusters) != len(epochs):
            raise SyntheticCampaignError("cluster_ids must align exactly with epoch_ids")
        reference = _positive_float(
            self.reference_uncertainty_m_s,
            "reference_uncertainty_m_s",
        )
        injected = _positive_float(
            self.injected_uncertainty_m_s,
            "injected_uncertainty_m_s",
        )
        response = _positive_float(
            self.response_uncertainty_m_s,
            "response_uncertainty_m_s",
        )
        object.__setattr__(self, "epoch_ids", epochs)
        object.__setattr__(self, "cluster_ids", clusters)
        object.__setattr__(self, "reference_uncertainty_m_s", reference)
        object.__setattr__(self, "injected_uncertainty_m_s", injected)
        object.__setattr__(self, "response_uncertainty_m_s", response)
        object.__setattr__(self, "contract_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "cluster_ids": list(self.cluster_ids),
                "epoch_ids": list(self.epoch_ids),
                "injected_uncertainty_m_s_hex": self.injected_uncertainty_m_s.hex(),
                "reference_uncertainty_m_s_hex": self.reference_uncertainty_m_s.hex(),
                "response_uncertainty_m_s_hex": self.response_uncertainty_m_s.hex(),
                "schema_version": _SCHEMA_VERSION,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.contract_sha256:
            raise SyntheticCampaignError("bridge uncertainty contract content hash mismatch")


def _evaluation_epoch_ids(fold_plan: FoldPlan) -> tuple[str, ...]:
    epochs = tuple(epoch for fold in fold_plan.folds for epoch in fold.evaluation_epoch_ids)
    if not epochs or len(set(epochs)) != len(epochs):
        raise SyntheticCampaignError(
            "selection bridging requires every evaluation epoch to occur exactly once"
        )
    return epochs


def _trial_arm_matrix(
    ensemble: TemplateChainEnsembleResult,
    trial_index: int,
    arm_id: str,
    frame_contract: RVFrameContract,
) -> tuple[tuple[str, ...], tuple[str, ...], FloatArray, BoolArray, tuple[str, ...]]:
    trial = ensemble.trials[trial_index]
    matches = tuple(
        (entry, result)
        for entry, result in zip(
            ensemble.roster.entries,
            trial.fold_results,
            strict=True,
        )
        if entry.arm_id == arm_id
    )
    if not matches:
        raise SyntheticCampaignError(f"unknown extraction arm: {arm_id!r}")
    order_ids = matches[0][0].fit_order_ids
    epoch_ids: list[str] = []
    rows: list[FloatArray] = []
    masks: list[BoolArray] = []
    result_sha256: list[str] = []
    for entry, result in matches:
        if entry.fit_order_ids != order_ids:
            raise SyntheticCampaignError("fit-order roster changed across template folds")
        if not result.convergence.converged or result.evaluation_rv is None:
            raise SyntheticCampaignError(
                "every bridged template fold must converge and be evaluated"
            )
        state = result.evaluation_rv
        state.verify_integrity()
        if (
            state.epoch_ids != entry.evaluation_epoch_ids
            or state.order_ids != order_ids
            or state.role != "evaluation"
        ):
            raise SyntheticCampaignError("evaluation RV state does not match its roster entry")
        adapter_identity = result.invocation.adapter_identity_sha256
        if adapter_identity != frame_contract.adapter_identity_sha256:
            raise SyntheticCampaignError(
                "RV-frame contract adapter identity does not match the template ensemble"
            )
        native_values = np.array(state.values, copy=True, dtype=np.float64)
        transformed = np.empty_like(native_values)
        for order_index, order_id in enumerate(order_ids):
            transform = frame_contract.transform_for(entry.fold_id, order_id)
            transformed[:, order_index] = (
                native_values[:, order_index] * transform.scale_m_s_per_native_unit
                + transform.offset_m_s
            )
        epoch_ids.extend(state.epoch_ids)
        rows.extend(transformed)
        masks.extend(np.array(state.valid_mask, copy=True, dtype=np.bool_))
        result_sha256.append(result.result_sha256)
    epochs = tuple(epoch_ids)
    if epochs != _evaluation_epoch_ids(ensemble.roster.fold_plan):
        raise SyntheticCampaignError("bridged evaluation epochs do not match the fold plan")
    values = np.asarray(rows, dtype=np.float64)
    valid = np.asarray(masks, dtype=np.bool_)
    return epochs, order_ids, values, valid, tuple(result_sha256)


def _masked_constant(mask: BoolArray, value: float) -> FloatArray:
    return np.where(mask, value, np.nan).astype(np.float64, copy=False)


def _derive_selection_objects(
    ensemble: TemplateChainEnsembleResult,
    arm_id: str,
    uncertainty_contract: BridgeUncertaintyContract,
    frame_contract: RVFrameContract,
) -> tuple[
    ReferenceResponse,
    tuple[InjectionPlan, ...],
    tuple[InjectedResponse, ...],
    tuple[str, ...],
]:
    ensemble.verify_integrity()
    uncertainty_contract.verify_integrity()
    frame_contract.verify_integrity()
    arm = _native_label(arm_id, "arm_id")
    if uncertainty_contract.epoch_ids != ensemble.roster.fold_plan.epoch_ids:
        raise SyntheticCampaignError(
            "uncertainty contract must cover the complete source/fold epoch roster"
        )
    reference_indices = tuple(
        index
        for index, trial in enumerate(ensemble.trials)
        if trial.applied_injection.plan.plan_sha256 == ensemble.mask_contract.reference_plan_sha256
    )
    if len(reference_indices) != 1:
        raise SyntheticCampaignError("ensemble must retain exactly one mask-reference trial")
    reference_index = reference_indices[0]
    reference_plan = ensemble.trials[reference_index].applied_injection.plan
    if any(item.velocity_m_s != 0.0 for item in reference_plan.velocities):
        raise SyntheticCampaignError("selection reference trial must be an exact zero injection")

    epochs, orders, reference_values, reference_mask, reference_hashes = _trial_arm_matrix(
        ensemble,
        reference_index,
        arm,
        frame_contract,
    )
    cluster_by_epoch = dict(
        zip(
            uncertainty_contract.epoch_ids,
            uncertainty_contract.cluster_ids,
            strict=True,
        )
    )
    reference = ReferenceResponse(
        epoch_ids=epochs,
        cluster_ids=tuple(cluster_by_epoch[epoch] for epoch in epochs),
        order_ids=orders,
        rv=reference_values,
        uncertainty=_masked_constant(
            reference_mask,
            uncertainty_contract.reference_uncertainty_m_s,
        ),
        valid_mask=reference_mask,
    )

    plans: list[InjectionPlan] = []
    responses: list[InjectedResponse] = []
    fold_hashes = list(reference_hashes)
    for trial_index, trial in enumerate(ensemble.trials):
        if trial_index == reference_index:
            continue
        pre_template_plan = trial.applied_injection.plan
        velocity_by_epoch = {
            item.epoch_id: item.velocity_m_s for item in pre_template_plan.velocities
        }
        plan = InjectionPlan(
            injection_id=pre_template_plan.plan_sha256,
            epoch_ids=epochs,
            velocities=np.asarray(
                [velocity_by_epoch[epoch] for epoch in epochs],
                dtype=np.float64,
            ),
        )
        if np.all(plan.velocities == 0.0):
            raise SyntheticCampaignError(
                "a non-reference plan becomes zero on the evaluation epoch roster"
            )
        _, trial_orders, values, valid_mask, current_hashes = _trial_arm_matrix(
            ensemble,
            trial_index,
            arm,
            frame_contract,
        )
        if trial_orders != orders:
            raise SyntheticCampaignError("injected and reference fit-order rosters differ")
        plans.append(plan)
        responses.append(
            InjectedResponse(
                injection_id=plan.injection_id,
                epoch_ids=epochs,
                order_ids=orders,
                rv=values,
                uncertainty=_masked_constant(
                    valid_mask,
                    uncertainty_contract.injected_uncertainty_m_s,
                ),
                response_uncertainty=_masked_constant(
                    valid_mask,
                    uncertainty_contract.response_uncertainty_m_s,
                ),
                valid_mask=valid_mask,
            )
        )
        fold_hashes.extend(current_hashes)
    if not plans:
        raise SyntheticCampaignError("selection bridging requires at least one non-reference trial")
    selection_plan_identity(epochs, tuple(plans))
    return reference, tuple(plans), tuple(responses), tuple(fold_hashes)


def _selection_evidence_payload(
    ensemble: TemplateChainEnsembleResult,
    arm_id: str,
    uncertainty_contract: BridgeUncertaintyContract,
    frame_contract: RVFrameContract,
    reference: ReferenceResponse,
    plans: tuple[InjectionPlan, ...],
    responses: tuple[InjectedResponse, ...],
    fold_result_sha256: tuple[str, ...],
) -> dict[str, object]:
    return {
        "arm_id": arm_id,
        "bridge_contract_sha256": uncertainty_contract.recompute_sha256(),
        "common_rv_frame_label": frame_contract.common_frame_label,
        "rv_frame_contract_sha256": frame_contract.recompute_sha256(),
        "rv_unit": "m/s",
        "cluster_ids": list(reference.cluster_ids),
        "ensemble_result_sha256": ensemble.recompute_sha256(),
        "fold_result_sha256": list(fold_result_sha256),
        "injections": [
            {
                "epoch_ids": list(plan.epoch_ids),
                "injection_id": plan.injection_id,
                "response_rv": _array_identity(response.rv),
                "response_uncertainty": _array_identity(response.response_uncertainty),
                "response_valid_mask": _array_identity(response.valid_mask),
                "rv_uncertainty": _array_identity(response.uncertainty),
                "velocities": _array_identity(plan.velocities),
            }
            for plan, response in zip(plans, responses, strict=True)
        ],
        "reference": {
            "epoch_ids": list(reference.epoch_ids),
            "order_ids": list(reference.order_ids),
            "rv": _array_identity(reference.rv),
            "uncertainty": _array_identity(reference.uncertainty),
            "valid_mask": _array_identity(reference.valid_mask),
        },
        "reference_mask_roster_sha256": ensemble.reference_mask_roster_sha256,
        "schema_version": _SCHEMA_VERSION,
        "selection_plan_sha256": selection_plan_identity(reference.epoch_ids, plans),
    }


@dataclass(frozen=True, slots=True)
class SyntheticSelectionEvidence:
    """Selection objects recursively tied to one template-chain ensemble and arm."""

    ensemble: TemplateChainEnsembleResult
    arm_id: str
    uncertainty_contract: BridgeUncertaintyContract
    frame_contract: RVFrameContract
    reference: ReferenceResponse
    injection_plans: tuple[InjectionPlan, ...]
    injected_responses: tuple[InjectedResponse, ...]
    fold_result_sha256: tuple[str, ...]
    bridge_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.ensemble) is not TemplateChainEnsembleResult:
            raise SyntheticCampaignError("ensemble must be an exact TemplateChainEnsembleResult")
        if type(self.uncertainty_contract) is not BridgeUncertaintyContract:
            raise SyntheticCampaignError(
                "uncertainty_contract must be an exact BridgeUncertaintyContract"
            )
        if type(self.frame_contract) is not RVFrameContract:
            raise SyntheticCampaignError("frame_contract must be an exact RVFrameContract")
        arm = _native_label(self.arm_id, "arm_id")
        derived = _derive_selection_objects(
            self.ensemble,
            arm,
            self.uncertainty_contract,
            self.frame_contract,
        )
        reference, plans, responses, fold_hashes = derived
        supplied_payload = _selection_evidence_payload(
            self.ensemble,
            arm,
            self.uncertainty_contract,
            self.frame_contract,
            self.reference,
            tuple(self.injection_plans),
            tuple(self.injected_responses),
            tuple(self.fold_result_sha256),
        )
        derived_payload = _selection_evidence_payload(
            self.ensemble,
            arm,
            self.uncertainty_contract,
            self.frame_contract,
            reference,
            plans,
            responses,
            fold_hashes,
        )
        if canonical_sha256(supplied_payload) != canonical_sha256(derived_payload):
            raise SyntheticCampaignError(
                "selection evidence does not exactly derive from the retained ensemble"
            )
        object.__setattr__(self, "arm_id", arm)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "injection_plans", plans)
        object.__setattr__(self, "injected_responses", responses)
        object.__setattr__(self, "fold_result_sha256", fold_hashes)
        object.__setattr__(self, "bridge_sha256", canonical_sha256(derived_payload))

    @property
    def selection_plan_sha256(self) -> str:
        return selection_plan_identity(self.reference.epoch_ids, self.injection_plans)

    def verify_integrity(self) -> None:
        reference, plans, responses, fold_hashes = _derive_selection_objects(
            self.ensemble,
            self.arm_id,
            self.uncertainty_contract,
            self.frame_contract,
        )
        payload = _selection_evidence_payload(
            self.ensemble,
            self.arm_id,
            self.uncertainty_contract,
            self.frame_contract,
            reference,
            plans,
            responses,
            fold_hashes,
        )
        retained_payload = _selection_evidence_payload(
            self.ensemble,
            self.arm_id,
            self.uncertainty_contract,
            self.frame_contract,
            self.reference,
            tuple(self.injection_plans),
            tuple(self.injected_responses),
            tuple(self.fold_result_sha256),
        )
        expected = canonical_sha256(payload)
        if canonical_sha256(retained_payload) != expected or expected != self.bridge_sha256:
            raise SyntheticCampaignError("synthetic selection bridge content hash mismatch")


def bridge_template_chain_to_selection(
    ensemble: TemplateChainEnsembleResult,
    *,
    arm_id: str,
    uncertainty_contract: BridgeUncertaintyContract,
    frame_contract: RVFrameContract,
) -> SyntheticSelectionEvidence:
    """Derive strict selection inputs for one arm from complete evaluation RV states."""

    reference, plans, responses, fold_hashes = _derive_selection_objects(
        ensemble,
        arm_id,
        uncertainty_contract,
        frame_contract,
    )
    return SyntheticSelectionEvidence(
        ensemble=ensemble,
        arm_id=arm_id,
        uncertainty_contract=uncertainty_contract,
        frame_contract=frame_contract,
        reference=reference,
        injection_plans=plans,
        injected_responses=responses,
        fold_result_sha256=fold_hashes,
    )


@dataclass(frozen=True, slots=True)
class SyntheticInjectionBank:
    """Explicit epoch-aligned nonzero velocity schedules for one toy campaign stage."""

    bank_label: str
    epoch_ids: tuple[str, ...]
    velocity_patterns: tuple[tuple[float, ...], ...]
    bank_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        label = _native_label(self.bank_label, "bank_label")
        epochs = _labels(self.epoch_ids, "bank epoch_ids")
        if type(self.velocity_patterns) is not tuple or not self.velocity_patterns:
            raise SyntheticCampaignError("velocity_patterns must be a non-empty tuple")
        patterns: list[tuple[float, ...]] = []
        for index, value in enumerate(self.velocity_patterns):
            pattern = _float_tuple(value, f"velocity pattern {index}")
            if len(pattern) != len(epochs):
                raise SyntheticCampaignError("every velocity pattern must align with epoch_ids")
            if all(item == 0.0 for item in pattern):
                raise SyntheticCampaignError("a non-reference velocity pattern cannot be all zero")
            patterns.append(pattern)
        physical = tuple(
            canonical_sha256(
                {
                    "epoch_velocity": sorted(
                        [epoch, _float_token(velocity)]
                        for epoch, velocity in zip(epochs, pattern, strict=True)
                    )
                }
            )
            for pattern in patterns
        )
        if len(set(physical)) != len(physical):
            raise SyntheticCampaignError("velocity_patterns contain duplicate physical schedules")
        object.__setattr__(self, "bank_label", label)
        object.__setattr__(self, "epoch_ids", epochs)
        object.__setattr__(self, "velocity_patterns", tuple(patterns))
        object.__setattr__(self, "bank_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "bank_label": self.bank_label,
                "epoch_ids": list(self.epoch_ids),
                "schema_version": _SCHEMA_VERSION,
                "velocity_patterns_hex": [
                    [_float_token(value) for value in pattern] for pattern in self.velocity_patterns
                ],
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.bank_sha256:
            raise SyntheticCampaignError("synthetic injection bank content hash mismatch")

    def projected_selection_plans(
        self,
        evaluation_epoch_ids: tuple[str, ...],
    ) -> tuple[InjectionPlan, ...]:
        self.verify_integrity()
        evaluation = _labels(evaluation_epoch_ids, "evaluation_epoch_ids")
        if not set(evaluation).issubset(self.epoch_ids):
            raise SyntheticCampaignError("evaluation epochs are outside the injection bank")
        epoch_index = {epoch: index for index, epoch in enumerate(self.epoch_ids)}
        plans = tuple(
            InjectionPlan(
                injection_id=canonical_sha256(
                    {
                        "bank_sha256": self.bank_sha256,
                        "pattern_index": pattern_index,
                    }
                ),
                epoch_ids=evaluation,
                velocities=np.asarray(
                    [pattern[epoch_index[epoch]] for epoch in evaluation],
                    dtype=np.float64,
                ),
            )
            for pattern_index, pattern in enumerate(self.velocity_patterns)
        )
        if any(np.all(plan.velocities == 0.0) for plan in plans):
            raise SyntheticCampaignError(
                "a velocity pattern becomes zero on the evaluation epoch roster"
            )
        selection_plan_identity(evaluation, plans)
        return plans

    def verify_pre_template_training_support(self, fold_plan: FoldPlan) -> None:
        """Require non-degenerate signed training support in every configured toy fold.

        This structural rule has no numerical threshold: every non-reference injection must
        place at least one strictly positive and one strictly negative velocity into the
        training data for each fold.  It prevents a nominally pre-template bank from changing
        only evaluation exposures while leaving every injected template flux identical to the
        zero-injection reference.  It is a toy integration invariant, not a scientific design
        recommendation.
        """

        self.verify_integrity()
        if type(fold_plan) is not FoldPlan:
            raise SyntheticCampaignError("fold_plan must be an exact FoldPlan")
        fold_plan.verify_integrity()
        if fold_plan.epoch_ids != self.epoch_ids:
            raise SyntheticCampaignError(
                "injection bank and fold plan must share the exact epoch roster"
            )
        epoch_index = {epoch: index for index, epoch in enumerate(self.epoch_ids)}
        for pattern_index, pattern in enumerate(self.velocity_patterns):
            for fold in fold_plan.folds:
                training = tuple(pattern[epoch_index[epoch]] for epoch in fold.training_epoch_ids)
                if not any(value > 0.0 for value in training) or not any(
                    value < 0.0 for value in training
                ):
                    raise SyntheticCampaignError(
                        "every pre-template injection/fold requires both positive and "
                        "negative training velocities; "
                        f"bank={self.bank_label!r}, pattern={pattern_index}, "
                        f"fold={fold.fold_id!r}"
                    )

    def pre_template_plans(self, *, stage: str) -> tuple[PreTemplateInjectionPlan, ...]:
        self.verify_integrity()
        stage_label = _native_label(stage, "stage")
        zero = PreTemplateInjectionPlan(
            plan_label=f"{self.bank_label}-{stage_label}-reference",
            epoch_ids=self.epoch_ids,
            velocities=tuple(EpochVelocity(epoch, 0.0) for epoch in self.epoch_ids),
        )
        injected = tuple(
            PreTemplateInjectionPlan(
                plan_label=f"{self.bank_label}-{stage_label}-{index:04d}",
                epoch_ids=self.epoch_ids,
                velocities=tuple(
                    EpochVelocity(epoch, velocity)
                    for epoch, velocity in zip(self.epoch_ids, pattern, strict=True)
                ),
            )
            for index, pattern in enumerate(self.velocity_patterns)
        )
        return (zero, *injected)


@dataclass(frozen=True, slots=True)
class SyntheticSinusoidSignalModel:
    """Explicit circular sinusoid for a caller-named three-axis synthetic signal plan."""

    amplitude_parameter: str
    period_parameter: str
    phase_parameter: str
    model_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        names = tuple(
            _native_label(value, name)
            for value, name in (
                (self.amplitude_parameter, "amplitude_parameter"),
                (self.period_parameter, "period_parameter"),
                (self.phase_parameter, "phase_parameter"),
            )
        )
        if len(set(names)) != 3:
            raise SyntheticCampaignError("signal-model parameter names must be distinct")
        object.__setattr__(self, "amplitude_parameter", names[0])
        object.__setattr__(self, "period_parameter", names[1])
        object.__setattr__(self, "phase_parameter", names[2])
        object.__setattr__(
            self,
            "model_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "amplitude_parameter": self.amplitude_parameter,
                "formula": "A*sin(2*pi*(t-min(t))/P+phase_radians)",
                "period_parameter": self.period_parameter,
                "phase_parameter": self.phase_parameter,
                "schema_version": _SCHEMA_VERSION,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.model_sha256:
            raise SyntheticCampaignError("synthetic signal model content hash mismatch")

    def velocities(self, trial: PipelineTrial, times: tuple[float, ...]) -> FloatArray:
        if type(trial) is not PipelineTrial:
            raise SyntheticCampaignError("trial must be an exact PipelineTrial")
        time_values = np.asarray(times, dtype=np.float64)
        if trial.kind == "null":
            return np.zeros(time_values.size, dtype=np.float64)
        parameters = dict(trial.signal_parameters or ())
        expected = {
            self.amplitude_parameter,
            self.period_parameter,
            self.phase_parameter,
        }
        if set(parameters) != expected:
            raise SyntheticCampaignError(
                "signal trial must supply exactly the configured sinusoid parameters"
            )
        amplitude = _finite_float(parameters[self.amplitude_parameter], "signal amplitude")
        if amplitude < 0.0:
            raise SyntheticCampaignError("signal amplitude must be non-negative")
        period = _positive_float(parameters[self.period_parameter], "signal period")
        phase = _finite_float(parameters[self.phase_parameter], "signal phase")
        origin = float(np.min(time_values))
        velocities = amplitude * np.sin(2.0 * np.pi * (time_values - origin) / period + phase)
        if not np.all(np.isfinite(velocities)):
            raise SyntheticCampaignError("synthetic signal velocities became non-finite")
        return np.asarray(velocities, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class SyntheticTemplateRunConfig:
    """Complete toy generator/template-chain configuration with no threshold defaults."""

    specification: ToyControlSpecification
    epoch_times: tuple[float, ...]
    fold_plan: FoldPlan
    order_plan: OrderPropagationPlan
    convergence_policy: ConvergencePolicy
    adapter_label: str
    adapter_relaxation: float
    adjacent_noise_scale: float
    uncertainty_contract: BridgeUncertaintyContract
    frame_contract: RVFrameContract
    config_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.specification) is not ToyControlSpecification:
            raise SyntheticCampaignError("specification must be an exact ToyControlSpecification")
        self.specification.verify_integrity()
        if (
            type(self.fold_plan) is not FoldPlan
            or type(self.order_plan) is not OrderPropagationPlan
        ):
            raise SyntheticCampaignError("fold_plan and order_plan must use exact plan types")
        self.fold_plan.verify_integrity()
        self.order_plan.verify_integrity()
        if type(self.convergence_policy) is not ConvergencePolicy:
            raise SyntheticCampaignError("convergence_policy must be an exact ConvergencePolicy")
        if type(self.uncertainty_contract) is not BridgeUncertaintyContract:
            raise SyntheticCampaignError(
                "uncertainty_contract must be an exact BridgeUncertaintyContract"
            )
        if type(self.frame_contract) is not RVFrameContract:
            raise SyntheticCampaignError("frame_contract must be an exact RVFrameContract")
        self.frame_contract.verify_integrity()
        epochs = tuple(item.epoch_id for item in self.specification.epochs)
        orders = tuple(item.order_id for item in self.specification.orders)
        noise_seeds = tuple(item.noise_seed for item in self.specification.epochs)
        if len(set(noise_seeds)) != len(noise_seeds):
            raise SyntheticCampaignError(
                "toy source epoch noise seeds must be unique before trial derivation"
            )
        if self.fold_plan.epoch_ids != epochs or self.order_plan.available_order_ids != orders:
            raise SyntheticCampaignError(
                "toy specification, fold plan, and order plan rosters must match exactly"
            )
        if self.uncertainty_contract.epoch_ids != epochs:
            raise SyntheticCampaignError("uncertainty contract does not match toy epochs")
        times = _float_tuple(self.epoch_times, "epoch_times")
        if len(times) != len(epochs) or len(set(times)) != len(times):
            raise SyntheticCampaignError("epoch_times must uniquely align with every toy epoch")
        adapter_label = _native_label(self.adapter_label, "adapter_label")
        relaxation = _positive_float(self.adapter_relaxation, "adapter_relaxation")
        if relaxation > 1.0:
            raise SyntheticCampaignError("adapter_relaxation must not exceed one")
        adjacent_noise = _positive_float(self.adjacent_noise_scale, "adjacent_noise_scale")
        adapter_identity = ToyTemplateAdapterFactory(
            adapter_label=adapter_label,
            relaxation=relaxation,
            adjacent_noise_scale=adjacent_noise,
        ).identity.identity_sha256
        if self.frame_contract.adapter_identity_sha256 != adapter_identity:
            raise SyntheticCampaignError(
                "frame contract must bind the exact configured toy adapter identity"
            )
        required_frame_keys = {
            (fold.fold_id, order_id)
            for fold in self.fold_plan.folds
            for order_id in {
                fit_order_id for arm in self.order_plan.arms for fit_order_id in arm.fit_order_ids
            }
        }
        declared_frame_keys = {
            (item.fold_id, item.order_id) for item in self.frame_contract.transforms
        }
        if declared_frame_keys != required_frame_keys:
            raise SyntheticCampaignError(
                "frame contract must exactly cover every fitted fold/order"
            )
        object.__setattr__(self, "epoch_times", times)
        object.__setattr__(self, "adapter_label", adapter_label)
        object.__setattr__(self, "adapter_relaxation", relaxation)
        object.__setattr__(self, "adjacent_noise_scale", adjacent_noise)
        object.__setattr__(self, "config_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        policy = self.convergence_policy
        return canonical_sha256(
            {
                "adapter_label": self.adapter_label,
                "adapter_relaxation_hex": self.adapter_relaxation.hex(),
                "adjacent_noise_scale_hex": self.adjacent_noise_scale.hex(),
                "convergence_policy": {
                    "d_rv_limit_hex": policy.d_rv_limit.hex(),
                    "d_template_limit_hex": policy.d_template_limit.hex(),
                    "k_max": policy.k_max,
                    "q_conv": policy.q_conv,
                    "template_aggregate": policy.template_aggregate,
                },
                "epoch_times_hex": [value.hex() for value in self.epoch_times],
                "fold_plan_sha256": self.fold_plan.recompute_sha256(),
                "frame_contract_sha256": self.frame_contract.recompute_sha256(),
                "order_plan_sha256": self.order_plan.recompute_sha256(),
                "schema_version": _SCHEMA_VERSION,
                "toy_specification_sha256": self.specification.recompute_sha256(),
                "uncertainty_contract_sha256": self.uncertainty_contract.recompute_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        self.specification.verify_integrity()
        self.fold_plan.verify_integrity()
        self.order_plan.verify_integrity()
        self.uncertainty_contract.verify_integrity()
        self.frame_contract.verify_integrity()
        if self.recompute_sha256() != self.config_sha256:
            raise SyntheticCampaignError("synthetic template configuration hash mismatch")


@dataclass(frozen=True, slots=True)
class SyntheticSelectionConfig:
    """Caller-owned selection/hidden banks and statistical contract."""

    selection_bank: SyntheticInjectionBank
    hidden_bank: SyntheticInjectionBank
    attrition_policy: AttritionPolicy
    equivalence_interval: EquivalenceInterval
    bootstrap_repetitions: int
    confidence_level: float
    minimum_independent_clusters: int
    config_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.selection_bank) is not SyntheticInjectionBank
            or type(self.hidden_bank) is not SyntheticInjectionBank
        ):
            raise SyntheticCampaignError("selection and hidden banks must use exact bank types")
        if self.selection_bank.epoch_ids != self.hidden_bank.epoch_ids:
            raise SyntheticCampaignError("selection and hidden banks must share one epoch roster")
        selection_patterns = {
            canonical_sha256([_float_token(value) for value in pattern])
            for pattern in self.selection_bank.velocity_patterns
        }
        hidden_patterns = {
            canonical_sha256([_float_token(value) for value in pattern])
            for pattern in self.hidden_bank.velocity_patterns
        }
        if not selection_patterns.isdisjoint(hidden_patterns):
            raise SyntheticCampaignError("selection and hidden banks must be physically disjoint")
        if type(self.attrition_policy) is not AttritionPolicy:
            raise SyntheticCampaignError("attrition_policy must be an exact AttritionPolicy")
        if type(self.equivalence_interval) is not EquivalenceInterval:
            raise SyntheticCampaignError(
                "equivalence_interval must be an exact EquivalenceInterval"
            )
        repetitions = _positive_int(self.bootstrap_repetitions, "bootstrap_repetitions")
        confidence = _finite_float(self.confidence_level, "confidence_level")
        if not 0.0 < confidence < 1.0:
            raise SyntheticCampaignError("confidence_level must lie strictly between zero and one")
        clusters = _positive_int(
            self.minimum_independent_clusters,
            "minimum_independent_clusters",
        )
        if clusters < 2:
            raise SyntheticCampaignError("minimum_independent_clusters must be at least two")
        object.__setattr__(self, "bootstrap_repetitions", repetitions)
        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "minimum_independent_clusters", clusters)
        object.__setattr__(self, "config_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        policy = self.attrition_policy
        return canonical_sha256(
            {
                "attrition_policy": {
                    "attrition_action": policy.attrition_action,
                    "maximum_lost_fraction_hex": policy.maximum_lost_fraction.hex(),
                    "maximum_lost_orders": policy.maximum_lost_orders,
                    "minimum_common_orders": policy.minimum_common_orders,
                    "minimum_reference_orders": policy.minimum_reference_orders,
                },
                "bootstrap_repetitions": self.bootstrap_repetitions,
                "confidence_level_hex": self.confidence_level.hex(),
                "equivalence_delta_hex": self.equivalence_interval.delta.hex(),
                "hidden_bank_sha256": self.hidden_bank.recompute_sha256(),
                "minimum_independent_clusters": self.minimum_independent_clusters,
                "schema_version": _SCHEMA_VERSION,
                "selection_bank_sha256": self.selection_bank.recompute_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        self.selection_bank.verify_integrity()
        self.hidden_bank.verify_integrity()
        if self.recompute_sha256() != self.config_sha256:
            raise SyntheticCampaignError("synthetic selection configuration hash mismatch")


@dataclass(frozen=True, slots=True)
class SyntheticSearchConfig:
    """Explicit period-search design for the toy whole-pipeline callback."""

    periods: tuple[float, ...]
    order_combination: OrderCombination
    include_intercept: bool
    reference_time: float | None
    rcond: float | None
    nuisance_regressors: object
    config_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        periods = _float_tuple(self.periods, "periods")
        if any(value <= 0.0 for value in periods) or any(
            current <= previous for previous, current in pairwise(periods)
        ):
            raise SyntheticCampaignError("periods must be positive and strictly increasing")
        if type(self.order_combination) is not str or self.order_combination != (
            "inverse_variance_mean"
        ):
            raise SyntheticCampaignError(
                "order_combination must be explicitly 'inverse_variance_mean'"
            )
        if type(self.include_intercept) is not bool:
            raise SyntheticCampaignError("include_intercept must be a native boolean")
        reference_time = (
            None
            if self.reference_time is None
            else _finite_float(self.reference_time, "reference_time")
        )
        rcond = None if self.rcond is None else _positive_float(self.rcond, "rcond")
        nuisance: FloatArray | None
        if self.nuisance_regressors is None:
            nuisance = None
        else:
            try:
                nuisance = np.array(
                    self.nuisance_regressors,
                    dtype=np.float64,
                    copy=True,
                    order="C",
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise SyntheticCampaignError(
                    "nuisance_regressors must be a finite two-dimensional array"
                ) from exc
            if nuisance.ndim != 2 or 0 in nuisance.shape or not np.all(np.isfinite(nuisance)):
                raise SyntheticCampaignError(
                    "nuisance_regressors must be a finite two-dimensional array"
                )
            contiguous = np.ascontiguousarray(nuisance, dtype=np.float64)
            nuisance = np.frombuffer(contiguous.tobytes(order="C"), dtype=np.float64).reshape(
                contiguous.shape
            )
        object.__setattr__(self, "periods", periods)
        object.__setattr__(self, "reference_time", reference_time)
        object.__setattr__(self, "rcond", rcond)
        object.__setattr__(self, "nuisance_regressors", nuisance)
        object.__setattr__(self, "config_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        nuisance = self.nuisance_regressors
        return canonical_sha256(
            {
                "include_intercept": self.include_intercept,
                "nuisance_regressors": (None if nuisance is None else _array_identity(nuisance)),
                "order_combination": self.order_combination,
                "periods_hex": [value.hex() for value in self.periods],
                "rcond_hex": None if self.rcond is None else self.rcond.hex(),
                "reference_time_hex": (
                    None if self.reference_time is None else self.reference_time.hex()
                ),
                "schema_version": _SCHEMA_VERSION,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.config_sha256:
            raise SyntheticCampaignError("synthetic search configuration hash mismatch")


def _derived_seed(master_seed: int, domain: int, index: int = 0) -> int:
    sequence = np.random.SeedSequence([int(master_seed), domain, index])
    return int(sequence.generate_state(1, dtype=np.uint64)[0])


def _derived_noise_seed(
    trial_seed: int,
    source_noise_seed: int,
    epoch_id: str,
    epoch_index: int,
) -> int:
    """Derive one epoch seed from separately represented, content-bound entropy fields."""

    epoch = _native_label(epoch_id, "noise-seed epoch_id")
    epoch_digest = bytes.fromhex(canonical_sha256({"epoch_id": epoch}))
    epoch_words = tuple(
        int.from_bytes(epoch_digest[offset : offset + 4], "big") for offset in range(0, 32, 4)
    )
    sequence = np.random.SeedSequence(
        [
            int(trial_seed),
            _NOISE_SEED_DOMAIN,
            int(source_noise_seed),
            int(epoch_index),
            *epoch_words,
        ]
    )
    return int(sequence.generate_state(1, dtype=np.uint64)[0])


def _verify_nonreference_template_flux_changes(
    ensemble: TemplateChainEnsembleResult,
) -> None:
    """Fail when a nominal pre-template injection leaves any final toy template unchanged."""

    ensemble.verify_integrity()
    reference_trials = tuple(
        item
        for item in ensemble.trials
        if item.applied_injection.plan.plan_sha256 == ensemble.mask_contract.reference_plan_sha256
    )
    if len(reference_trials) != 1:
        raise SyntheticCampaignError(
            "template-change validation requires exactly one reference trial"
        )
    reference = reference_trials[0]
    for injected in ensemble.trials:
        if injected is reference:
            continue
        for entry, reference_fold, injected_fold in zip(
            ensemble.roster.entries,
            reference.fold_results,
            injected.fold_results,
            strict=True,
        ):
            reference_index = reference_fold.convergence.converged_iteration
            injected_index = injected_fold.convergence.converged_iteration
            if (
                not reference_fold.convergence.converged
                or not injected_fold.convergence.converged
                or reference_index is None
                or injected_index is None
            ):
                raise SyntheticCampaignError(
                    "template-change validation requires every compared fold to converge"
                )
            reference_template = reference_fold.template_states[reference_index]
            injected_template = injected_fold.template_states[injected_index]
            reference_template.verify_integrity()
            injected_template.verify_integrity()
            if reference_template.order_ids != injected_template.order_ids or not np.array_equal(
                reference_template.valid_mask,
                injected_template.valid_mask,
            ):
                raise SyntheticCampaignError(
                    "final template order/mask roster drifted across injections"
                )
            active = reference_template.valid_mask
            if np.array_equal(
                reference_template.flux[active],
                injected_template.flux[active],
            ):
                raise SyntheticCampaignError(
                    "a non-reference pre-template injection did not alter final template "
                    f"flux for arm={entry.arm_id!r}, fold={entry.fold_id!r}"
                )


def _configuration_identity(
    template_config: SyntheticTemplateRunConfig,
    arm_id: str,
) -> str:
    arm = next(
        (value for value in template_config.order_plan.arms if value.arm_id == arm_id),
        None,
    )
    if arm is None:
        raise SyntheticCampaignError(f"unknown extraction arm: {arm_id!r}")
    return canonical_sha256(
        {
            "arm_id": arm.arm_id,
            "fit_order_ids": list(arm.fit_order_ids),
            "template_config_sha256": template_config.config_sha256,
            "template_order_ids": list(template_config.order_plan.template_order_ids_for(arm)),
        }
    )


@dataclass(frozen=True, slots=True)
class ToyStructuralGateEvaluation:
    """Caller-supplied, identity-bound checks scoped only to a toy integration run.

    ``structural_gates`` use :class:`ArmGates` solely because the existing selector consumes
    that record.  Passing them authorises only an in-memory synthetic wiring decision.  This
    result always records that scientific use is unresolved and unauthorised; it must never
    be presented as observational gate evidence.
    """

    evaluator_identity_sha256: str
    evidence_bridge_sha256: str
    arm_id: str
    configuration_identity: str
    assessment_stage: Literal["selection", "hidden_validation"]
    structural_gates: ArmGates
    scope: Literal["toy_structural_only"] = field(
        init=False,
        default="toy_structural_only",
    )
    scientific_gate_status: Literal["unresolved"] = field(
        init=False,
        default="unresolved",
    )
    scientific_use_authorized: Literal[False] = field(init=False, default=False)
    evaluation_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        evaluator = _sha256(
            self.evaluator_identity_sha256,
            "gate evaluator_identity_sha256",
        )
        evidence = _sha256(self.evidence_bridge_sha256, "gate evidence_bridge_sha256")
        arm = _native_label(self.arm_id, "gate arm_id")
        configuration = _sha256(
            self.configuration_identity,
            "gate configuration_identity",
        )
        if type(self.assessment_stage) is not str or self.assessment_stage not in (
            "selection",
            "hidden_validation",
        ):
            raise SyntheticCampaignError(
                "gate assessment_stage must be 'selection' or 'hidden_validation'"
            )
        if type(self.structural_gates) is not ArmGates:
            raise SyntheticCampaignError("structural_gates must be an exact ArmGates value")
        object.__setattr__(self, "evaluator_identity_sha256", evaluator)
        object.__setattr__(self, "evidence_bridge_sha256", evidence)
        object.__setattr__(self, "arm_id", arm)
        object.__setattr__(self, "configuration_identity", configuration)
        object.__setattr__(self, "evaluation_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        gates = self.structural_gates
        return {
            "arm_id": self.arm_id,
            "assessment_stage": self.assessment_stage,
            "configuration_identity": self.configuration_identity,
            "evaluator_identity_sha256": self.evaluator_identity_sha256,
            "evidence_bridge_sha256": self.evidence_bridge_sha256,
            "scientific_gate_status": "unresolved",
            "scientific_use_authorized": False,
            "schema_version": _SCHEMA_VERSION,
            "scope": "toy_structural_only",
            "structural_gates": {
                "catastrophic_fit_checks_passed": gates.catastrophic_fit_checks_passed,
                "fit_quality_passed": gates.fit_quality_passed,
                "injection_runs_complete": gates.injection_runs_complete,
                "per_order_stability_passed": gates.per_order_stability_passed,
                "provenance_valid": gates.provenance_valid,
                "reference_run_complete": gates.reference_run_complete,
                "template_convergence_complete": gates.template_convergence_complete,
            },
        }

    def identity_payload(self) -> dict[str, object]:
        """Return a fresh strict-JSON payload for recursive outcome binding."""

        self.verify_integrity()
        return {
            **self._identity_payload(),
            "evaluation_sha256": self.evaluation_sha256,
        }

    def verify_integrity(self) -> None:
        if (
            self.scope != "toy_structural_only"
            or self.scientific_gate_status != "unresolved"
            or self.scientific_use_authorized is not False
        ):
            raise SyntheticCampaignError(
                "toy structural gate evaluation cannot authorise scientific use"
            )
        if self.recompute_sha256() != self.evaluation_sha256:
            raise SyntheticCampaignError("toy structural gate evaluation hash mismatch")


@dataclass(frozen=True, slots=True)
class ToyArmAssessment(ArmAssessment):
    """A toy-scoped carrier accepted by the existing selection utilities.

    The upstream selection evidence identity covers only base ``ArmAssessment`` fields, so
    this subclass is not a standalone anti-substitution guarantee.  The callback verifies the
    exact subclass and recursively includes its gate evaluation in the returned decision trace.
    """

    gate_evaluation: ToyStructuralGateEvaluation
    scope: Literal["toy_structural_only"] = field(
        init=False,
        default="toy_structural_only",
    )
    scientific_gate_status: Literal["unresolved"] = field(
        init=False,
        default="unresolved",
    )
    scientific_use_authorized: Literal[False] = field(init=False, default=False)

    def __post_init__(self) -> None:
        ArmAssessment.__post_init__(self)
        if type(self.gate_evaluation) is not ToyStructuralGateEvaluation:
            raise SyntheticCampaignError(
                "gate_evaluation must be an exact ToyStructuralGateEvaluation"
            )
        self.gate_evaluation.verify_integrity()
        if (
            self.gate_evaluation.arm_id != self.arm_id
            or self.gate_evaluation.configuration_identity != self.configuration_identity
            or self.gate_evaluation.assessment_stage != self.assessment_stage
            or self.gate_evaluation.structural_gates != self.gates
        ):
            raise SyntheticCampaignError(
                "toy arm assessment does not match its scoped gate evaluation"
            )
        if (
            self.scope != "toy_structural_only"
            or self.scientific_gate_status != "unresolved"
            or self.scientific_use_authorized is not False
        ):
            raise SyntheticCampaignError("toy arm assessment cannot authorise scientific use")


@dataclass(frozen=True, slots=True)
class SyntheticExecutionRecord:
    """One observable arm/fold/injection execution in the synthetic callback."""

    trial_id: str
    stage: Literal["selection", "hidden-validation"]
    arm_id: str
    fold_id: str
    injection_plan_sha256: str
    invocation_sha256: str
    record_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        trial = _native_label(self.trial_id, "execution trial_id")
        if type(self.stage) is not str or self.stage not in (
            "selection",
            "hidden-validation",
        ):
            raise SyntheticCampaignError("execution stage is unsupported")
        arm = _native_label(self.arm_id, "execution arm_id")
        fold = _native_label(self.fold_id, "execution fold_id")
        plan = _sha256(self.injection_plan_sha256, "execution injection_plan_sha256")
        invocation = _sha256(self.invocation_sha256, "execution invocation_sha256")
        object.__setattr__(self, "trial_id", trial)
        object.__setattr__(self, "arm_id", arm)
        object.__setattr__(self, "fold_id", fold)
        object.__setattr__(self, "injection_plan_sha256", plan)
        object.__setattr__(self, "invocation_sha256", invocation)
        object.__setattr__(self, "record_sha256", self.recompute_sha256())

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "arm_id": self.arm_id,
                "fold_id": self.fold_id,
                "injection_plan_sha256": self.injection_plan_sha256,
                "invocation_sha256": self.invocation_sha256,
                "stage": self.stage,
                "trial_id": self.trial_id,
            }
        )

    def verify_integrity(self) -> None:
        if self.recompute_sha256() != self.record_sha256:
            raise SyntheticCampaignError("synthetic execution record hash mismatch")


class SyntheticWholePipelineCallback:
    """Fresh toy template-selection-validation-search callback for adaptive calibration.

    This is a concrete ``WholePipelineCallback``: every invocation regenerates toy noise,
    applies any signal before template iteration zero, rebuilds selection and hidden template
    chains, scores and selects the declared arm roster, validates only the winner, and runs the
    explicit period grid.  It remains a wiring/algorithm integration control, not evidence of
    detector-level injection, VIPER behavior, process isolation, or scientific adequacy.
    """

    def __init__(
        self,
        template_config: SyntheticTemplateRunConfig,
        selection_config: SyntheticSelectionConfig,
        search_config: SyntheticSearchConfig,
        signal_model: SyntheticSinusoidSignalModel,
        *,
        declared_implementation_build_sha256: str,
        gate_evaluator: object,
        gate_evaluator_identity_sha256: str,
    ) -> None:
        if type(template_config) is not SyntheticTemplateRunConfig:
            raise SyntheticCampaignError(
                "template_config must be an exact SyntheticTemplateRunConfig"
            )
        if type(selection_config) is not SyntheticSelectionConfig:
            raise SyntheticCampaignError(
                "selection_config must be an exact SyntheticSelectionConfig"
            )
        if type(search_config) is not SyntheticSearchConfig:
            raise SyntheticCampaignError("search_config must be an exact SyntheticSearchConfig")
        if type(signal_model) is not SyntheticSinusoidSignalModel:
            raise SyntheticCampaignError(
                "signal_model must be an exact SyntheticSinusoidSignalModel"
            )
        declared_implementation = _sha256(
            declared_implementation_build_sha256,
            "declared_implementation_build_sha256",
        )
        evaluator_identity = _sha256(
            gate_evaluator_identity_sha256,
            "gate_evaluator_identity_sha256",
        )
        if not callable(gate_evaluator):
            raise SyntheticCampaignError("gate_evaluator must be callable")
        epochs = tuple(item.epoch_id for item in template_config.specification.epochs)
        if (
            selection_config.selection_bank.epoch_ids != epochs
            or selection_config.hidden_bank.epoch_ids != epochs
        ):
            raise SyntheticCampaignError("injection banks must match the toy epoch roster")
        selection_config.selection_bank.verify_pre_template_training_support(
            template_config.fold_plan
        )
        selection_config.hidden_bank.verify_pre_template_training_support(template_config.fold_plan)
        evaluation_epochs = _evaluation_epoch_ids(template_config.fold_plan)
        projected_selection = selection_config.selection_bank.projected_selection_plans(
            evaluation_epochs
        )
        projected_hidden = selection_config.hidden_bank.projected_selection_plans(evaluation_epochs)
        selection_patterns = {_velocity_pattern_identity(plan) for plan in projected_selection}
        hidden_patterns = {_velocity_pattern_identity(plan) for plan in projected_hidden}
        if not selection_patterns.isdisjoint(hidden_patterns):
            raise SyntheticCampaignError(
                "selection and hidden banks must remain disjoint on evaluation epochs"
            )
        nuisance = search_config.nuisance_regressors
        if nuisance is not None and nuisance.shape[0] != len(epochs):
            raise SyntheticCampaignError(
                "nuisance_regressors rows must align with the complete toy epoch roster"
            )
        self._template = template_config
        self._selection = selection_config
        self._search = search_config
        self._signal_model = signal_model
        self._declared_implementation_build_sha256 = declared_implementation
        self._gate_evaluator = gate_evaluator
        self._gate_evaluator_identity_sha256 = evaluator_identity
        self._freshness = WorkflowFreshnessRegistry()
        self._execution_records: list[SyntheticExecutionRecord] = []
        self._configuration_sha256 = canonical_sha256(
            {
                "gate_evaluator_identity_sha256": evaluator_identity,
                "schema_version": _SCHEMA_VERSION,
                "search_config_sha256": search_config.config_sha256,
                "selection_config_sha256": selection_config.config_sha256,
                "signal_model_sha256": signal_model.model_sha256,
                "template_config_sha256": template_config.config_sha256,
            }
        )
        self._pipeline_identity_sha256 = canonical_sha256(
            {
                "configuration_sha256": self._configuration_sha256,
                "declared_implementation_build_sha256": declared_implementation,
            }
        )

    @property
    def configuration_sha256(self) -> str:
        """Content identity of caller configuration, excluding implementation code."""

        self._verify_integrity()
        return self._configuration_sha256

    @property
    def declared_implementation_build_sha256(self) -> str:
        """Caller-declared build digest; independent evidence must verify the declaration."""

        self._verify_integrity()
        return self._declared_implementation_build_sha256

    @property
    def pipeline_identity_sha256(self) -> str:
        """Bind configuration to a caller-declared build digest requiring external verification."""

        self._verify_integrity()
        return self._pipeline_identity_sha256

    @property
    def execution_records(self) -> tuple[SyntheticExecutionRecord, ...]:
        """Return callback-owned instrumentation reporting synthetic arm-slot execution."""

        records = tuple(self._execution_records)
        for record in records:
            record.verify_integrity()
        return records

    def _verify_integrity(self) -> None:
        self._template.verify_integrity()
        self._selection.verify_integrity()
        self._selection.selection_bank.verify_pre_template_training_support(
            self._template.fold_plan
        )
        self._selection.hidden_bank.verify_pre_template_training_support(self._template.fold_plan)
        self._search.verify_integrity()
        self._signal_model.verify_integrity()
        expected_configuration = canonical_sha256(
            {
                "gate_evaluator_identity_sha256": self._gate_evaluator_identity_sha256,
                "schema_version": _SCHEMA_VERSION,
                "search_config_sha256": self._search.config_sha256,
                "selection_config_sha256": self._selection.config_sha256,
                "signal_model_sha256": self._signal_model.model_sha256,
                "template_config_sha256": self._template.config_sha256,
            }
        )
        expected_pipeline = canonical_sha256(
            {
                "configuration_sha256": expected_configuration,
                "declared_implementation_build_sha256": (
                    self._declared_implementation_build_sha256
                ),
            }
        )
        if expected_configuration != self._configuration_sha256:
            raise SyntheticCampaignError("synthetic callback configuration identity mismatch")
        if expected_pipeline != self._pipeline_identity_sha256:
            raise SyntheticCampaignError("synthetic whole-pipeline identity mismatch")

    def _trial_control(self, trial: PipelineTrial):
        signal = self._signal_model.velocities(trial, self._template.epoch_times)
        derived_noise_seeds = tuple(
            _derived_noise_seed(
                trial.trial_seed,
                specification.noise_seed,
                specification.epoch_id,
                index,
            )
            for index, specification in enumerate(self._template.specification.epochs)
        )
        if len(set(derived_noise_seeds)) != len(derived_noise_seeds):
            raise SyntheticCampaignError(
                "derived trial noise seeds collide across distinct epoch identities"
            )
        epochs = tuple(
            replace(
                specification,
                baseline_velocity_m_s=(specification.baseline_velocity_m_s + float(signal[index])),
                noise_seed=derived_noise_seeds[index],
            )
            for index, specification in enumerate(self._template.specification.epochs)
        )
        specification = replace(self._template.specification, epochs=epochs)
        return generate_toy_control(specification)

    def _run_ensemble(
        self,
        source,
        bank: SyntheticInjectionBank,
        *,
        trial: PipelineTrial,
        stage: Literal["selection", "hidden-validation"],
        order_plan: OrderPropagationPlan | None = None,
    ) -> TemplateChainEnsembleResult:
        bank.verify_pre_template_training_support(self._template.fold_plan)
        plans = bank.pre_template_plans(stage=stage)
        effective_order_plan = self._template.order_plan if order_plan is None else order_plan
        if type(effective_order_plan) is not OrderPropagationPlan:
            raise SyntheticCampaignError("order_plan must be an exact OrderPropagationPlan")
        effective_order_plan.verify_integrity()
        roster = TemplateChainRoster(
            fold_plan=self._template.fold_plan,
            order_plan=effective_order_plan,
        )
        contract = CrossInjectionMaskContract(
            reference_plan_sha256=plans[0].plan_sha256,
            roster_sha256=roster.roster_sha256,
        )
        factory = ToyTemplateAdapterFactory(
            adapter_label=self._template.adapter_label,
            relaxation=self._template.adapter_relaxation,
            adjacent_noise_scale=self._template.adjacent_noise_scale,
        )
        nonce = canonical_sha256(
            {
                "pipeline_identity_sha256": self.pipeline_identity_sha256,
                "stage": stage,
                "trial_id": trial.trial_id,
            }
        )
        result = run_template_chain_ensemble(
            source,
            plans,
            self._template.fold_plan,
            effective_order_plan,
            self._template.convergence_policy,
            factory,
            mask_contract=contract,
            ensemble_nonce=nonce,
            freshness_registry=self._freshness,
        )
        _verify_nonreference_template_flux_changes(result)
        for injection_trial in result.trials:
            for entry, fold_result in zip(
                result.roster.entries,
                injection_trial.fold_results,
                strict=True,
            ):
                self._execution_records.append(
                    SyntheticExecutionRecord(
                        trial_id=trial.trial_id,
                        stage=stage,
                        arm_id=entry.arm_id,
                        fold_id=entry.fold_id,
                        injection_plan_sha256=(injection_trial.applied_injection.plan.plan_sha256),
                        invocation_sha256=fold_result.invocation.invocation_sha256,
                    )
                )
        return result

    def _arm_assessment(
        self,
        evidence: SyntheticSelectionEvidence,
        *,
        configuration_index: int,
        bootstrap_seed: int,
        stage: Literal["selection", "hidden_validation"],
    ):
        score = score_injection_responses(
            evidence.reference,
            evidence.injection_plans,
            evidence.injected_responses,
            self._selection.attrition_policy,
        )
        estimate = estimate_recovery_slope(
            score,
            seed=bootstrap_seed,
            repetitions=self._selection.bootstrap_repetitions,
            confidence_level=self._selection.confidence_level,
            minimum_independent_clusters=self._selection.minimum_independent_clusters,
        )
        configuration_identity = _configuration_identity(self._template, evidence.arm_id)
        gate_evaluation = self._gate_evaluator(
            evidence,
            configuration_identity,
            stage,
        )
        if type(gate_evaluation) is not ToyStructuralGateEvaluation:
            raise SyntheticCampaignError(
                "gate_evaluator must return an exact ToyStructuralGateEvaluation"
            )
        gate_evaluation.verify_integrity()
        expected_binding = (
            self._gate_evaluator_identity_sha256,
            evidence.bridge_sha256,
            evidence.arm_id,
            configuration_identity,
            stage,
        )
        actual_binding = (
            gate_evaluation.evaluator_identity_sha256,
            gate_evaluation.evidence_bridge_sha256,
            gate_evaluation.arm_id,
            gate_evaluation.configuration_identity,
            gate_evaluation.assessment_stage,
        )
        if actual_binding != expected_binding:
            raise SyntheticCampaignError(
                "toy structural gate evaluation is not bound to this exact assessment"
            )
        assessment = ToyArmAssessment(
            arm_id=evidence.arm_id,
            configuration_index=configuration_index,
            configuration_identity=configuration_identity,
            assessment_stage=stage,
            score=score,
            estimate=estimate,
            equivalence_interval=self._selection.equivalence_interval,
            gates=gate_evaluation.structural_gates,
            gate_evaluation=gate_evaluation,
        )
        return assessment, gate_evaluation

    def __call__(self, trial: PipelineTrial, /) -> PipelineOutcome:
        if type(trial) is not PipelineTrial:
            raise SyntheticCampaignError("trial must be an exact PipelineTrial")
        self._verify_integrity()
        control = self._trial_control(trial)
        selection_ensemble = self._run_ensemble(
            control.exposures,
            self._selection.selection_bank,
            trial=trial,
            stage="selection",
        )
        selection_seed = _derived_seed(trial.trial_seed, _SELECTION_BOOTSTRAP_DOMAIN)
        evidence_by_arm = tuple(
            bridge_template_chain_to_selection(
                selection_ensemble,
                arm_id=arm.arm_id,
                uncertainty_contract=self._template.uncertainty_contract,
                frame_contract=self._template.frame_contract,
            )
            for arm in self._template.order_plan.arms
        )
        assessment_results = tuple(
            self._arm_assessment(
                evidence,
                configuration_index=index,
                bootstrap_seed=selection_seed,
                stage="selection",
            )
            for index, evidence in enumerate(evidence_by_arm)
        )
        assessments = tuple(item[0] for item in assessment_results)
        selection_gate_evaluations = tuple(item[1] for item in assessment_results)
        evaluation_epochs = evidence_by_arm[0].reference.epoch_ids
        hidden_plans = self._selection.hidden_bank.projected_selection_plans(evaluation_epochs)
        hidden_plan_sha256 = selection_plan_identity(evaluation_epochs, hidden_plans)
        hidden_seed = _derived_seed(trial.trial_seed, _HIDDEN_BOOTSTRAP_DOMAIN)
        selection = select_winner(
            assessments,
            SelectionContract(
                expected_arms=tuple(
                    ArmRosterEntry(
                        arm_id=assessment.arm_id,
                        configuration_index=assessment.configuration_index,
                        configuration_identity=assessment.configuration_identity,
                    )
                    for assessment in assessments
                ),
                expected_hidden_plan_id=hidden_plan_sha256,
                expected_hidden_bootstrap_seed=hidden_seed,
            ),
        )
        if type(selection.winner) is not ToyArmAssessment or any(
            type(item) is not ToyArmAssessment for item in selection.all_assessments
        ):
            raise SyntheticCampaignError(
                "synthetic selection lost its mandatory toy assessment scope"
            )

        winner_arm = next(
            arm for arm in self._template.order_plan.arms if arm.arm_id == selection.winner.arm_id
        )
        winner_only_order_plan = OrderPropagationPlan(
            mode=self._template.order_plan.mode,
            available_order_ids=self._template.order_plan.available_order_ids,
            arms=(winner_arm,),
            common_template_order_ids=self._template.order_plan.common_template_order_ids,
        )
        hidden_ensemble = self._run_ensemble(
            control.exposures,
            self._selection.hidden_bank,
            trial=trial,
            stage="hidden-validation",
            order_plan=winner_only_order_plan,
        )
        hidden_evidence = bridge_template_chain_to_selection(
            hidden_ensemble,
            arm_id=selection.winner.arm_id,
            uncertainty_contract=self._template.uncertainty_contract,
            frame_contract=self._template.frame_contract,
        )
        if hidden_evidence.selection_plan_sha256 != hidden_plan_sha256:
            raise SyntheticCampaignError("executed hidden bank differs from its commitment")
        hidden_assessment, hidden_gate_evaluation = self._arm_assessment(
            hidden_evidence,
            configuration_index=selection.winner.configuration_index,
            bootstrap_seed=hidden_seed,
            stage="hidden_validation",
        )
        validation = apply_hidden_validation(selection, hidden_assessment)
        if type(validation.hidden_assessment) is not ToyArmAssessment:
            raise SyntheticCampaignError(
                "synthetic hidden validation lost its mandatory toy assessment scope"
            )
        if not validation.passed:
            raise SyntheticCampaignError("selected toy arm failed hidden validation")

        selected_evidence = next(
            item for item in evidence_by_arm if item.arm_id == selection.winner.arm_id
        )
        reference = selected_evidence.reference
        weights = np.where(
            reference.valid_mask,
            1.0 / np.square(reference.uncertainty),
            0.0,
        )
        weight_sum = np.sum(weights, axis=1)
        if np.any(weight_sum <= 0.0):
            raise SyntheticCampaignError("an epoch has no valid orders for period search")
        values = np.sum(np.where(reference.valid_mask, reference.rv * weights, 0.0), axis=1) / (
            weight_sum
        )
        uncertainties = np.sqrt(1.0 / weight_sum)
        time_by_epoch = dict(
            zip(
                (item.epoch_id for item in self._template.specification.epochs),
                self._template.epoch_times,
                strict=True,
            )
        )
        times = np.asarray([time_by_epoch[epoch] for epoch in reference.epoch_ids])
        nuisance = self._search.nuisance_regressors
        if nuisance is not None:
            full_epoch_index = {
                item.epoch_id: index
                for index, item in enumerate(self._template.specification.epochs)
            }
            nuisance = np.asarray(
                [nuisance[full_epoch_index[epoch]] for epoch in reference.epoch_ids],
                dtype=np.float64,
            )
        search = weighted_sinusoid_search(
            times,
            values,
            uncertainties,
            np.asarray(self._search.periods, dtype=np.float64),
            nuisance_regressors=nuisance,
            include_intercept=self._search.include_intercept,
            reference_time=self._search.reference_time,
            rcond=self._search.rcond,
        )
        decision_trace = {
            "configuration_sha256": self.configuration_sha256,
            "declared_implementation_build_sha256": (self.declared_implementation_build_sha256),
            "hidden_validation": {
                "assessment": {
                    "arm_id": hidden_assessment.arm_id,
                    "configuration_identity": hidden_assessment.configuration_identity,
                    "configuration_index": hidden_assessment.configuration_index,
                    "gate_evaluation_sha256": (hidden_gate_evaluation.evaluation_sha256),
                    "plan_id": hidden_assessment.plan_id,
                    "score_id": hidden_assessment.score_id,
                },
                "bridge_sha256": hidden_evidence.bridge_sha256,
                "ensemble_sha256": hidden_ensemble.result_sha256,
                "gate_evaluation": hidden_gate_evaluation.identity_payload(),
                "plan_sha256": hidden_plan_sha256,
            },
            "pipeline_identity_sha256": self.pipeline_identity_sha256,
            "rv_frame_contract_sha256": self._template.frame_contract.contract_sha256,
            "rv_unit": "m/s",
            "schema_version": _SCHEMA_VERSION,
            "scientific_gate_status": "unresolved",
            "scientific_use_authorized": False,
            "scope": "toy_structural_only",
            "selection": {
                "bridge_sha256": [item.bridge_sha256 for item in evidence_by_arm],
                "ensemble_sha256": selection_ensemble.result_sha256,
                "gate_evaluations": [
                    item.identity_payload() for item in selection_gate_evaluations
                ],
                "plan_sha256": evidence_by_arm[0].selection_plan_sha256,
                "winner": {
                    "arm_id": selection.winner.arm_id,
                    "configuration_identity": selection.winner.configuration_identity,
                    "configuration_index": selection.winner.configuration_index,
                    "gate_evaluation_sha256": (selection.winner.gate_evaluation.evaluation_sha256),
                    "plan_id": selection.winner.plan_id,
                    "score_id": selection.winner.score_id,
                },
            },
        }
        return PipelineOutcome(
            trial_id=trial.trial_id,
            max_statistic=search.max_statistic,
            details={
                "best_period": search.best_period,
                "common_rv_frame_label": self._template.frame_contract.common_frame_label,
                "configuration_sha256": self.configuration_sha256,
                "gate_scope": "toy_structural_only",
                "hidden_bridge_sha256": hidden_evidence.bridge_sha256,
                "hidden_ensemble_sha256": hidden_ensemble.result_sha256,
                "hidden_gate_evaluation_sha256": (hidden_gate_evaluation.evaluation_sha256),
                "declared_implementation_build_sha256": (self.declared_implementation_build_sha256),
                "pipeline_identity_sha256": self.pipeline_identity_sha256,
                "rv_unit": "m/s",
                "search_result_sha256": search.result_identity,
                "scientific_gate_status": "unresolved",
                "selection_gate_evaluation_sha256": [
                    item.evaluation_sha256 for item in selection_gate_evaluations
                ],
                "selection_bridge_sha256": selected_evidence.bridge_sha256,
                "selection_ensemble_sha256": selection_ensemble.result_sha256,
                "source_control_sha256": control.control_sha256,
                "synthetic_only": True,
                "toy_decision_trace": decision_trace,
                "toy_decision_trace_sha256": canonical_sha256(decision_trace),
                "winner_arm_id": selection.winner.arm_id,
                "winner_configuration_sha256": selection.winner.configuration_identity,
            },
        )


__all__ = [
    "BridgeUncertaintyContract",
    "RVFrameContract",
    "RVFrameTransform",
    "SyntheticCampaignError",
    "SyntheticExecutionRecord",
    "SyntheticInjectionBank",
    "SyntheticSearchConfig",
    "SyntheticSelectionConfig",
    "SyntheticSelectionEvidence",
    "SyntheticSinusoidSignalModel",
    "SyntheticTemplateRunConfig",
    "SyntheticWholePipelineCallback",
    "ToyArmAssessment",
    "ToyStructuralGateEvaluation",
    "bridge_template_chain_to_selection",
    "selection_plan_identity",
]
