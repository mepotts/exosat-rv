"""Adversarial target-free tests for the M38 synthetic campaign bridge."""

from collections.abc import Mapping
from dataclasses import replace

import numpy as np
import pytest

import exosat_rv.m38.synthetic_campaign as campaign_module
from exosat_rv.m38.convergence import ConvergencePolicy
from exosat_rv.m38.period_search import (
    PipelineOutcome,
    PipelineTrial,
    SignalAxis,
    SignalTrialPlan,
    run_adaptive_pipeline_grid_calibration,
)
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.selection import (
    ArmGates,
    AttritionPolicy,
    EquivalenceInterval,
    estimate_recovery_slope,
    score_injection_responses,
)
from exosat_rv.m38.spectral import C_M_S
from exosat_rv.m38.synthetic_campaign import (
    BridgeUncertaintyContract,
    RVFrameContract,
    RVFrameTransform,
    SyntheticCampaignError,
    SyntheticInjectionBank,
    SyntheticSearchConfig,
    SyntheticSelectionConfig,
    SyntheticSelectionEvidence,
    SyntheticSinusoidSignalModel,
    SyntheticTemplateRunConfig,
    SyntheticWholePipelineCallback,
    ToyStructuralGateEvaluation,
    bridge_template_chain_to_selection,
    selection_plan_identity,
)
from exosat_rv.m38.synthetic_controls import (
    ToyControlSpecification,
    ToyEpochSpecification,
    ToyOrderSpecification,
    ToyTemplateAdapterFactory,
    generate_toy_control,
)
from exosat_rv.m38.template_chain import (
    CrossInjectionMaskContract,
    EpochVelocity,
    ExtractionArm,
    OrderPropagationPlan,
    PreTemplateInjectionPlan,
    TemplateChainRoster,
    WorkflowFreshnessRegistry,
    make_disjoint_fold_plan,
    run_template_chain_ensemble,
)

_BRIDGE_ADAPTER_LABEL = "synthetic-campaign-bridge-test"
_CALLBACK_ADAPTER_LABEL = "synthetic-whole-pipeline-test"
_GATE_EVALUATOR_ID = canonical_sha256(
    {"exact_test_gate_evaluator_build": "synthetic-structural-gates"}
)
_IMPLEMENTATION_BUILD_SHA256 = canonical_sha256(
    {"exact_test_implementation_build": "synthetic-campaign"}
)
_EVIDENCE_THRESHOLD = 100.0


def _specification() -> ToyControlSpecification:
    return ToyControlSpecification(
        control_label="synthetic-campaign-integration",
        epochs=tuple(
            ToyEpochSpecification(f"epoch-{index:02d}", 0.0, 100 + index) for index in range(12)
        ),
        orders=(
            ToyOrderSpecification("order-a", 500.0, 0.001, 500.064, 500.090),
            ToyOrderSpecification("order-b", 600.0, 0.001, 600.064, 600.094),
        ),
        sample_count=129,
        stellar_depth=0.4,
        stellar_width=0.006,
        telluric_depth=0.0,
        telluric_width=0.005,
        lsf_kernel=(0.2, 0.6, 0.2),
        noise_standard_deviation=0.000001,
    )


def _fold_and_order_plans(specification: ToyControlSpecification):
    epoch_ids = tuple(item.epoch_id for item in specification.epochs)
    order_ids = tuple(item.order_id for item in specification.orders)
    fold_plan = make_disjoint_fold_plan(
        epoch_ids[:3],
        epoch_ids[3:],
        fold_id="train-evaluate",
    )
    order_plan = OrderPropagationPlan(
        mode="common",
        available_order_ids=order_ids,
        arms=(
            ExtractionArm("both-orders", order_ids),
            ExtractionArm("first-order", (order_ids[0],)),
        ),
        common_template_order_ids=order_ids,
    )
    return fold_plan, order_plan


