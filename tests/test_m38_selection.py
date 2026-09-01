from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np
import pytest

from exosat_rv.m38 import selection
from exosat_rv.m38.selection import (
    ArmAssessment,
    ArmGates,
    ArmRosterEntry,
    AttritionPolicy,
    BootstrapFailure,
    EquivalenceInterval,
    HiddenValidationResult,
    InjectedResponse,
    InjectionPlan,
    NoEligibleArmError,
    ReferenceResponse,
    SelectionContract,
    SelectionDataError,
    WinnerSelection,
    apply_hidden_validation,
    assess_arm,
    estimate_recovery_slope,
    rank_eligible_arms,
    score_injection_responses,
    select_winner,
)


class EvilHex(str):
    """A digest-shaped string whose equality tries to approve every commitment."""

    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        return True


class EvilLabel(str):
    """A label-shaped string whose equality tries to impersonate every identity."""

    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        return True


class EvilFloat(float):
    """A scalar whose arithmetic and equality try to make forged audits look valid."""

    def __eq__(self, other: object) -> bool:
        return True

    def __sub__(self, other: object) -> float:
        return 0.0

    def __rsub__(self, other: object) -> float:
        return 0.0


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _policy() -> AttritionPolicy:
    return AttritionPolicy(
        minimum_reference_orders=3,
        minimum_common_orders=3,
        maximum_lost_orders=0,
        maximum_lost_fraction=0.0,
        attrition_action="fail_primary",
    )


def _reference(
    *,
    epoch_count: int = 4,
    order_count: int = 3,
    cluster_ids: tuple[str, ...] | None = None,
) -> ReferenceResponse:
    epoch_ids = tuple(f"epoch-{index}" for index in range(epoch_count))
    clusters = cluster_ids or tuple(f"cluster-{index}" for index in range(epoch_count))
    return ReferenceResponse(
        epoch_ids=epoch_ids,
        cluster_ids=clusters,
        order_ids=tuple(f"order-{index}" for index in range(order_count)),
        rv=np.zeros((epoch_count, order_count), dtype=np.float64),
        uncertainty=np.full((epoch_count, order_count), 0.3),
        valid_mask=np.ones((epoch_count, order_count), dtype=np.bool_),
    )


def _plans(
    reference: ReferenceResponse,
    *,
    identity: str = "selection",
    pattern_scale: float = 1.0,
) -> tuple[InjectionPlan, ...]:
    epoch_index = np.arange(len(reference.epoch_ids), dtype=np.float64)
    velocity_patterns = pattern_scale * np.array(
        (
            -2.0 + 0.25 * (epoch_index % 2.0),
            np.where((epoch_index.astype(int) % 2) == 0, -0.4, 0.5),
            2.0 - 0.2 * (epoch_index % 3.0),
        )
    )
    return tuple(
        InjectionPlan(
            injection_id=f"{identity}-injection-{index}",
            epoch_ids=reference.epoch_ids,
            velocities=velocities,
        )
        for index, velocities in enumerate(velocity_patterns)
    )


def _linear_response(
    reference: ReferenceResponse,
    plan: InjectionPlan,
    *,
    epoch_slopes: np.ndarray | None = None,
    order_slopes: np.ndarray | None = None,
    valid_mask: np.ndarray | None = None,
    paired_uncertainty: float | np.ndarray = 0.6,
) -> InjectedResponse:
    epoch_slope_values = (
        np.ones(len(reference.epoch_ids), dtype=np.float64)
        if epoch_slopes is None
        else np.asarray(epoch_slopes, dtype=np.float64)
    )
    if epoch_slope_values.shape != (len(reference.epoch_ids),):
        raise ValueError("test epoch-slope vector has the wrong shape")
    order_slope_values = (
        None if order_slopes is None else np.asarray(order_slopes, dtype=np.float64)
    )
    if order_slope_values is not None and order_slope_values.shape != (len(reference.order_ids),):
        raise ValueError("test order-slope vector has the wrong shape")
    injected_mask = (
        np.array(reference.valid_mask, copy=True)
        if valid_mask is None
        else np.asarray(valid_mask, dtype=np.bool_)
    )
    paired = np.broadcast_to(
        np.asarray(paired_uncertainty, dtype=np.float64),
        reference.rv.shape,
    )
    rv = np.full(reference.rv.shape, np.nan)
    uncertainty = np.full(reference.rv.shape, np.nan)
    response_uncertainty = np.full(reference.rv.shape, np.nan)
    for epoch_index in range(len(reference.epoch_ids)):
        for order_index in range(len(reference.order_ids)):
            if not injected_mask[epoch_index, order_index]:
                continue
            slope = (
                epoch_slope_values[epoch_index]
                if order_slope_values is None
                else order_slope_values[order_index]
            )
            rv[epoch_index, order_index] = (
                reference.rv[epoch_index, order_index] + 0.05 + slope * plan.velocities[epoch_index]
            )
            uncertainty[epoch_index, order_index] = 0.4
            response_uncertainty[epoch_index, order_index] = paired[
                epoch_index,
                order_index,
            ]
    return InjectedResponse(
        injection_id=plan.injection_id,
        epoch_ids=reference.epoch_ids,
        order_ids=reference.order_ids,
        rv=rv,
        uncertainty=uncertainty,
        response_uncertainty=response_uncertainty,
        valid_mask=injected_mask,
    )


def _complete_score(
    *,
    epoch_slopes: np.ndarray | None = None,
    cluster_ids: tuple[str, ...] | None = None,
    plan_identity: str = "selection",
    plan_scale: float = 1.0,
):
    reference = _reference(cluster_ids=cluster_ids)
    plans = _plans(reference, identity=plan_identity, pattern_scale=plan_scale)
    responses = tuple(
        _linear_response(reference, plan, epoch_slopes=epoch_slopes) for plan in plans
    )
    score = score_injection_responses(reference, plans, responses, _policy())
    return reference, plans, responses, score


def _estimate(score, *, seed: int = 41, repetitions: int = 31):
    return estimate_recovery_slope(
        score,
        seed=seed,
        repetitions=repetitions,
        confidence_level=0.9,
        minimum_independent_clusters=2,
    )


