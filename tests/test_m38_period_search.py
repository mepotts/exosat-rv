from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from exosat_rv.m38 import period_search
from exosat_rv.m38.period_search import (
    IncompleteCalibrationError,
    NumericalFitError,
    PeriodSearchError,
    PipelineOutcome,
    PipelineTrial,
    RankDeficiencyError,
    calibrate_global_max_statistic,
    run_adaptive_pipeline_calibration,
    weighted_sinusoid_search,
    wilson_interval,
)

SYNTHETIC_PIPELINE_ID = "synthetic-whole-pipeline-v1"
SYNTHETIC_RECOVERY_ID = "synthetic-recovery-rule-v1"


def test_wilson_interval_rejects_a_non_integer_success_type() -> None:
    with pytest.raises(TypeError, match="successes must be an integer"):
        wilson_interval(True, 1, confidence_level=0.95)


def test_weighted_search_recovers_a_generic_sinusoid_and_full_landscape() -> None:
    rng = np.random.default_rng(104)
    times = np.sort(rng.uniform(0.0, 72.0, 64))
    true_period = 8.0
    true_amplitude = 2.4
    phase = 0.37
    uncertainties = np.linspace(0.10, 0.18, times.size)
    values = (
        1.7
        + true_amplitude * np.sin(2.0 * np.pi * times / true_period + phase)
        + rng.normal(0.0, uncertainties)
    )
    periods = np.linspace(4.0, 12.0, 161)

    result = weighted_sinusoid_search(times, values, uncertainties, periods)

    assert result.best_period == pytest.approx(true_period, abs=0.05)
    assert result.amplitudes[result.best_index] == pytest.approx(true_amplitude, rel=0.05)
    np.testing.assert_array_equal(result.periods, periods)
    assert result.periodic_coefficients.shape == (periods.size, 3)
    assert result.chi2.shape == periods.shape
    assert result.delta_chi2.shape == periods.shape
    assert result.ranks.tolist() == [3] * periods.size
    assert result.dof.tolist() == [times.size - 3] * periods.size
    assert result.null_fit.rank == 1
    assert result.null_fit.dof == times.size - 1
    assert result.periodic_design_matrix(result.best_index).shape == (times.size, 3)
    assert np.all(result.delta_chi2 >= 0.0)
    assert not result.periods.flags.writeable


def test_nuisance_regressor_is_an_explicit_null_model_column() -> None:
    times = np.linspace(0.0, 30.0, 61)
    nuisance = (times - np.mean(times)) / np.ptp(times)
    values = 2.5 + 4.0 * nuisance
    uncertainties = np.full(times.size, 0.2)
    periods = np.linspace(3.0, 9.0, 31)

    controlled = weighted_sinusoid_search(
        times,
        values,
        uncertainties,
        periods,
        nuisance_regressors=nuisance,
    )
    uncontrolled = weighted_sinusoid_search(times, values, uncertainties, periods)

    assert controlled.null_design_matrix.shape == (times.size, 2)
    np.testing.assert_allclose(controlled.null_design_matrix[:, 1], nuisance)
    assert controlled.null_fit.rank == 2
    assert controlled.null_fit.chi2 < 1e-20
    assert controlled.max_statistic < 1e-20
    assert uncontrolled.max_statistic > 50.0


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda t, y, s, p: (t, y, -s, p), PeriodSearchError),
        (lambda t, y, s, p: (t, y, s, p[::-1]), PeriodSearchError),
        (
            lambda t, y, s, p: (np.zeros_like(t), y, s, p),
            RankDeficiencyError,
        ),
    ],
)
def test_search_fails_closed_on_invalid_inputs_and_rank(
    mutator: Callable[
        [np.ndarray, np.ndarray, np.ndarray, np.ndarray],
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ],
    error: type[Exception],
) -> None:
    times = np.linspace(0.0, 10.0, 20)
    values = np.sin(times)
    uncertainties = np.ones(times.size)
    periods = np.linspace(2.0, 5.0, 8)

    with pytest.raises(error):
        weighted_sinusoid_search(*mutator(times, values, uncertainties, periods))


def test_search_rejects_rank_deficient_nuisance_model() -> None:
    times = np.linspace(0.0, 12.0, 25)
    with pytest.raises(RankDeficiencyError, match="null model design is rank deficient"):
        weighted_sinusoid_search(
            times,
            np.cos(times),
            np.ones(times.size),
            np.linspace(2.0, 6.0, 10),
            nuisance_regressors=np.ones(times.size),
        )