def _policy() -> ConvergencePolicy:
    return ConvergencePolicy(
        d_template_limit=1_000_000.0,
        d_rv_limit=1_000_000.0,
        q_conv=1,
        k_max=1,
        template_aggregate="maximum",
    )


def _selection_patterns() -> tuple[tuple[float, ...], ...]:
    return (
        (
            900.0,
            -600.0,
            -300.0,
            -1800.0,
            -900.0,
            450.0,
            1350.0,
            1800.0,
            900.0,
            -450.0,
            -1350.0,
            600.0,
        ),
        (
            -600.0,
            -300.0,
            900.0,
            1500.0,
            -1200.0,
            900.0,
            -600.0,
            300.0,
            -1500.0,
            1200.0,
            -300.0,
            1800.0,
        ),
    )


def _hidden_patterns() -> tuple[tuple[float, ...], ...]:
    return (
        (
            1200.0,
            -800.0,
            -400.0,
            -1300.0,
            700.0,
            1900.0,
            -400.0,
            1100.0,
            -1700.0,
            300.0,
            1500.0,
            -900.0,
        ),
        (
            -800.0,
            -400.0,
            1200.0,
            800.0,
            1600.0,
            -500.0,
            -1400.0,
            2000.0,
            -100.0,
            1000.0,
            -1900.0,
            400.0,
        ),
    )


def _pre_template_plans(epoch_ids: tuple[str, ...]):
    return (
        PreTemplateInjectionPlan(
            plan_label="reference-zero",
            epoch_ids=epoch_ids,
            velocities=tuple(EpochVelocity(epoch, 0.0) for epoch in epoch_ids),
        ),
        *(
            PreTemplateInjectionPlan(
                plan_label=f"injection-{index}",
                epoch_ids=epoch_ids,
                velocities=tuple(
                    EpochVelocity(epoch, velocity)
                    for epoch, velocity in zip(epoch_ids, pattern, strict=True)
                ),
            )
            for index, pattern in enumerate(_selection_patterns())
        ),
    )


def _adapter_identity(adapter_label: str) -> str:
    return ToyTemplateAdapterFactory(
        adapter_label=adapter_label,
        relaxation=1.0,
        adjacent_noise_scale=1.0,
    ).identity.identity_sha256


def _frame_contract(
    specification: ToyControlSpecification,
    *,
    adapter_label: str,
) -> RVFrameContract:
    fold_plan, _ = _fold_and_order_plans(specification)
    return RVFrameContract(
        adapter_identity_sha256=_adapter_identity(adapter_label),
        common_frame_label="toy-barycentric-origin-zero",
        transforms=tuple(
            RVFrameTransform(
                fold_id=fold.fold_id,
                order_id=order.order_id,
                scale_m_s_per_native_unit=(
                    C_M_S * order.wavelength_step / order.stellar_line_center
                ),
                offset_m_s=0.0,
            )
            for fold in fold_plan.folds
            for order in specification.orders
        ),
    )


def _ensemble(*, reference_index: int = 0):
    specification = _specification()
    control = generate_toy_control(specification)
    fold_plan, order_plan = _fold_and_order_plans(specification)
    plans = _pre_template_plans(control.exposures.epoch_ids)
    roster = TemplateChainRoster(fold_plan=fold_plan, order_plan=order_plan)
    return run_template_chain_ensemble(
        control.exposures,
        plans,
        fold_plan,
        order_plan,
        _policy(),
        ToyTemplateAdapterFactory(
            adapter_label=_BRIDGE_ADAPTER_LABEL,
            relaxation=1.0,
            adjacent_noise_scale=1.0,
        ),
        mask_contract=CrossInjectionMaskContract(
            reference_plan_sha256=plans[reference_index].plan_sha256,
            roster_sha256=roster.roster_sha256,
        ),
        ensemble_nonce=canonical_sha256({"test": "synthetic-campaign-bridge"}),
        freshness_registry=WorkflowFreshnessRegistry(),
    )


