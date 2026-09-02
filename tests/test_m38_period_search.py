from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

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
    SignalAxis,
    SignalTrialPlan,
    calibrate_global_max_statistic,
    run_adaptive_pipeline_calibration,
    run_adaptive_pipeline_grid_calibration,
    weighted_sinusoid_search,
    wilson_interval,
)

SYNTHETIC_PIPELINE_ID = "a" * 64
SYNTHETIC_RECOVERY_ID = "b" * 64


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
    assert strong.result_identity == repeated.result_identity
    assert strong.verify_integrity().result_identity == strong.result_identity
    with pytest.raises(ValueError, match="does not replay"):
        replace(
            strong,
            simulation_statistics=np.zeros_like(strong.simulation_statistics),
            exceedance_count=0,
            p_value=1.0 / 64.0,
        )
    tampered = strong.verify_integrity()
    object.__setattr__(
        tampered,
        "simulation_statistics",
        np.zeros_like(tampered.simulation_statistics),
    )
    with pytest.raises(ValueError, match="does not replay"):
        tampered.verify_integrity()


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

    # One observed search, all seven requested simulations, then deterministic replay of
    # the six successful statistics at the calibration trust boundary.
    assert call_count == 14
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
        ("not-a-number", "pipeline_outcome_statistic_type"),
        (np.nan, "pipeline_outcome_nonfinite"),
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
    assert all(failure.exception_type == "pipeline_outcome_details_invalid" for failure in failures)
    assert all(failure.message.startswith("diagnostic_sha256:") for failure in failures)


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
    assert all(failure.exception_type == "pipeline_outcome_stale" for failure in failures)


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