def test_global_max_calibration_is_plus_one_monotone_and_reproducible() -> None:
    rng = np.random.default_rng(812)
    times = np.sort(rng.uniform(0.0, 45.0, 44))
    uncertainties = np.full(times.size, 0.35)
    periods = np.linspace(3.0, 12.0, 46)
    noise = rng.normal(0.0, uncertainties)
    weak_values = 0.8 + noise
    strong_values = weak_values + 2.8 * np.sin(2.0 * np.pi * times / 6.0 + 0.2)

    weak = calibrate_global_max_statistic(
        times,
        weak_values,
        uncertainties,
        periods,
        simulations=63,
        seed=9124,
    )
    strong = calibrate_global_max_statistic(
        times,
        strong_values,
        uncertainties,
        periods,
        simulations=63,
        seed=9124,
    )
    repeated = calibrate_global_max_statistic(
        times,
        strong_values,
        uncertainties,
        periods,
        simulations=63,
        seed=9124,
    )

    assert weak.complete and strong.complete
    assert strong.p_value is not None and weak.p_value is not None
    assert strong.p_value <= weak.p_value
    assert strong.p_value <= 0.05
    assert strong.p_value == (strong.exceedance_count + 1) / 64
    assert strong.simulation_statistics.shape == (63,)
    assert len(strong.simulation_seeds) == 63
    np.testing.assert_array_equal(strong.simulation_statistics, repeated.simulation_statistics)
    assert strong.simulation_seeds == repeated.simulation_seeds


def test_global_calibration_never_shrinks_to_successful_simulations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = np.linspace(0.0, 18.0, 28)
    values = np.sin(2.0 * np.pi * times / 4.0)
    uncertainties = np.full(times.size, 0.3)
    periods = np.linspace(2.0, 7.0, 20)
    original = period_search.weighted_sinusoid_search
    call_count = 0

    def fail_one_simulation(*args: object, **kwargs: object):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise NumericalFitError("synthetic trial failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(period_search, "weighted_sinusoid_search", fail_one_simulation)
    calibration = calibrate_global_max_statistic(
        times,
        values,
        uncertainties,
        periods,
        simulations=7,
        seed=22,
    )

    assert call_count == 8  # one observed search plus every requested simulation
    assert len(calibration.failures) == 1
    assert np.count_nonzero(np.isnan(calibration.simulation_statistics)) == 1
    assert calibration.exceedance_count is None
    assert calibration.p_value is None
    assert not calibration.complete


def test_adaptive_harness_invokes_every_trial_once_with_fresh_ids() -> None:
    seen_ids: list[str] = []

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        seen_ids.append(trial.trial_id)
        rng = np.random.default_rng(trial.trial_seed)
        base = 0.0 if trial.amplitude is None else trial.amplitude
        return PipelineOutcome(
            trial_id=trial.trial_id,
            max_statistic=float(base + rng.uniform(-0.1, 0.1)),
            details=trial.phase,
        )

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: outcome.details == trial.phase,
        null_trials=3,
        amplitudes=[0.0, 2.0],
        phases=[0.0, 1.0],
        replicates_per_cell=2,
        null_seed=31,
        signal_seed=41,
        evidence_threshold=1.0,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )

    assert len(seen_ids) == 3 + 2 * 2 * 2
    assert len(set(seen_ids)) == len(seen_ids)
    assert len(result.null.records) == 3
    assert len(result.completeness.records) == 8
    assert result.null.plan_id == result.plan_id == result.completeness.plan_id
    assert all(record.trial.plan_id == result.plan_id for record in result.null.records)
    assert all(record.trial.plan_id == result.plan_id for record in result.completeness.records)
    assert result.complete
    assert result.null.plus_one_p_value(1.0) == pytest.approx(1.0 / 4.0)


def test_pipeline_outcome_details_are_detached_per_trial() -> None:
    shared_details: dict[str, object] = {}

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        shared_details["trial_id"] = trial.trial_id
        return PipelineOutcome(trial.trial_id, 1.0, details=shared_details)

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: outcome.details == {"trial_id": trial.trial_id},
        null_trials=2,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=2,
        null_seed=18,
        signal_seed=19,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    records = (*result.null.records, *result.completeness.records)

    shared_details["trial_id"] = "mutated after every callback"
    for record in records:
        assert record.outcome is not None
        assert record.outcome.details == {"trial_id": record.trial.trial_id}
        assert record.outcome.details is not shared_details