def _uncertainty_contract(specification: ToyControlSpecification):
    epoch_ids = tuple(item.epoch_id for item in specification.epochs)
    return BridgeUncertaintyContract(
        epoch_ids=epoch_ids,
        cluster_ids=tuple(f"night-{index:02d}" for index in range(len(epoch_ids))),
        reference_uncertainty_m_s=5.0,
        injected_uncertainty_m_s=5.0,
        response_uncertainty_m_s=5.0,
    )


def _toy_gate_evaluator(
    evidence: SyntheticSelectionEvidence,
    configuration_identity: str,
    stage: str,
) -> ToyStructuralGateEvaluation:
    reference_counts = np.sum(evidence.reference.valid_mask, axis=1)
    return ToyStructuralGateEvaluation(
        evaluator_identity_sha256=_GATE_EVALUATOR_ID,
        evidence_bridge_sha256=evidence.bridge_sha256,
        arm_id=evidence.arm_id,
        configuration_identity=configuration_identity,
        assessment_stage=stage,
        structural_gates=ArmGates(
            provenance_valid=True,
            reference_run_complete=True,
            injection_runs_complete=(
                len(evidence.injected_responses) == len(evidence.injection_plans)
            ),
            template_convergence_complete=True,
            fit_quality_passed=bool(np.all(reference_counts >= 1)),
            per_order_stability_passed=all(
                np.array_equal(response.valid_mask, evidence.reference.valid_mask)
                for response in evidence.injected_responses
            ),
            catastrophic_fit_checks_passed=bool(
                np.all(np.isfinite(evidence.reference.rv[evidence.reference.valid_mask]))
            ),
        ),
    )


def _null_trial(*, seed: int = 42) -> PipelineTrial:
    plan_id = canonical_sha256({"test_plan": "one-null"})
    descriptor = {
        "amplitude": None,
        "amplitude_index": None,
        "kind": "null",
        "phase": None,
        "phase_index": None,
        "plan_id": plan_id,
        "replicate_index": 0,
        "signal_indices": None,
        "signal_parameters": None,
        "trial_seed": seed,
    }
    return PipelineTrial(
        trial_id=f"null:{plan_id}:{canonical_sha256(descriptor)}",
        plan_id=plan_id,
        kind="null",
        trial_seed=seed,
        replicate_index=0,
    )


def _native_json(value):
    if isinstance(value, Mapping):
        return {key: _native_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_native_json(item) for item in value]
    return value


def test_bridge_is_content_bound_and_recovers_m_s_slope_near_unity() -> None:
    specification = _specification()
    ensemble = _ensemble()
    evidence = bridge_template_chain_to_selection(
        ensemble,
        arm_id="both-orders",
        uncertainty_contract=_uncertainty_contract(specification),
        frame_contract=_frame_contract(
            specification,
            adapter_label=_BRIDGE_ADAPTER_LABEL,
        ),
    )

    evidence.verify_integrity()
    assert evidence.reference.epoch_ids == tuple(item.epoch_id for item in specification.epochs[3:])
    assert evidence.reference.order_ids == ("order-a", "order-b")
    assert np.all(evidence.reference.uncertainty[evidence.reference.valid_mask] == 5.0)
    assert len(evidence.injection_plans) == 2
    assert tuple(plan.injection_id for plan in evidence.injection_plans) == tuple(
        trial.applied_injection.plan.plan_sha256 for trial in ensemble.trials[1:]
    )
    assert evidence.selection_plan_sha256 == selection_plan_identity(
        evidence.reference.epoch_ids,
        evidence.injection_plans,
    )
    assert len(evidence.fold_result_sha256) == 3
    reference_trial = ensemble.trials[0]
    for injected_trial in ensemble.trials[1:]:
        assert injected_trial.result_sha256 != reference_trial.result_sha256
        for reference_fold, injected_fold in zip(
            reference_trial.fold_results,
            injected_trial.fold_results,
            strict=True,
        ):
            reference_template = reference_fold.template_states[-1]
            injected_template = injected_fold.template_states[-1]
            assert injected_template.state_sha256 != reference_template.state_sha256
            assert not np.array_equal(injected_template.flux, reference_template.flux)

    score = score_injection_responses(
        evidence.reference,
        evidence.injection_plans,
        evidence.injected_responses,
        AttritionPolicy(
            minimum_reference_orders=2,
            minimum_common_orders=2,
            maximum_lost_orders=0,
            maximum_lost_fraction=0.0,
            attrition_action="fail_primary",
        ),
    )
    estimate = estimate_recovery_slope(
        score,
        seed=7721,
        repetitions=101,
        confidence_level=0.9,
        minimum_independent_clusters=4,
    )
    assert score.all_planned_responses_present
    assert score.attrition_gate_passed
    assert estimate.complete
    assert estimate.slope == pytest.approx(1.0, abs=0.08)
    assert estimate.confidence_lower is not None
    assert estimate.confidence_upper is not None
    assert estimate.confidence_lower >= 0.9
    assert estimate.confidence_upper <= 1.1