def _passed_gates() -> ArmGates:
    return ArmGates(
        provenance_valid=True,
        reference_run_complete=True,
        injection_runs_complete=True,
        template_convergence_complete=True,
        fit_quality_passed=True,
        per_order_stability_passed=True,
        catastrophic_fit_checks_passed=True,
    )


def _assessment(
    arm_id: str,
    configuration_index: int,
    score,
    estimate,
    *,
    stage: selection.AssessmentStage = "selection",
    gates: ArmGates | None = None,
    delta: float = 0.2,
    configuration_identity: str | None = None,
) -> ArmAssessment:
    return assess_arm(
        arm_id,
        configuration_index,
        configuration_identity or _digest(f"configuration-{configuration_index}"),
        score,
        estimate,
        EquivalenceInterval.from_delta(delta),
        gates or _passed_gates(),
        assessment_stage=stage,
    )


def _contract(
    assessments: tuple[ArmAssessment, ...],
    expected_hidden_plan_id: str,
    expected_hidden_bootstrap_seed: int = 97,
) -> SelectionContract:
    return SelectionContract(
        expected_arms=tuple(
            ArmRosterEntry(
                arm_id=value.arm_id,
                configuration_index=value.configuration_index,
                configuration_identity=value.configuration_identity,
            )
            for value in assessments
        ),
        expected_hidden_plan_id=expected_hidden_plan_id,
        expected_hidden_bootstrap_seed=expected_hidden_bootstrap_seed,
    )


def test_common_mask_uses_paired_differences_and_caller_uncertainties() -> None:
    reference = ReferenceResponse(
        epoch_ids=("epoch-a",),
        cluster_ids=("cluster-a",),
        order_ids=("order-a", "order-b", "order-c"),
        rv=np.array([[10.0, 20.0, 40.0]]),
        uncertainty=np.full((1, 3), 9.0),
        valid_mask=np.ones((1, 3), dtype=np.bool_),
    )
    plan = InjectionPlan(
        injection_id="injection-a",
        epoch_ids=reference.epoch_ids,
        velocities=np.array([3.0]),
    )
    response = InjectedResponse(
        injection_id=plan.injection_id,
        epoch_ids=reference.epoch_ids,
        order_ids=reference.order_ids,
        rv=np.array([[15.0, np.nan, 49.0]]),
        uncertainty=np.array([[7.0, np.nan, 7.0]]),
        response_uncertainty=np.array([[0.6, np.nan, 0.8]]),
        valid_mask=np.array([[True, False, True]]),
    )
    policy = AttritionPolicy(
        minimum_reference_orders=3,
        minimum_common_orders=2,
        maximum_lost_orders=0,
        maximum_lost_fraction=0.0,
        attrition_action="fail_primary",
    )

    score = score_injection_responses(reference, (plan,), (response,), policy)
    audit = score.epoch_records[0]

    assert audit.mean_response == pytest.approx(7.0)
    assert audit.mean_response != pytest.approx(
        np.mean(response.rv[response.valid_mask]) - np.mean(reference.rv)
    )
    assert audit.mean_response_uncertainty == pytest.approx(0.7)
    assert audit.common_order_ids == ("order-a", "order-c")
    assert audit.lost_order_ids == ("order-b",)
    assert not score.attrition_gate_passed
    assert not score.fit_ready
    changed_paired = np.array(response.response_uncertainty, copy=True)
    changed_paired[0, 0] = 0.7
    changed_score = score_injection_responses(
        reference,
        (plan,),
        (replace(response, response_uncertainty=changed_paired),),
        policy,
    )
    assert changed_score.score_id != score.score_id


def test_slope_one_one_four_loss_counterexample_is_primary_ineligible() -> None:
    reference = _reference(epoch_count=3)
    plans = _plans(reference)
    surviving_mask = np.ones(reference.rv.shape, dtype=np.bool_)
    surviving_mask[:, -1] = False
    responses = tuple(
        _linear_response(
            reference,
            plan,
            order_slopes=np.array([1.0, 1.0, 4.0]),
            valid_mask=surviving_mask,
        )
        for plan in plans
    )
    policy = AttritionPolicy(
        minimum_reference_orders=3,
        minimum_common_orders=2,
        maximum_lost_orders=0,
        maximum_lost_fraction=0.0,
        attrition_action="fail_primary",
    )

    score = score_injection_responses(reference, plans, responses, policy)
    estimate = _estimate(score, repetitions=9)
    assessment = _assessment("arm-a", 0, score, estimate)

    for record in score.epoch_records:
        assert record.mean_response == pytest.approx(record.injected_velocity + 0.05)
        assert record.lost_order_ids == ("order-2",)
    assert not score.attrition_gate_passed
    assert not score.fit_ready
    assert len(estimate.failures) == estimate.requested_repetitions
    assert not assessment.eligible


def test_primary_attrition_policy_rejects_any_nonzero_tolerance() -> None:
    with pytest.raises(ValueError, match="zero allowed"):
        AttritionPolicy(
            minimum_reference_orders=3,
            minimum_common_orders=2,
            maximum_lost_orders=1,
            maximum_lost_fraction=0.0,
            attrition_action="fail_primary",
        )
    with pytest.raises(ValueError, match="zero allowed"):
        AttritionPolicy(
            minimum_reference_orders=3,
            minimum_common_orders=2,
            maximum_lost_orders=0,
            maximum_lost_fraction=0.1,
            attrition_action="fail_primary",
        )


def test_epoch_aligned_patterns_are_bound_and_used_in_every_audit() -> None:
    reference, plans, _, score = _complete_score()

    assert all(np.unique(plan.velocities).size > 1 for plan in plans)
    assert len({_array.tobytes() for _array in (plan.velocities for plan in plans)}) == 3
    for record in score.epoch_records:
        plan = next(value for value in plans if value.injection_id == record.injection_id)
        epoch_index = reference.epoch_ids.index(record.epoch_id)
        assert record.injected_velocity == plan.velocities[epoch_index]
    estimate = _estimate(score)
    assert estimate.slope == pytest.approx(1.0)