def test_signal_trial_plan_binds_every_explicit_axis_without_defaults() -> None:
    plan = SignalTrialPlan(
        axes=(
            SignalAxis("period", (5.0, 7.0)),
            SignalAxis("eccentricity", (0.0, 0.3)),
            SignalAxis("amplitude", (1.0, 2.0)),
        ),
        replicates_per_cell=3,
    )

    assert plan.cell_count == 8
    assert plan.trial_count == 24
    assert len(plan.identity) == 64
    assert (
        plan.identity
        != SignalTrialPlan(
            axes=(
                SignalAxis("period", (5.0, 8.0)),
                SignalAxis("eccentricity", (0.0, 0.3)),
                SignalAxis("amplitude", (1.0, 2.0)),
            ),
            replicates_per_cell=3,
        ).identity
    )
    with pytest.raises(ValueError, match="axis names must be unique"):
        SignalTrialPlan(
            axes=(SignalAxis("period", (5.0,)), SignalAxis("period", (7.0,))),
            replicates_per_cell=1,
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        SignalAxis("period", (5.0, 5.0))


def test_multi_axis_pipeline_grid_replays_every_cell_and_rejects_wrong_association() -> None:
    calls: list[PipelineTrial] = []

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        calls.append(trial)
        if trial.kind == "null":
            return PipelineOutcome(trial.trial_id, 0.1)
        parameters = dict(trial.signal_parameters or ())
        return PipelineOutcome(
            trial.trial_id,
            parameters["amplitude"] + 1.0,
            details={"recovered_period": 5.0},
        )

    def recovery_rule(trial: PipelineTrial, outcome: PipelineOutcome) -> bool:
        parameters = dict(trial.signal_parameters or ())
        assert isinstance(outcome.details, dict)
        return abs(float(outcome.details["recovered_period"]) - parameters["period"]) <= 0.01

    signal_plan = SignalTrialPlan(
        axes=(
            SignalAxis("period", (5.0, 7.0)),
            SignalAxis("amplitude", (1.0, 2.0)),
            SignalAxis("phase", (0.0, 0.5)),
        ),
        replicates_per_cell=2,
    )
    result = run_adaptive_pipeline_grid_calibration(
        pipeline,
        recovery_rule,
        null_trials=3,
        signal_plan=signal_plan,
        null_seed=1201,
        signal_seed=1202,
        evidence_threshold=1.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
        plan_metadata={"orbital_family": "caller-declared-test-family"},
    )

    assert result.complete
    assert len(calls) == 3 + signal_plan.trial_count
    assert len(result.completeness.cells) == signal_plan.cell_count
    assert len({record.trial.trial_id for record in result.completeness.records}) == 16
    assert result.completeness.cell_at(period=5.0, amplitude=1.0, phase=0.0).completeness == 1.0
    assert result.completeness.cell_at(period=7.0, amplitude=2.0, phase=0.5).completeness == 0.0
    with pytest.raises(ValueError, match="was not evaluated"):
        result.completeness.cell_at(period=6.0, amplitude=1.0, phase=0.0)
    with pytest.raises(ValueError, match="every declared signal axis"):
        result.completeness.cell_at(period=5.0, amplitude=1.0)
    assert result.false_alarm_probability_at_threshold() == pytest.approx(0.25)


def test_multi_axis_failures_remain_in_the_planned_cell_denominator() -> None:
    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        if trial.kind == "signal" and trial.replicate_index == 1:
            raise RuntimeError("declared grid failure")
        return PipelineOutcome(trial.trial_id, 2.0)

    result = run_adaptive_pipeline_grid_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=2,
        signal_plan=SignalTrialPlan(
            axes=(SignalAxis("period", (4.0,)), SignalAxis("amplitude", (1.0,))),
            replicates_per_cell=3,
        ),
        null_seed=1301,
        signal_seed=1302,
        evidence_threshold=1.0,
        confidence_level=0.90,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    cell = result.completeness.cells[0]

    assert not result.complete
    assert cell.planned_trials == 3
    assert cell.recovered_trials == 2
    assert cell.failed_trials == 1
    assert cell.completeness == pytest.approx(2.0 / 3.0)
    assert len(result.completeness.failures) == 1


def test_multi_axis_stale_outcomes_fail_closed_and_plan_metadata_is_detached() -> None:
    metadata = {"association": {"tolerance": 0.1}}
    cached: PipelineOutcome | None = None

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        nonlocal cached
        if cached is None:
            cached = PipelineOutcome(trial.trial_id, 1.0)
        return cached

    kwargs = {
        "null_trials": 1,
        "signal_plan": SignalTrialPlan(
            axes=(SignalAxis("period", (5.0,)),),
            replicates_per_cell=1,
        ),
        "null_seed": 1401,
        "signal_seed": 1402,
        "evidence_threshold": 0.5,
        "confidence_level": 0.95,
        "interval_method": "wilson",
        "pipeline_identity": SYNTHETIC_PIPELINE_ID,
        "recovery_rule_identity": SYNTHETIC_RECOVERY_ID,
        "plan_metadata": metadata,
    }
    result = run_adaptive_pipeline_grid_calibration(
        pipeline,
        lambda trial, outcome: True,
        **kwargs,
    )
    metadata["association"]["tolerance"] = 99.0

    assert result.null.complete
    assert not result.completeness.complete
    assert result.completeness.failures[0].exception_type == "pipeline_outcome_stale"


def test_pipeline_reports_are_unforgeable_immutable_and_content_identified() -> None:
    result = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 1.0),
        lambda trial, outcome: True,
        null_trials=2,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=1501,
        signal_seed=1502,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )

    with pytest.raises(ValueError, match="WRITEABLE"):
        result.null.statistics.setflags(write=True)
    with pytest.raises(ValueError, match="cover every requested trial"):
        replace(result.null, records=result.null.records[:1])
    with pytest.raises(ValueError, match="SHA-256"):
        run_adaptive_pipeline_calibration(
            lambda trial: PipelineOutcome(trial.trial_id, 1.0),
            lambda trial, outcome: True,
            null_trials=1,
            amplitudes=[1.0],
            phases=[0.0],
            replicates_per_cell=1,
            null_seed=1503,
            signal_seed=1504,
            evidence_threshold=0.5,
            confidence_level=0.95,
            interval_method="wilson",
            pipeline_identity="label-only",
            recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
        )
    with pytest.raises(TypeError, match="real scalar"):
        SignalAxis("period", ("5.0",))