def test_bridge_rejects_wrong_frame_missing_transform_and_forged_outputs() -> None:
    specification = _specification()
    ensemble = _ensemble()
    uncertainty = _uncertainty_contract(specification)
    frame = _frame_contract(specification, adapter_label=_BRIDGE_ADAPTER_LABEL)
    evidence = bridge_template_chain_to_selection(
        ensemble,
        arm_id="first-order",
        uncertainty_contract=uncertainty,
        frame_contract=frame,
    )
    forged_reference = replace(evidence.reference, rv=np.asarray(evidence.reference.rv) + 1.0)
    with pytest.raises(SyntheticCampaignError, match="does not exactly derive"):
        SyntheticSelectionEvidence(
            ensemble=ensemble,
            arm_id=evidence.arm_id,
            uncertainty_contract=uncertainty,
            frame_contract=frame,
            reference=forged_reference,
            injection_plans=evidence.injection_plans,
            injected_responses=evidence.injected_responses,
            fold_result_sha256=evidence.fold_result_sha256,
        )

    wrong_adapter = replace(frame, adapter_identity_sha256="0" * 64)
    with pytest.raises(SyntheticCampaignError, match="adapter identity"):
        bridge_template_chain_to_selection(
            ensemble,
            arm_id="first-order",
            uncertainty_contract=uncertainty,
            frame_contract=wrong_adapter,
        )
    missing = RVFrameContract(
        adapter_identity_sha256=frame.adapter_identity_sha256,
        common_frame_label=frame.common_frame_label,
        transforms=(frame.transforms[1],),
    )
    with pytest.raises(SyntheticCampaignError, match="does not cover fold/order"):
        bridge_template_chain_to_selection(
            ensemble,
            arm_id="first-order",
            uncertainty_contract=uncertainty,
            frame_contract=missing,
        )

    nonzero_reference = _ensemble(reference_index=1)
    with pytest.raises(SyntheticCampaignError, match="exact zero injection"):
        bridge_template_chain_to_selection(
            nonzero_reference,
            arm_id="first-order",
            uncertainty_contract=uncertainty,
            frame_contract=frame,
        )