def test_plan_epoch_identity_reordering_is_rejected() -> None:
    reference = _reference()
    good_plan = _plans(reference)[0]
    reordered_plan = InjectionPlan(
        injection_id=good_plan.injection_id,
        epoch_ids=tuple(reversed(good_plan.epoch_ids)),
        velocities=good_plan.velocities[::-1],
    )
    response = _linear_response(reference, good_plan)

    with pytest.raises(SelectionDataError, match="injection plan"):
        score_injection_responses(reference, (reordered_plan,), (response,), _policy())


def test_missing_planned_response_is_fully_audited_and_ineligible() -> None:
    reference = _reference()
    plans = _plans(reference)
    first_response = _linear_response(reference, plans[0])

    score = score_injection_responses(reference, plans, (first_response,), _policy())
    missing_records = tuple(
        record for record in score.order_records if record.injection_id != plans[0].injection_id
    )
    estimate = _estimate(score, repetitions=7)
    assessment = _assessment("arm-a", 0, score, estimate)

    assert not score.all_planned_responses_present
    assert len(missing_records) == (
        (len(plans) - 1) * len(reference.epoch_ids) * len(reference.order_ids)
    )
    assert {record.status for record in missing_records} == {"missing_response"}
    assert len(estimate.failures) == estimate.requested_repetitions
    assert not assessment.eligible


def test_cluster_bootstrap_is_deterministic_and_keeps_clustered_epochs_together() -> None:
    clusters = ("cluster-a", "cluster-a", "cluster-b", "cluster-c")
    epoch_slopes = np.array([0.7, 0.9, 1.1, 1.3])
    reference, plans, _, score = _complete_score(
        epoch_slopes=epoch_slopes,
        cluster_ids=clusters,
    )

    first = estimate_recovery_slope(
        score,
        seed=345,
        repetitions=41,
        confidence_level=0.9,
        minimum_independent_clusters=3,
    )
    second = estimate_recovery_slope(
        score,
        seed=345,
        repetitions=41,
        confidence_level=0.9,
        minimum_independent_clusters=3,
    )

    assert first.complete
    assert 0.7 < first.slope < 1.3
    np.testing.assert_array_equal(first.bootstrap_slopes, second.bootstrap_slopes)
    assert first.cluster_draws == second.cluster_draws
    assert first.epoch_index_draws == second.epoch_index_draws
    assert all(len(draw) == len(set(clusters)) for draw in first.cluster_draws)
    assert all(draw.count(0) == draw.count(1) for draw in first.epoch_index_draws)
    assert len(score.order_records) == (
        len(reference.epoch_ids) * len(reference.order_ids) * len(plans)
    )


def test_one_cluster_cannot_produce_a_zero_width_eligible_interval() -> None:
    clusters = ("one-cluster",) * 4
    _, _, _, score = _complete_score(cluster_ids=clusters)

    estimate = estimate_recovery_slope(
        score,
        seed=7,
        repetitions=13,
        confidence_level=0.9,
        minimum_independent_clusters=2,
    )

    assert not estimate.complete
    assert estimate.actual_independent_clusters == 1
    assert len(estimate.failures) == estimate.requested_repetitions
    assert np.all(np.isnan(estimate.bootstrap_slopes))
    assert estimate.confidence_lower is None
    assert "below" in estimate.fit_failure_reason
    with pytest.raises(ValueError, match="at least two"):
        estimate_recovery_slope(
            score,
            seed=7,
            repetitions=13,
            confidence_level=0.9,
            minimum_independent_clusters=1,
        )


def test_any_bootstrap_failure_blocks_interval_without_successful_subset_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, score = _complete_score(epoch_slopes=np.array([0.8, 0.9, 1.1, 1.2]))
    original_fit = selection._fit_line
    call_count = 0

    def fail_one_bootstrap(x, y, uncertainty):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("synthetic planned-repetition failure")
        return original_fit(x, y, uncertainty)

    monkeypatch.setattr(selection, "_fit_line", fail_one_bootstrap)
    estimate = _estimate(score, seed=88, repetitions=11)

    assert call_count == estimate.requested_repetitions + 1
    assert np.isnan(estimate.bootstrap_slopes[0])
    assert np.count_nonzero(np.isfinite(estimate.bootstrap_slopes)) == 10
    assert estimate.failures == (
        BootstrapFailure(0, "RuntimeError", "synthetic planned-repetition failure"),
    )
    assert estimate.confidence_lower is None
    assert not estimate.complete


def test_unity_centered_equivalence_includes_boundaries_and_rejects_arbitrary_bounds() -> None:
    _, _, _, score = _complete_score(epoch_slopes=np.array([0.9, 0.95, 1.05, 1.1]))
    estimate = _estimate(score, repetitions=13)
    assert estimate.confidence_lower is not None
    assert estimate.confidence_upper is not None
    boundary_delta = max(
        abs(estimate.confidence_lower - 1.0),
        abs(estimate.confidence_upper - 1.0),
    )

    included = _assessment("arm-a", 0, score, estimate, delta=boundary_delta)
    excluded = _assessment(
        "arm-a",
        0,
        score,
        estimate,
        delta=boundary_delta * 0.9,
    )

    assert included.eligible
    assert included.worst_confidence_bound_error == pytest.approx(boundary_delta)
    assert not excluded.eligible
    with pytest.raises(TypeError):
        EquivalenceInterval(1.9, 2.1)


def test_ranking_recomputes_eligibility_and_uses_frozen_index_for_ties() -> None:
    _, _, _, score = _complete_score()
    estimate = _estimate(score, repetitions=13)
    higher_index = _assessment("arm-higher", 8, score, estimate)
    lower_index = _assessment("arm-lower", 3, score, estimate)

    ranked = rank_eligible_arms((higher_index, lower_index))
    assessments = (higher_index, lower_index)
    winner = select_winner(
        assessments,
        _contract(assessments, _digest("committed-hidden-plan")),
    )

    assert tuple(arm.configuration_index for arm in ranked) == (3, 8)
    assert winner.winner.configuration_index == 3
    with pytest.raises(TypeError):
        replace(lower_index, eligible=False)