@pytest.mark.parametrize(
    ("bad_statistic", "exception_type"),
    [
        ("not-a-number", "ValueError"),
        (np.nan, "NonFiniteStatistic"),
    ],
)
def test_invalid_statistics_never_retain_caller_owned_details(
    bad_statistic: object,
    exception_type: str,
) -> None:
    shared_details: dict[str, object] = {}

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        shared_details["last_trial_id"] = trial.trial_id
        return PipelineOutcome(
            trial.trial_id,
            bad_statistic,
            details=shared_details,
        )

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=2,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=26,
        signal_seed=27,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    records = (*result.null.records, *result.completeness.records)

    shared_details["last_trial_id"] = "mutated after all callbacks"
    assert len(records) == 3
    assert all(record.outcome is None for record in records)
    assert all(record.failure is not None for record in records)
    assert all(record.failure.exception_type == exception_type for record in records)


def test_recovery_rule_cannot_mutate_recorded_pipeline_details() -> None:
    def recovery_rule(trial: PipelineTrial, outcome: PipelineOutcome) -> bool:
        assert isinstance(outcome.details, dict)
        outcome.details["rule_mutation"] = trial.trial_id
        return True

    result = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(
            trial.trial_id,
            1.0,
            details={"callback_value": trial.trial_id},
        ),
        recovery_rule,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=24,
        signal_seed=25,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    record = result.completeness.records[0]

    assert record.failure is None
    assert record.recovered
    assert record.outcome is not None
    assert record.outcome.details == {"callback_value": record.trial.trial_id}


def test_cyclic_pipeline_details_become_auditable_outcome_failures() -> None:
    cyclic_details: dict[str, object] = {}
    cyclic_details["self"] = cyclic_details

    result = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 1.0, details=cyclic_details),
        lambda trial, outcome: True,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=20,
        signal_seed=21,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    failures = (*result.null.failures, *result.completeness.failures)

    assert len(failures) == 2
    assert all(failure.stage == "outcome" for failure in failures)
    assert all(failure.exception_type == "ValueError" for failure in failures)
    assert all("cyclic JSON container" in failure.message for failure in failures)


def test_plan_metadata_rejects_cycles_and_excessive_depth_before_execution() -> None:
    callback_calls = 0

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        nonlocal callback_calls
        callback_calls += 1
        return PipelineOutcome(trial.trial_id, 1.0)

    common = {
        "null_trials": 1,
        "amplitudes": [1.0],
        "phases": [0.0],
        "replicates_per_cell": 1,
        "null_seed": 22,
        "signal_seed": 23,
        "evidence_threshold": 0.5,
        "confidence_level": 0.95,
        "interval_method": "wilson",
        "pipeline_identity": SYNTHETIC_PIPELINE_ID,
        "recovery_rule_identity": SYNTHETIC_RECOVERY_ID,
    }
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cyclic JSON container"):
        run_adaptive_pipeline_calibration(
            pipeline,
            lambda trial, outcome: True,
            plan_metadata=cyclic,
            **common,
        )

    deeply_nested: dict[str, object] = {}
    cursor = deeply_nested
    for _ in range(66):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ValueError, match="strict-JSON maximum depth"):
        run_adaptive_pipeline_calibration(
            pipeline,
            lambda trial, outcome: True,
            plan_metadata=deeply_nested,
            **common,
        )

    assert callback_calls == 0


def test_cross_plan_cached_outcomes_are_rejected_as_stale() -> None:
    cache: dict[tuple[str, int | None, int | None, int], PipelineOutcome] = {}

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        key = (
            trial.kind,
            trial.amplitude_index,
            trial.phase_index,
            trial.replicate_index,
        )
        if key not in cache:
            statistic = 0.0 if trial.amplitude is None else trial.amplitude
            cache[key] = PipelineOutcome(trial.trial_id, statistic)
        return cache[key]

    common = {
        "null_trials": 2,
        "phases": [0.0],
        "replicates_per_cell": 1,
        "null_seed": 111,
        "signal_seed": 222,
        "evidence_threshold": 0.5,
        "confidence_level": 0.95,
        "interval_method": "wilson",
        "pipeline_identity": SYNTHETIC_PIPELINE_ID,
        "recovery_rule_identity": SYNTHETIC_RECOVERY_ID,
    }
    first = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        amplitudes=[0.0, 1.0],
        **common,
    )
    second = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        amplitudes=[0.0, 2.0],
        **common,
    )

    assert first.complete
    assert first.plan_id != second.plan_id
    assert not second.complete
    failures = (*second.null.failures, *second.completeness.failures)
    assert len(failures) == 4
    assert all(failure.exception_type == "StaleTrialOutcome" for failure in failures)