def _whole_pipeline_callback(
    *,
    declared_implementation_build_sha256: str = _IMPLEMENTATION_BUILD_SHA256,
    gate_evaluator=_toy_gate_evaluator,
    gate_evaluator_identity_sha256: str = _GATE_EVALUATOR_ID,
    selection_patterns: tuple[tuple[float, ...], ...] | None = None,
    hidden_patterns: tuple[tuple[float, ...], ...] | None = None,
) -> SyntheticWholePipelineCallback:
    specification = _specification()
    epoch_ids = tuple(item.epoch_id for item in specification.epochs)
    fold_plan, order_plan = _fold_and_order_plans(specification)
    template_config = SyntheticTemplateRunConfig(
        specification=specification,
        epoch_times=(
            -3.0,
            -2.0,
            -1.0,
            0.0,
            0.8,
            2.1,
            3.5,
            5.4,
            7.9,
            11.2,
            15.8,
            21.3,
        ),
        fold_plan=fold_plan,
        order_plan=order_plan,
        convergence_policy=_policy(),
        adapter_label=_CALLBACK_ADAPTER_LABEL,
        adapter_relaxation=1.0,
        adjacent_noise_scale=1.0,
        uncertainty_contract=_uncertainty_contract(specification),
        frame_contract=_frame_contract(
            specification,
            adapter_label=_CALLBACK_ADAPTER_LABEL,
        ),
    )
    selection_config = SyntheticSelectionConfig(
        selection_bank=SyntheticInjectionBank(
            bank_label="selection-bank",
            epoch_ids=epoch_ids,
            velocity_patterns=(
                _selection_patterns() if selection_patterns is None else selection_patterns
            ),
        ),
        hidden_bank=SyntheticInjectionBank(
            bank_label="hidden-bank",
            epoch_ids=epoch_ids,
            velocity_patterns=_hidden_patterns() if hidden_patterns is None else hidden_patterns,
        ),
        attrition_policy=AttritionPolicy(
            minimum_reference_orders=1,
            minimum_common_orders=1,
            maximum_lost_orders=0,
            maximum_lost_fraction=0.0,
            attrition_action="fail_primary",
        ),
        equivalence_interval=EquivalenceInterval.from_delta(0.1),
        bootstrap_repetitions=31,
        confidence_level=0.9,
        minimum_independent_clusters=4,
    )
    search_config = SyntheticSearchConfig(
        periods=(3.2, 4.3, 5.1, 6.6, 8.4, 13.0),
        order_combination="inverse_variance_mean",
        include_intercept=True,
        reference_time=None,
        rcond=None,
        nuisance_regressors=None,
    )
    return SyntheticWholePipelineCallback(
        template_config,
        selection_config,
        search_config,
        SyntheticSinusoidSignalModel(
            amplitude_parameter="amplitude",
            period_parameter="period",
            phase_parameter="phase",
        ),
        declared_implementation_build_sha256=declared_implementation_build_sha256,
        gate_evaluator=gate_evaluator,
        gate_evaluator_identity_sha256=gate_evaluator_identity_sha256,
    )