def test_no_eligible_arm_fails_closed() -> None:
    _, _, _, score = _complete_score()
    estimate = _estimate(score, repetitions=13)
    assessment = _assessment(
        "arm-a",
        0,
        score,
        estimate,
        gates=replace(_passed_gates(), provenance_valid=False),
    )

    with pytest.raises(NoEligibleArmError, match="no arm"):
        select_winner(
            (assessment,),
            _contract((assessment,), _digest("committed-hidden-plan")),
        )


def test_hidden_validation_requires_distinct_plan_and_never_substitutes_runner_up() -> None:
    _, _, _, selection_score = _complete_score(plan_identity="selection")
    _, _, _, hidden_score = _complete_score(
        plan_identity="hidden",
        plan_scale=0.85,
    )
    selection_estimate = _estimate(selection_score, repetitions=13)
    first = _assessment("arm-first", 0, selection_score, selection_estimate)
    second = _assessment("arm-second", 1, selection_score, selection_estimate)
    assessments = (first, second)
    winner = select_winner(
        assessments,
        _contract(assessments, hidden_score.plan_id),
    )

    hidden_estimate = _estimate(hidden_score, seed=97, repetitions=13)
    failed_hidden = _assessment(
        "arm-first",
        0,
        hidden_score,
        hidden_estimate,
        stage="hidden_validation",
        gates=replace(_passed_gates(), fit_quality_passed=False),
    )
    result = apply_hidden_validation(winner, failed_hidden)

    assert failed_hidden.plan_id != winner.winner.plan_id
    assert failed_hidden.score_id != winner.winner.score_id
    assert not result.passed
    assert result.experiment_stopped
    assert result.validated_winner is None
    assert result.selected_winner.arm_id == "arm-first"

    reused = replace(winner.winner, assessment_stage="hidden_validation")
    with pytest.raises(SelectionDataError, match="committed at winner selection"):
        apply_hidden_validation(winner, reused)
    with pytest.raises(SelectionDataError, match="hidden evidence"):
        HiddenValidationResult(selection=winner, hidden_assessment=winner.winner)
    with pytest.raises(SelectionDataError, match="locked equivalence delta"):
        apply_hidden_validation(
            winner,
            replace(
                failed_hidden,
                equivalence_interval=EquivalenceInterval.from_delta(0.1),
            ),
        )


def test_same_plan_with_changed_responses_is_not_hidden_validation() -> None:
    reference, plans, _, score = _complete_score()
    estimate = _estimate(score, repetitions=13)
    selected = _assessment("arm-a", 0, score, estimate)
    winner = select_winner(
        (selected,),
        _contract((selected,), _digest("different-hidden-plan")),
    )
    changed_responses = tuple(
        _linear_response(reference, plan, epoch_slopes=np.full(4, 0.99)) for plan in plans
    )
    changed_score = score_injection_responses(
        reference,
        plans,
        changed_responses,
        _policy(),
    )
    changed_estimate = _estimate(changed_score, repetitions=13)
    hidden = _assessment(
        "arm-a",
        0,
        changed_score,
        changed_estimate,
        stage="hidden_validation",
    )

    assert hidden.score_id != winner.winner.score_id
    assert hidden.plan_id == winner.winner.plan_id
    with pytest.raises(SelectionDataError, match="committed at winner selection"):
        apply_hidden_validation(winner, hidden)


def test_hidden_bank_must_match_commitment_and_be_fully_disjoint() -> None:
    reference, selection_plans, _, selection_score = _complete_score()
    selection_estimate = _estimate(selection_score, repetitions=9)
    selected = _assessment("arm-a", 0, selection_score, selection_estimate)

    distinct_plans = _plans(reference, identity="hidden", pattern_scale=0.8)
    overlapping_plans = (
        InjectionPlan(
            "hidden-shared",
            reference.epoch_ids,
            selection_plans[0].velocities,
        ),
        *distinct_plans[1:],
    )
    overlapping_score = score_injection_responses(
        reference,
        overlapping_plans,
        tuple(_linear_response(reference, plan) for plan in overlapping_plans),
        _policy(),
    )
    winner = select_winner(
        (selected,),
        _contract(
            (selected,),
            overlapping_score.plan_id,
            expected_hidden_bootstrap_seed=73,
        ),
    )
    overlapping_hidden = _assessment(
        "arm-a",
        0,
        overlapping_score,
        _estimate(overlapping_score, seed=73, repetitions=9),
        stage="hidden_validation",
    )

    with pytest.raises(SelectionDataError, match="fully disjoint"):
        apply_hidden_validation(winner, overlapping_hidden)

    wrong_commitment = select_winner(
        (selected,),
        _contract((selected,), _digest("wrong-hidden-commitment")),
    )
    with pytest.raises(SelectionDataError, match="committed at winner selection"):
        apply_hidden_validation(wrong_commitment, overlapping_hidden)