@pytest.mark.parametrize(
    ("amplitudes", "phases"),
    [
        (["1.0"], [0.0]),
        ([1.0], [True]),
    ],
)
def test_fixed_signal_grid_rejects_string_and_boolean_values(
    amplitudes: list[object],
    phases: list[object],
) -> None:
    with pytest.raises(TypeError, match="native or NumPy real scalar"):
        run_adaptive_pipeline_calibration(
            lambda trial: PipelineOutcome(trial.trial_id, 1.0),
            lambda trial, outcome: True,
            null_trials=1,
            amplitudes=amplitudes,
            phases=phases,
            replicates_per_cell=1,
            null_seed=1601,
            signal_seed=1602,
            evidence_threshold=0.5,
            confidence_level=0.95,
            interval_method="wilson",
            pipeline_identity=SYNTHETIC_PIPELINE_ID,
            recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
        )


def test_search_result_freezes_every_array_and_replays_all_retained_evidence() -> None:
    times = np.linspace(0.0, 12.0, 24)
    values = 0.2 + np.sin(2.0 * np.pi * times / 3.0)
    uncertainties = np.linspace(0.1, 0.2, times.size)
    periods = np.linspace(2.0, 5.0, 13)
    result = weighted_sinusoid_search(
        times,
        values,
        uncertainties,
        periods,
        rcond=np.float64(1e-12),
    )

    retained_arrays = (
        result.times,
        result.values,
        result.uncertainties,
        result.periods,
        result.null_design_matrix,
        result.null_fit.design_matrix,
        result.null_fit.observed_values,
        result.null_fit.uncertainties,
        result.null_fit.coefficients,
        result.null_fit.fitted_values,
        result.null_fit.residuals,
        result.periodic_coefficients,
        result.chi2,
        result.delta_chi2,
        result.amplitudes,
        result.ranks,
        result.dof,
    )
    assert all(not array.flags.writeable for array in retained_arrays)
    for array in retained_arrays:
        with pytest.raises(ValueError, match="WRITEABLE"):
            array.setflags(write=True)
    assert len(result.design_identity) == 64
    assert len(result.result_identity) == 64

    forged_values = result.values.copy()
    forged_values[0] += 1.0
    with pytest.raises(ValueError, match="replay"):
        replace(result, values=forged_values)
    with pytest.raises(ValueError, match="chi2 does not replay"):
        replace(result.null_fit, chi2=result.null_fit.chi2 + 1.0)
    with pytest.raises(ValueError, match="residuals does not replay"):
        replace(
            result.null_fit,
            residuals=np.full_like(result.null_fit.residuals, 999.0),
        )
    forged_landscape = result.delta_chi2.copy()
    forged_landscape[result.best_index] += 1.0
    with pytest.raises(ValueError, match="delta_chi2 does not replay"):
        replace(result, delta_chi2=forged_landscape)


def test_global_calibration_replays_a_forged_observed_search_before_accounting() -> None:
    times = np.linspace(0.0, 12.0, 24)
    values = np.sin(2.0 * np.pi * times / 3.0)
    uncertainties = np.full(times.size, 0.2)
    periods = np.linspace(2.0, 5.0, 13)
    calibration = calibrate_global_max_statistic(
        times,
        values,
        uncertainties,
        periods,
        simulations=3,
        seed=1701,
    )
    forged = weighted_sinusoid_search(times, values, uncertainties, periods)
    object.__setattr__(forged, "delta_chi2", forged.delta_chi2 + 1000.0)

    with pytest.raises(ValueError, match="delta_chi2 does not replay"):
        replace(calibration, observed_search=forged)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("times", [False, 1.0, 2.0, 3.0, 4.0, 5.0]),
        ("values", ["0.0", 1.0, 0.0, -1.0, 0.0, 1.0]),
        ("uncertainties", [1.0, 1.0, 1.0, 1.0, 1.0, True]),
        ("periods", [np.float64(2.0), "3.0"]),
    ],
)
def test_core_search_arrays_reject_elementwise_bool_and_string_coercion(
    field: str,
    bad_value: list[object],
) -> None:
    arguments: dict[str, object] = {
        "times": np.arange(6, dtype=np.float64),
        "values": np.sin(np.arange(6, dtype=np.float64)),
        "uncertainties": np.ones(6),
        "periods": np.array([2.0, 3.0]),
    }
    arguments[field] = bad_value

    with pytest.raises(TypeError, match="native or NumPy real scalar"):
        weighted_sinusoid_search(**arguments)