@pytest.mark.parametrize("bank_name", ("selection", "hidden"))
@pytest.mark.parametrize(
    "training_values",
    (
        (0.0, 0.0, 0.0),
        (300.0, 300.0, 300.0),
    ),
)
def test_callback_rejects_degenerate_training_injections_before_execution(
    monkeypatch,
    bank_name: str,
    training_values: tuple[float, float, float],
) -> None:
    source_patterns = _selection_patterns() if bank_name == "selection" else _hidden_patterns()
    degenerate = tuple((*training_values, *pattern[3:]) for pattern in source_patterns)
    executed = False

    def forbidden_execution(*args, **kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("template-chain execution must not begin")

    monkeypatch.setattr(
        campaign_module,
        "run_template_chain_ensemble",
        forbidden_execution,
    )
    arguments = {f"{bank_name}_patterns": degenerate}
    with pytest.raises(
        SyntheticCampaignError,
        match="both positive and negative training velocities",
    ):
        _whole_pipeline_callback(**arguments)
    assert executed is False


@pytest.mark.parametrize("bank_name", ("selection", "hidden"))
def test_callback_rejects_signed_subresolution_training_after_ensemble(
    monkeypatch,
    bank_name: str,
) -> None:
    source_patterns = _selection_patterns() if bank_name == "selection" else _hidden_patterns()
    subresolution = tuple((1e-9, -1e-9, 1e-9, *pattern[3:]) for pattern in source_patterns)
    arguments = {f"{bank_name}_patterns": subresolution}
    callback = _whole_pipeline_callback(**arguments)
    original_score = campaign_module.score_injection_responses
    scoring_calls = 0

    def tracked_score(*args, **kwargs):
        nonlocal scoring_calls
        scoring_calls += 1
        return original_score(*args, **kwargs)

    monkeypatch.setattr(campaign_module, "score_injection_responses", tracked_score)
    with pytest.raises(
        SyntheticCampaignError,
        match="did not alter final template flux",
    ):
        callback(_null_trial(seed=44))

    retained_stages = {item.stage for item in callback.execution_records}
    if bank_name == "selection":
        assert scoring_calls == 0
        assert retained_stages == set()
    else:
        assert scoring_calls == 2
        assert retained_stages == {"selection"}


def test_real_callback_recovers_associated_period_and_executes_only_winner_hidden() -> None:
    callback = _whole_pipeline_callback()

    def recovery_rule(trial, outcome: PipelineOutcome) -> bool:
        assert isinstance(outcome.details, dict)
        assert outcome.details["synthetic_only"] is True
        injected_period = dict(trial.signal_parameters or ())["period"]
        return bool(abs(outcome.details["best_period"] - injected_period) <= 0.01)

    result = run_adaptive_pipeline_grid_calibration(
        callback,
        recovery_rule,
        null_trials=1,
        signal_plan=SignalTrialPlan(
            axes=(
                SignalAxis("period", (5.1,)),
                SignalAxis("amplitude", (900.0,)),
                SignalAxis("phase", (0.37,)),
            ),
            replicates_per_cell=1,
        ),
        null_seed=712,
        signal_seed=713,
        evidence_threshold=_EVIDENCE_THRESHOLD,
        confidence_level=0.9,
        interval_method="wilson",
        pipeline_identity=callback.pipeline_identity_sha256,
        recovery_rule_identity=canonical_sha256({"test": "injected-period-association-v1"}),
        plan_metadata={"scope": "target-free-toy-integration"},
    )

    assert result.complete
    assert len(result.null.records) == 1
    assert len(result.completeness.records) == 1
    null_record = result.null.records[0]
    signal_record = result.completeness.records[0]
    assert null_record.outcome is not None
    assert signal_record.outcome is not None
    assert signal_record.recovered is True
    assert signal_record.outcome.details["best_period"] == pytest.approx(5.1)
    assert signal_record.outcome.max_statistic >= _EVIDENCE_THRESHOLD
    assert signal_record.outcome.max_statistic > null_record.outcome.max_statistic

    for record in (null_record, signal_record):
        assert isinstance(record.outcome.details, Mapping)
        assert (
            record.outcome.details["pipeline_identity_sha256"] == callback.pipeline_identity_sha256
        )
        assert record.outcome.details["rv_unit"] == "m/s"
        assert record.outcome.details["gate_scope"] == "toy_structural_only"
        assert record.outcome.details["scientific_gate_status"] == "unresolved"
        decision_trace = record.outcome.details["toy_decision_trace"]
        assert (
            canonical_sha256(_native_json(decision_trace))
            == record.outcome.details["toy_decision_trace_sha256"]
        )
        assert decision_trace["scientific_use_authorized"] is False
        assert all(
            item["scope"] == "toy_structural_only"
            for item in decision_trace["selection"]["gate_evaluations"]
        )
        trial_records = tuple(
            item for item in callback.execution_records if item.trial_id == record.trial.trial_id
        )
        selection_arms = {item.arm_id for item in trial_records if item.stage == "selection"}
        hidden_arms = {item.arm_id for item in trial_records if item.stage == "hidden-validation"}
        assert selection_arms == {"both-orders", "first-order"}
        assert hidden_arms == {record.outcome.details["winner_arm_id"]}
        loser = (selection_arms - hidden_arms).pop()
        assert not any(
            item.arm_id == loser and item.stage == "hidden-validation" for item in trial_records
        )

    selection = np.asarray(_selection_patterns(), dtype=np.float64)[:, 3:]
    hidden = np.asarray(_hidden_patterns(), dtype=np.float64)[:, 3:]
    for pattern in (*_selection_patterns(), *_hidden_patterns()):
        assert all(value != 0.0 for value in pattern[:3])
        assert sum(pattern[:3]) == pytest.approx(0.0)
    assert all(
        np.linalg.matrix_rank(np.stack((selection_row, hidden_row))) == 2
        for selection_row in selection
        for hidden_row in hidden
    )


def test_gate_results_are_external_bound_toy_only_and_fail_closed() -> None:
    def stale_gate_evaluator(evidence, configuration_identity, stage):
        result = _toy_gate_evaluator(evidence, configuration_identity, stage)
        return replace(result, evidence_bridge_sha256="0" * 64)

    callback = _whole_pipeline_callback(gate_evaluator=stale_gate_evaluator)
    with pytest.raises(SyntheticCampaignError, match="not bound to this exact assessment"):
        callback(_null_trial())

    evidence = bridge_template_chain_to_selection(
        _ensemble(),
        arm_id="first-order",
        uncertainty_contract=_uncertainty_contract(_specification()),
        frame_contract=_frame_contract(
            _specification(),
            adapter_label=_BRIDGE_ADAPTER_LABEL,
        ),
    )
    evaluation = _toy_gate_evaluator(
        evidence,
        canonical_sha256({"configuration": "test"}),
        "selection",
    )
    assert evaluation.scope == "toy_structural_only"
    assert evaluation.scientific_gate_status == "unresolved"
    assert evaluation.scientific_use_authorized is False
    # dataclasses.replace raises ValueError on Python 3.11/3.12 and TypeError on 3.13.
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(evaluation, scientific_use_authorized=True)
    object.__setattr__(evaluation, "scientific_use_authorized", True)
    with pytest.raises(SyntheticCampaignError, match="cannot authorise scientific use"):
        evaluation.verify_integrity()


def test_build_identity_noise_seeds_and_bank_projection_fail_closed(monkeypatch) -> None:
    callback = _whole_pipeline_callback()
    changed_build = _whole_pipeline_callback(
        declared_implementation_build_sha256=canonical_sha256({"different_exact_build": True})
    )
    assert callback.configuration_sha256 == changed_build.configuration_sha256
    assert callback.pipeline_identity_sha256 != changed_build.pipeline_identity_sha256
    assert callback.declared_implementation_build_sha256 == _IMPLEMENTATION_BUILD_SHA256

    monkeypatch.setattr(campaign_module, "_derived_noise_seed", lambda *args: 17)
    with pytest.raises(SyntheticCampaignError, match="noise seeds collide"):
        callback(_null_trial(seed=43))

    bank = callback._selection.selection_bank
    object.__setattr__(bank, "velocity_patterns", _hidden_patterns())
    with pytest.raises(SyntheticCampaignError, match="content hash mismatch"):
        bank.projected_selection_plans(tuple(item.epoch_id for item in _specification().epochs[3:]))

    duplicate_seed_specification = replace(
        _specification(),
        epochs=tuple(replace(item, noise_seed=100) for item in _specification().epochs),
    )
    template = callback._template
    with pytest.raises(SyntheticCampaignError, match="noise seeds must be unique"):
        replace(template, specification=duplicate_seed_specification)


def test_every_campaign_choice_is_explicit_and_content_bound() -> None:
    callback = _whole_pipeline_callback()
    second = _whole_pipeline_callback()
    assert callback.configuration_sha256 == second.configuration_sha256
    assert callback.pipeline_identity_sha256 == second.pipeline_identity_sha256

    with pytest.raises(SyntheticCampaignError, match="physically disjoint"):
        config = second._selection
        replace(config, hidden_bank=config.selection_bank)
    with pytest.raises(SyntheticCampaignError, match="strictly increasing"):
        replace(second._search, periods=(5.0, 5.0))
    with pytest.raises(SyntheticCampaignError, match="must be positive"):
        replace(
            second._template.uncertainty_contract,
            response_uncertainty_m_s=0.0,
        )
    with pytest.raises(SyntheticCampaignError, match="exactly cover every fitted fold/order"):
        frame = second._template.frame_contract
        replace(second._template, frame_contract=replace(frame, transforms=frame.transforms[:1]))