def test_hidden_validation_locks_configuration_data_and_uncertainty_contract() -> None:
    reference, _, _, selection_score = _complete_score()
    hidden_plans = _plans(reference, identity="hidden", pattern_scale=0.8)
    hidden_responses = tuple(_linear_response(reference, plan) for plan in hidden_plans)
    hidden_score = score_injection_responses(
        reference,
        hidden_plans,
        hidden_responses,
        _policy(),
    )
    selection_estimate = _estimate(selection_score, seed=41, repetitions=7)
    selected = _assessment("arm-a", 0, selection_score, selection_estimate)
    winner = select_winner(
        (selected,),
        _contract(
            (selected,),
            hidden_score.plan_id,
            expected_hidden_bootstrap_seed=99,
        ),
    )
    hidden = _assessment(
        "arm-a",
        0,
        hidden_score,
        _estimate(hidden_score, seed=99, repetitions=7),
        stage="hidden_validation",
    )

    assert apply_hidden_validation(winner, hidden).passed
    adaptively_reseeded = _assessment(
        "arm-a",
        0,
        hidden_score,
        _estimate(hidden_score, seed=100, repetitions=7),
        stage="hidden_validation",
    )
    with pytest.raises(SelectionDataError, match="seed.*committed"):
        apply_hidden_validation(winner, adaptively_reseeded)
    with pytest.raises(SelectionDataError, match="locked winner"):
        apply_hidden_validation(
            winner,
            replace(
                hidden,
                configuration_identity=_digest("different-configuration"),
            ),
        )
    with pytest.raises(SelectionDataError, match="uncertainty contract"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                hidden_score,
                _estimate(hidden_score, seed=99, repetitions=9),
                stage="hidden_validation",
            ),
        )

    changed_policy = AttritionPolicy(
        minimum_reference_orders=3,
        minimum_common_orders=2,
        maximum_lost_orders=0,
        maximum_lost_fraction=0.0,
        attrition_action="fail_primary",
    )
    policy_score = score_injection_responses(
        reference,
        hidden_plans,
        hidden_responses,
        changed_policy,
    )
    with pytest.raises(SelectionDataError, match="attrition policy"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                policy_score,
                _estimate(policy_score, seed=99, repetitions=7),
                stage="hidden_validation",
            ),
        )

    changed_rv = np.array(reference.rv, copy=True)
    changed_rv[0, 0] = 0.2
    changed_reference = ReferenceResponse(
        epoch_ids=reference.epoch_ids,
        cluster_ids=reference.cluster_ids,
        order_ids=reference.order_ids,
        rv=changed_rv,
        uncertainty=reference.uncertainty,
        valid_mask=reference.valid_mask,
    )
    reference_score = score_injection_responses(
        changed_reference,
        hidden_plans,
        tuple(_linear_response(changed_reference, plan) for plan in hidden_plans),
        _policy(),
    )
    with pytest.raises(SelectionDataError, match="reference evidence"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                reference_score,
                _estimate(reference_score, seed=99, repetitions=7),
                stage="hidden_validation",
            ),
        )

    changed_clusters = ReferenceResponse(
        epoch_ids=reference.epoch_ids,
        cluster_ids=("changed-a", "changed-b", "changed-c", "changed-d"),
        order_ids=reference.order_ids,
        rv=reference.rv,
        uncertainty=reference.uncertainty,
        valid_mask=reference.valid_mask,
    )
    cluster_score = score_injection_responses(
        changed_clusters,
        hidden_plans,
        tuple(_linear_response(changed_clusters, plan) for plan in hidden_plans),
        _policy(),
    )
    with pytest.raises(SelectionDataError, match="cluster identities"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                cluster_score,
                _estimate(cluster_score, seed=99, repetitions=7),
                stage="hidden_validation",
            ),
        )

    reordered_orders = ReferenceResponse(
        epoch_ids=reference.epoch_ids,
        cluster_ids=reference.cluster_ids,
        order_ids=tuple(reversed(reference.order_ids)),
        rv=reference.rv[:, ::-1],
        uncertainty=reference.uncertainty[:, ::-1],
        valid_mask=reference.valid_mask[:, ::-1],
    )
    order_score = score_injection_responses(
        reordered_orders,
        hidden_plans,
        tuple(_linear_response(reordered_orders, plan) for plan in hidden_plans),
        _policy(),
    )
    with pytest.raises(SelectionDataError, match="order identities"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                order_score,
                _estimate(order_score, seed=99, repetitions=7),
                stage="hidden_validation",
            ),
        )

    permutation = np.array([2, 0, 3, 1])
    reordered_epochs = ReferenceResponse(
        epoch_ids=tuple(reference.epoch_ids[index] for index in permutation),
        cluster_ids=tuple(reference.cluster_ids[index] for index in permutation),
        order_ids=reference.order_ids,
        rv=reference.rv[permutation],
        uncertainty=reference.uncertainty[permutation],
        valid_mask=reference.valid_mask[permutation],
    )
    reordered_hidden_plans = tuple(
        InjectionPlan(
            plan.injection_id,
            reordered_epochs.epoch_ids,
            plan.velocities[permutation],
        )
        for plan in hidden_plans
    )
    epoch_score = score_injection_responses(
        reordered_epochs,
        reordered_hidden_plans,
        tuple(_linear_response(reordered_epochs, plan) for plan in reordered_hidden_plans),
        _policy(),
    )
    assert epoch_score.plan_id == hidden_score.plan_id
    with pytest.raises(SelectionDataError, match="epoch identities"):
        apply_hidden_validation(
            winner,
            _assessment(
                "arm-a",
                0,
                epoch_score,
                _estimate(epoch_score, seed=99, repetitions=7),
                stage="hidden_validation",
            ),
        )


def test_recovery_estimate_rejects_forged_interval_and_failure_state() -> None:
    _, _, _, score = _complete_score()
    estimate = _estimate(score, repetitions=13)

    with pytest.raises(SelectionDataError, match="fit_ready"):
        replace(score, fit_ready=False)
    with pytest.raises(SelectionDataError, match="attrition_gate_passed"):
        replace(score, attrition_gate_passed=False)
    with pytest.raises(SelectionDataError, match="reversed"):
        replace(estimate, confidence_lower=1.1, confidence_upper=0.9)
    with pytest.raises(SelectionDataError, match="independent-cluster minimum"):
        replace(estimate, actual_independent_clusters=1)
    with pytest.raises(SelectionDataError, match="finite/NaN"):
        replace(
            estimate,
            failures=(BootstrapFailure(0, "SyntheticFailure", "planned failure"),),
            confidence_lower=None,
            confidence_upper=None,
        )