def test_equal_master_seeds_still_produce_disjoint_domain_child_seeds() -> None:
    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        return PipelineOutcome(trial.trial_id, float(trial.trial_seed % 17))

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=4,
        amplitudes=[0.0, 1.0],
        phases=[0.0, 1.0],
        replicates_per_cell=2,
        null_seed=333,
        signal_seed=333,
        evidence_threshold=1.0,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    null_child_seeds = {record.trial.trial_seed for record in result.null.records}
    signal_child_seeds = {record.trial.trial_seed for record in result.completeness.records}

    assert null_child_seeds.isdisjoint(signal_child_seeds)
    assert len(null_child_seeds) == 4
    assert len(signal_child_seeds) == 8


def test_failed_signal_trial_is_recorded_and_counted_as_nonrecovery() -> None:
    callback_count = 0

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        nonlocal callback_count
        callback_count += 1
        if trial.kind == "signal" and trial.phase_index == 0 and trial.replicate_index == 0:
            raise RuntimeError("declared synthetic failure")
        statistic = 0.0 if trial.amplitude is None else trial.amplitude + 1.0
        return PipelineOutcome(trial.trial_id, statistic)

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=2,
        amplitudes=[2.0],
        phases=[0.0, 1.0],
        replicates_per_cell=2,
        null_seed=51,
        signal_seed=61,
        evidence_threshold=2.5,
        confidence_level=0.90,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    point = result.completeness.points[0]

    assert callback_count == 2 + 4
    assert point.planned_trials == 4
    assert point.failed_trials == 1
    assert point.recovered_trials == 3
    assert point.completeness == pytest.approx(0.75)
    assert len(result.completeness.failures) == 1
    assert not result.completeness.complete
    assert point.interval.lower < point.completeness < point.interval.upper
    with pytest.raises(ValueError, match="interpolation is disabled"):
        result.completeness.completeness_at(2.1)


def test_incomplete_pipeline_null_refuses_a_p_value() -> None:
    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        if trial.kind == "null" and trial.replicate_index == 1:
            raise RuntimeError("synthetic null failure")
        return PipelineOutcome(trial.trial_id, 0.0)

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=3,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=71,
        signal_seed=81,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )

    assert len(result.null.failures) == 1
    assert np.isnan(result.null.statistics[1])
    with pytest.raises(IncompleteCalibrationError):
        result.null.plus_one_p_value(0.5)


def test_completeness_rises_with_amplitude_and_seeded_run_is_reproducible() -> None:
    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        rng = np.random.default_rng(trial.trial_seed)
        if trial.kind == "null":
            statistic = rng.uniform(0.0, 0.4)
        else:
            assert trial.amplitude is not None
            statistic = trial.amplitude + rng.uniform(-0.1, 0.1)
        return PipelineOutcome(trial.trial_id, float(statistic), details=trial.phase)

    kwargs = {
        "null_trials": 5,
        "amplitudes": [0.0, 1.0, 2.0, 3.0],
        "phases": [0.0, 0.5, 1.0, 1.5],
        "replicates_per_cell": 3,
        "null_seed": 91,
        "signal_seed": 101,
        "evidence_threshold": 1.5,
        "confidence_level": 0.95,
        "interval_method": "wilson",
        "pipeline_identity": SYNTHETIC_PIPELINE_ID,
        "recovery_rule_identity": SYNTHETIC_RECOVERY_ID,
        "interpolation_policy": "linear",
    }
    first = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: outcome.details == trial.phase,
        **kwargs,
    )
    second = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: outcome.details == trial.phase,
        **kwargs,
    )

    estimates = [point.completeness for point in first.completeness.points]
    assert estimates == sorted(estimates)
    assert estimates[0] < estimates[-1]
    assert first.completeness.completeness_at(1.5) == pytest.approx(0.5)
    assert first.false_alarm_probability_at_threshold() == pytest.approx(1.0 / 6.0)
    assert [record.trial.trial_id for record in first.completeness.records] == [
        record.trial.trial_id for record in second.completeness.records
    ]
    np.testing.assert_array_equal(first.null.statistics, second.null.statistics)
    np.testing.assert_array_equal(
        [record.outcome.max_statistic for record in first.completeness.records],
        [record.outcome.max_statistic for record in second.completeness.records],
    )