def test_custom_numeric_subclasses_are_not_silently_coerced_at_search_boundaries() -> None:
    class FloatSubclass(float):
        pass

    times = [FloatSubclass(0.0), 1.0, 2.0, 3.0, 4.0, 5.0]
    with pytest.raises(TypeError, match="native or NumPy real scalar"):
        weighted_sinusoid_search(
            times,
            np.sin(np.arange(6, dtype=np.float64)),
            np.ones(6),
            np.array([2.0, 3.0]),
        )
    with pytest.raises(TypeError, match="native or NumPy real scalar"):
        weighted_sinusoid_search(
            np.arange(6, dtype=np.float64),
            np.sin(np.arange(6, dtype=np.float64)),
            np.ones(6),
            np.array([2.0, 3.0]),
            rcond=FloatSubclass(1e-12),
        )


def test_hostile_numpy_scalar_subclasses_are_rejected_before_conversion() -> None:
    class HostileFloat(np.float64):
        def __float__(self) -> float:
            raise AssertionError("hostile NumPy float conversion must not run")

    class HostileInt(np.int64):
        def __int__(self) -> int:
            raise AssertionError("hostile NumPy integer conversion must not run")

    with pytest.raises(TypeError, match="native or NumPy real scalar"):
        weighted_sinusoid_search(
            [HostileFloat(0.0), 1.0, 2.0, 3.0, 4.0, 5.0],
            np.sin(np.arange(6, dtype=np.float64)),
            np.ones(6),
            np.array([2.0, 3.0]),
        )
    with pytest.raises(TypeError, match="real scalar"):
        weighted_sinusoid_search(
            np.arange(6, dtype=np.float64),
            np.sin(np.arange(6, dtype=np.float64)),
            np.ones(6),
            np.array([2.0, 3.0]),
            rcond=HostileFloat(1e-12),
        )
    with pytest.raises(ValueError, match="positive integer"):
        calibrate_global_max_statistic(
            np.arange(6, dtype=np.float64),
            np.sin(np.arange(6, dtype=np.float64)),
            np.ones(6),
            np.array([2.0, 3.0]),
            simulations=HostileInt(2),
            seed=1,
        )


def test_numpy_real_scalars_and_arrays_remain_valid_search_inputs() -> None:
    result = weighted_sinusoid_search(
        np.arange(8, dtype=np.float32),
        np.sin(np.arange(8, dtype=np.float32)),
        np.ones(8, dtype=np.float32),
        np.array([np.float32(2.5), np.float64(3.3)]),
        reference_time=np.float32(0.0),
        rcond=np.float64(1e-12),
    )

    assert result.periods.tolist() == pytest.approx([2.5, 3.3])
    assert result.rcond == pytest.approx(1e-12)


def test_malicious_exception_rendering_cannot_abort_or_leak_pipeline_accounting() -> None:
    secret = "do-not-render-this-free-text"

    class UnrenderableError(RuntimeError):
        def __str__(self) -> str:
            raise AssertionError("exception rendering must never be invoked")

    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        raise UnrenderableError(secret)

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=1801,
        signal_seed=1802,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    failures = (*result.null.failures, *result.completeness.failures)

    assert len(failures) == 2
    assert all(failure.exception_type == "pipeline_callback_exception" for failure in failures)
    assert all(failure.message.startswith("diagnostic_sha256:") for failure in failures)
    assert all(secret not in failure.message for failure in failures)