def test_score_rejects_forged_response_reference_and_canonical_id() -> None:
    _, _, _, score = _complete_score()
    first_epoch = score.epoch_records[0]
    for changes in (
        {"accepted_for_fit": 1},
        {"lost_order_count": False},
    ):
        with pytest.raises(TypeError, match="native"):
            replace(first_epoch, **changes)
    with pytest.raises(TypeError, match="native boolean"):
        replace(first_epoch.order_records[0], common_valid=1)

    records = list(score.epoch_records)
    first_epoch = records[0]
    first_orders = list(first_epoch.order_records)
    first_orders[0] = replace(
        first_orders[0],
        response=first_orders[0].response + 0.25,
    )
    records[0] = replace(first_epoch, order_records=tuple(first_orders))
    with pytest.raises(SelectionDataError, match="injected minus reference"):
        replace(score, epoch_records=tuple(records))

    records = list(score.epoch_records)
    second_plan_epoch = len(score.epoch_ids)
    changed_epoch = records[second_plan_epoch]
    changed_orders = list(changed_epoch.order_records)
    changed_order = changed_orders[0]
    changed_orders[0] = replace(
        changed_order,
        reference_rv=changed_order.reference_rv + 1.0,
        response=changed_order.response - 1.0,
    )
    changed_mean = float(np.mean([value.response for value in changed_orders]))
    records[second_plan_epoch] = replace(
        changed_epoch,
        mean_response=changed_mean,
        order_records=tuple(changed_orders),
    )
    with pytest.raises(SelectionDataError, match="inconsistent across injection audits"):
        replace(score, epoch_records=tuple(records))

    records = list(score.epoch_records)
    changed_epoch = records[0]
    changed_orders = list(changed_epoch.order_records)
    changed_orders[0] = replace(
        changed_orders[0],
        injected_uncertainty=changed_orders[0].injected_uncertainty + 0.1,
    )
    records[0] = replace(changed_epoch, order_records=tuple(changed_orders))
    with pytest.raises(SelectionDataError, match="canonical score evidence"):
        replace(score, epoch_records=tuple(records))

    with pytest.raises(SelectionDataError, match="canonical score evidence"):
        replace(score, score_id=_digest("forged-score-id"))


def test_native_string_boundaries_reject_hostile_digest_label_and_message_subclasses() -> None:
    reference, _, _, score = _complete_score()
    estimate = _estimate(score, repetitions=7)
    arm = _assessment("arm-a", 0, score, estimate)
    hidden_digest = _digest("hidden-plan")

    with pytest.raises(TypeError, match="native string"):
        InjectionPlan(EvilLabel("injection-a"), reference.epoch_ids, np.ones(4))
    with pytest.raises(SelectionDataError, match="non-empty strings"):
        replace(reference, epoch_ids=(EvilLabel("epoch-0"), *reference.epoch_ids[1:]))
    with pytest.raises(TypeError, match="native string"):
        replace(_policy(), attrition_action=EvilLabel("fail_primary"))
    with pytest.raises(TypeError, match="native string"):
        replace(score.epoch_records[0].order_records[0], status=EvilLabel("common"))
    with pytest.raises(SelectionDataError, match="non-empty strings"):
        replace(score.epoch_records[0], failure_reasons=(EvilLabel("forged"),))
    with pytest.raises(TypeError, match="native string"):
        BootstrapFailure(0, EvilLabel("SyntheticFailure"), "planned failure")
    with pytest.raises(TypeError, match="native string"):
        replace(estimate, interval_method=EvilLabel(estimate.interval_method))
    with pytest.raises(TypeError, match="native string"):
        replace(arm, assessment_stage=EvilLabel("selection"))
    with pytest.raises(TypeError, match="native string"):
        ArmRosterEntry(EvilLabel("arm-a"), 0, _digest("configuration-0"))
    with pytest.raises(TypeError, match="native string"):
        ArmRosterEntry("arm-a", 0, EvilHex(_digest("configuration-0")))
    with pytest.raises(TypeError, match="native string"):
        SelectionContract(
            expected_arms=(ArmRosterEntry("arm-a", 0, _digest("configuration-0")),),
            expected_hidden_plan_id=EvilHex(hidden_digest),
            expected_hidden_bootstrap_seed=97,
        )


def test_native_audit_floats_reject_hostile_response_and_mean_arithmetic() -> None:
    _, _, _, score = _complete_score()
    epoch = score.epoch_records[0]
    order = epoch.order_records[0]
    assert order.response is not None
    assert order.injected_rv is not None
    assert epoch.mean_response is not None

    with pytest.raises(TypeError, match="native float"):
        replace(order, response=EvilFloat(order.response + 10.0))
    with pytest.raises(TypeError, match="native float"):
        replace(order, injected_rv=EvilFloat(order.injected_rv + 10.0))
    with pytest.raises(TypeError, match="native float"):
        replace(epoch, mean_response=EvilFloat(epoch.mean_response + 10.0))
    with pytest.raises(TypeError, match="native float"):
        replace(epoch, lost_fraction=EvilFloat(epoch.lost_fraction))


def test_arm_assessment_recomputes_every_estimate_field_from_score() -> None:
    _, _, _, score = _complete_score(epoch_slopes=np.array([0.8, 0.95, 1.05, 1.2]))
    estimate = _estimate(score, repetitions=13)
    assert estimate.confidence_lower is not None
    assert estimate.confidence_upper is not None
    shifted_statistics = np.array(estimate.bootstrap_slopes) + 0.1
    shifted = replace(
        estimate,
        bootstrap_slopes=shifted_statistics,
        confidence_lower=estimate.confidence_lower + 0.1,
        confidence_upper=estimate.confidence_upper + 0.1,
    )
    with pytest.raises(SelectionDataError, match="deterministic recomputation"):
        _assessment("arm-a", 0, score, shifted, delta=0.5)

    changed_draws = list(estimate.cluster_draws)
    changed_draws[0] = ("forged-cluster", *changed_draws[0][1:])
    forged_draw = replace(estimate, cluster_draws=tuple(changed_draws))
    with pytest.raises(SelectionDataError, match="deterministic recomputation"):
        _assessment("arm-a", 0, score, forged_draw, delta=0.5)

    forged_seed = replace(estimate, seed=estimate.seed + 1)
    with pytest.raises(SelectionDataError, match="deterministic recomputation"):
        _assessment("arm-a", 0, score, forged_seed, delta=0.5)

    forged_score_id = replace(estimate, score_id=_digest("unrelated-score"))
    with pytest.raises(SelectionDataError, match="does not belong"):
        _assessment("arm-a", 0, score, forged_score_id, delta=0.5)


def test_assessment_and_winner_reject_mismatched_or_forged_evidence() -> None:
    _, _, _, first_score = _complete_score(plan_identity="first")
    _, _, _, second_score = _complete_score(plan_identity="second")
    first_estimate = _estimate(first_score, repetitions=13)
    second_estimate = _estimate(second_score, repetitions=13)

    with pytest.raises(SelectionDataError, match="lowercase SHA-256"):
        assess_arm(
            "arm-a",
            0,
            "configuration-label",
            first_score,
            first_estimate,
            EquivalenceInterval(0.2),
            _passed_gates(),
            assessment_stage="selection",
        )
    with pytest.raises(SelectionDataError, match="does not belong"):
        ArmAssessment(
            arm_id="arm-a",
            configuration_index=0,
            configuration_identity=_digest("configuration-0"),
            assessment_stage="selection",
            score=first_score,
            estimate=second_estimate,
            equivalence_interval=EquivalenceInterval(0.2),
            gates=_passed_gates(),
        )
    low = _assessment("arm-low", 0, first_score, first_estimate)
    high = _assessment("arm-high", 1, first_score, first_estimate)
    ranked = rank_eligible_arms((low, high))
    contract = _contract((low, high), _digest("committed-hidden-plan"))
    with pytest.raises(SelectionDataError, match="rank order"):
        WinnerSelection(
            contract=contract,
            all_assessments=(low, high),
            winner=low,
            ranked_eligible=tuple(reversed(ranked)),
        )
    forged_winners = (
        replace(low, assessment_stage="hidden_validation"),
        replace(
            low,
            gates=replace(low.gates, catastrophic_fit_checks_passed=False),
        ),
        replace(low, equivalence_interval=EquivalenceInterval(0.25)),
        replace(low, estimate=_estimate(first_score, seed=87, repetitions=13)),
    )
    for forged_winner in forged_winners:
        with pytest.raises(SelectionDataError, match="first deterministically ranked"):
            WinnerSelection(
                contract=contract,
                all_assessments=(low, high),
                winner=forged_winner,
                ranked_eligible=ranked,
            )


def test_all_arms_must_share_the_full_selection_contract_before_filtering() -> None:
    reference, plans, responses, score = _complete_score()
    estimate = _estimate(score, seed=31, repetitions=7)
    baseline = _assessment("arm-a", 0, score, estimate)

    changed_policy = AttritionPolicy(
        minimum_reference_orders=3,
        minimum_common_orders=2,
        maximum_lost_orders=0,
        maximum_lost_fraction=0.0,
        attrition_action="fail_primary",
    )
    policy_score = score_injection_responses(
        reference,
        plans,
        responses,
        changed_policy,
    )
    policy_arm = _assessment(
        "arm-b",
        1,
        policy_score,
        _estimate(policy_score, seed=31, repetitions=7),
    )
    with pytest.raises(SelectionDataError, match="frozen selection contract"):
        rank_eligible_arms((baseline, policy_arm))

    seed_arm = _assessment(
        "arm-b",
        1,
        score,
        _estimate(score, seed=32, repetitions=7),
    )
    with pytest.raises(SelectionDataError, match="frozen selection contract"):
        rank_eligible_arms((baseline, seed_arm))

    delta_arm = _assessment("arm-b", 1, score, estimate, delta=0.25)
    with pytest.raises(SelectionDataError, match="frozen selection contract"):
        rank_eligible_arms((baseline, delta_arm))

    changed_reference = _reference(cluster_ids=("changed-a", "changed-b", "changed-c", "changed-d"))
    cluster_plans = tuple(
        InjectionPlan(
            plan.injection_id,
            changed_reference.epoch_ids,
            plan.velocities,
        )
        for plan in plans
    )
    cluster_score = score_injection_responses(
        changed_reference,
        cluster_plans,
        tuple(_linear_response(changed_reference, plan) for plan in cluster_plans),
        _policy(),
    )
    cluster_arm = _assessment(
        "arm-b",
        1,
        cluster_score,
        _estimate(cluster_score, seed=31, repetitions=7),
    )
    with pytest.raises(SelectionDataError, match="frozen selection contract"):
        rank_eligible_arms((baseline, cluster_arm))

    _, _, _, changed_plan_score = _complete_score(plan_scale=0.9)
    plan_arm = _assessment(
        "arm-b",
        1,
        changed_plan_score,
        _estimate(changed_plan_score, seed=31, repetitions=7),
    )
    with pytest.raises(SelectionDataError, match="frozen selection contract"):
        rank_eligible_arms((baseline, plan_arm))

    alternate_reference = ReferenceResponse(
        epoch_ids=reference.epoch_ids,
        cluster_ids=reference.cluster_ids,
        order_ids=("alternate-a", "alternate-b", "alternate-c"),
        rv=np.full(reference.rv.shape, 5.0),
        uncertainty=reference.uncertainty,
        valid_mask=reference.valid_mask,
    )
    alternate_plans = tuple(
        InjectionPlan(plan.injection_id, alternate_reference.epoch_ids, plan.velocities)
        for plan in plans
    )
    alternate_score = score_injection_responses(
        alternate_reference,
        alternate_plans,
        tuple(_linear_response(alternate_reference, plan) for plan in alternate_plans),
        _policy(),
    )
    alternate_arm = _assessment(
        "arm-b",
        1,
        alternate_score,
        _estimate(alternate_score, seed=31, repetitions=7),
    )
    assert len(rank_eligible_arms((baseline, alternate_arm))) == 2


def test_select_winner_requires_exact_precommitted_roster_and_retains_all_arms() -> None:
    _, _, _, score = _complete_score()
    _, _, _, hidden_score = _complete_score(plan_identity="hidden", plan_scale=0.8)
    estimate = _estimate(score, repetitions=7)
    eligible = _assessment("arm-a", 0, score, estimate)
    ineligible = _assessment(
        "arm-b",
        1,
        score,
        estimate,
        gates=replace(_passed_gates(), fit_quality_passed=False),
    )
    roster_assessments = (eligible, ineligible)
    contract = _contract(roster_assessments, hidden_score.plan_id)

    with pytest.raises(ValueError, match="non-negative"):
        SelectionContract(
            expected_arms=contract.expected_arms,
            expected_hidden_plan_id=hidden_score.plan_id,
            expected_hidden_bootstrap_seed=-1,
        )

    result = select_winner(tuple(reversed(roster_assessments)), contract)

    assert result.all_assessments == roster_assessments
    assert result.ranked_eligible == (eligible,)
    assert result.contract.expected_hidden_plan_id == hidden_score.plan_id
    with pytest.raises(SelectionDataError, match="precommitted arm roster"):
        select_winner((eligible,), contract)
    with pytest.raises(SelectionDataError, match="precommitted arm roster"):
        select_winner((eligible, eligible), contract)
    extra = _assessment("arm-c", 2, score, estimate)
    with pytest.raises(SelectionDataError, match="precommitted arm roster"):
        select_winner((eligible, ineligible, extra), contract)
    mismatched = replace(
        ineligible,
        configuration_identity=_digest("different-configuration-evidence"),
    )
    with pytest.raises(SelectionDataError, match="precommitted arm roster"):
        select_winner((eligible, mismatched), contract)
    with pytest.raises(SelectionDataError, match="hidden plan commitment"):
        select_winner(
            roster_assessments,
            _contract(roster_assessments, score.plan_id),
        )