def test_malicious_exception_rendering_is_safe_in_null_and_recovery_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-render-this-null-or-recovery-secret"

    class UnrenderableError(RuntimeError):
        def __str__(self) -> str:
            raise AssertionError("exception rendering must never be invoked")

    times = np.linspace(0.0, 12.0, 24)
    values = np.sin(2.0 * np.pi * times / 3.0)
    uncertainties = np.full(times.size, 0.2)
    periods = np.linspace(2.0, 5.0, 13)
    original = period_search.weighted_sinusoid_search
    calls = 0

    def fail_simulations(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise UnrenderableError(secret)
        return original(*args, **kwargs)

    monkeypatch.setattr(period_search, "weighted_sinusoid_search", fail_simulations)
    null = calibrate_global_max_statistic(
        times,
        values,
        uncertainties,
        periods,
        simulations=2,
        seed=1803,
    )
    assert len(null.failures) == 2
    assert all(
        failure.exception_type == "conditional_null_trial_failure" for failure in null.failures
    )
    assert all(secret not in failure.message for failure in null.failures)

    def recovery_rule(trial: PipelineTrial, outcome: PipelineOutcome) -> bool:
        raise UnrenderableError(secret)

    recovery = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 1.0),
        recovery_rule,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=1804,
        signal_seed=1805,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    failure = recovery.completeness.failures[0]
    assert failure.exception_type == "recovery_rule_exception"
    assert failure.message.startswith("diagnostic_sha256:")
    assert secret not in failure.message


def test_fixed_signal_grid_retains_native_and_numpy_real_arrays() -> None:
    result = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 1.0),
        lambda trial, outcome: True,
        null_trials=1,
        amplitudes=np.array([0.0, 1.0], dtype=np.float32),
        phases=np.array([0], dtype=np.int64),
        replicates_per_cell=1,
        null_seed=1603,
        signal_seed=1604,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )

    assert result.complete
    assert result.completeness.amplitudes.tolist() == [0.0, 1.0]
    assert result.completeness.phases.tolist() == [0.0]


def test_failed_signal_record_cannot_be_relabelled_recovered() -> None:
    def pipeline(trial: PipelineTrial) -> PipelineOutcome:
        if trial.kind == "signal":
            raise RuntimeError("declared signal failure")
        return PipelineOutcome(trial.trial_id, 0.0)

    result = run_adaptive_pipeline_calibration(
        pipeline,
        lambda trial, outcome: True,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=1605,
        signal_seed=1606,
        evidence_threshold=0.5,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    failed = result.completeness.records[0]

    assert failed.failure is not None
    with pytest.raises(ValueError, match="failed signal records must be unrecovered"):
        replace(failed, recovered=True)


def test_fixed_and_multi_axis_reports_reject_below_threshold_recovery() -> None:
    fixed = run_adaptive_pipeline_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 0.0),
        lambda trial, outcome: True,
        null_trials=1,
        amplitudes=[1.0],
        phases=[0.0],
        replicates_per_cell=1,
        null_seed=1607,
        signal_seed=1608,
        evidence_threshold=1.0,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    fixed_record = replace(fixed.completeness.records[0], recovered=True)
    fixed_point = replace(
        fixed.completeness.points[0],
        recovered_trials=1,
        completeness=1.0,
        interval=wilson_interval(1, 1, confidence_level=0.95),
        records=(fixed_record,),
    )

    with pytest.raises(ValueError, match="declared evidence threshold"):
        replace(
            fixed.completeness,
            records=(fixed_record,),
            points=(fixed_point,),
        )

    multi = run_adaptive_pipeline_grid_calibration(
        lambda trial: PipelineOutcome(trial.trial_id, 0.0),
        lambda trial, outcome: True,
        null_trials=1,
        signal_plan=SignalTrialPlan(
            axes=(SignalAxis("amplitude", (1.0,)),),
            replicates_per_cell=1,
        ),
        null_seed=1609,
        signal_seed=1610,
        evidence_threshold=1.0,
        confidence_level=0.95,
        interval_method="wilson",
        pipeline_identity=SYNTHETIC_PIPELINE_ID,
        recovery_rule_identity=SYNTHETIC_RECOVERY_ID,
    )
    multi_record = replace(multi.completeness.records[0], recovered=True)
    multi_cell = replace(
        multi.completeness.cells[0],
        recovered_trials=1,
        completeness=1.0,
        interval=wilson_interval(1, 1, confidence_level=0.95),
        records=(multi_record,),
    )

    with pytest.raises(ValueError, match="declared evidence threshold"):
        replace(
            multi.completeness,
            records=(multi_record,),
            cells=(multi_cell,),
        )