def test_order_and_response_identity_reordering_is_rejected() -> None:
    reference = _reference()
    plan = _plans(reference)[0]
    response = _linear_response(reference, plan)
    reordered = InjectedResponse(
        injection_id=response.injection_id,
        epoch_ids=response.epoch_ids,
        order_ids=tuple(reversed(response.order_ids)),
        rv=response.rv[:, ::-1],
        uncertainty=response.uncertainty[:, ::-1],
        response_uncertainty=response.response_uncertainty[:, ::-1],
        valid_mask=response.valid_mask[:, ::-1],
    )

    with pytest.raises(SelectionDataError, match="order identity/order mismatch"):
        score_injection_responses(reference, (plan,), (reordered,), _policy())


def test_missing_common_paired_uncertainty_is_rejected() -> None:
    reference = _reference()
    plan = _plans(reference)[0]
    response = _linear_response(reference, plan)
    paired = np.array(response.response_uncertainty, copy=True)
    paired[0, 0] = np.nan
    missing = replace(response, response_uncertainty=paired)

    with pytest.raises(SelectionDataError, match="common cell"):
        score_injection_responses(reference, (plan,), (missing,), _policy())


@pytest.mark.parametrize(
    ("rv", "uncertainty", "valid_mask", "match"),
    [
        (
            np.array([[0.0]]),
            np.array([[0.0]]),
            np.array([[True]]),
            "positive finite uncertainties",
        ),
        (
            np.array([[np.inf]]),
            np.array([[1.0]]),
            np.array([[True]]),
            "positive finite uncertainties",
        ),
        (
            np.array([[0.0]]),
            np.array([[1.0]]),
            np.array([[False]]),
            "NaN RV and uncertainty sentinels",
        ),
    ],
)
def test_reference_mask_nonfinite_and_uncertainty_contracts_are_fail_closed(
    rv: np.ndarray,
    uncertainty: np.ndarray,
    valid_mask: np.ndarray,
    match: str,
) -> None:
    with pytest.raises(SelectionDataError, match=match):
        ReferenceResponse(
            epoch_ids=("epoch-a",),
            cluster_ids=("cluster-a",),
            order_ids=("order-a",),
            rv=rv,
            uncertainty=uncertainty,
            valid_mask=valid_mask,
        )


def test_inputs_are_defensively_copied_and_read_only() -> None:
    reference = _reference()
    velocities = np.array([-1.0, -0.5, 0.5, 1.0])
    plan = InjectionPlan("injection-a", reference.epoch_ids, velocities)
    velocities[0] = 99.0

    assert plan.velocities[0] == -1.0
    assert not plan.velocities.flags.writeable
    assert not reference.rv.flags.writeable
    assert not reference.uncertainty.flags.writeable
    assert not reference.valid_mask.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        plan.velocities[0] = 1.0
    _, _, responses, score = _complete_score()
    estimate = _estimate(score, repetitions=7)
    stored_arrays = (
        reference.rv,
        reference.uncertainty,
        reference.valid_mask,
        plan.velocities,
        responses[0].rv,
        responses[0].uncertainty,
        responses[0].response_uncertainty,
        responses[0].valid_mask,
        estimate.bootstrap_slopes,
    )
    for stored in stored_arrays:
        with pytest.raises(ValueError):
            stored.setflags(write=True)


def test_physical_plan_identity_is_epoch_keyed_signed_zero_canonical_and_label_free() -> None:
    reference = _reference()
    plans = (
        InjectionPlan(
            "pattern-a",
            reference.epoch_ids,
            np.array([0.0, 1.0, 2.0, 3.0]),
        ),
        InjectionPlan(
            "pattern-b",
            reference.epoch_ids,
            np.array([-2.0, -1.0, 1.0, 2.0]),
        ),
    )
    responses = tuple(_linear_response(reference, plan) for plan in plans)
    score = score_injection_responses(reference, plans, responses, _policy())

    permutation = np.array([2, 0, 3, 1])
    reordered_reference = ReferenceResponse(
        epoch_ids=tuple(reference.epoch_ids[index] for index in permutation),
        cluster_ids=tuple(reference.cluster_ids[index] for index in permutation),
        order_ids=reference.order_ids,
        rv=reference.rv[permutation],
        uncertainty=reference.uncertainty[permutation],
        valid_mask=reference.valid_mask[permutation],
    )
    reordered_plans = tuple(
        InjectionPlan(
            f"renamed-{index}",
            reordered_reference.epoch_ids,
            np.array([(-0.0 if value == 0.0 else value) for value in plan.velocities[permutation]]),
        )
        for index, plan in enumerate(plans)
    )
    reordered_responses = tuple(
        _linear_response(reordered_reference, plan) for plan in reordered_plans
    )
    reordered_score = score_injection_responses(
        reordered_reference,
        reordered_plans,
        reordered_responses,
        _policy(),
    )

    assert reordered_score.plan_id == score.plan_id
    assert set(reordered_score.velocity_pattern_ids) == set(score.velocity_pattern_ids)
    duplicate = InjectionPlan(
        "duplicate-label",
        reference.epoch_ids,
        np.array(plans[0].velocities, copy=True),
    )
    with pytest.raises(SelectionDataError, match="duplicate physical patterns"):
        score_injection_responses(reference, (plans[0], duplicate), (), _policy())
