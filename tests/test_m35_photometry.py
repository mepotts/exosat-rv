"""Regression tests for the corrected, night-aware M35 photometric analysis."""

import json
from pathlib import Path

import numpy as np
import pytest
import scripts.m35_asassn_photometry as m35
from scripts.m35_asassn_photometry import (
    P_RV_DAYS,
    apply_nightly_binning,
    fixed_period_power,
    make_binning_plan,
    phase_completeness,
    plus_one_pvalue,
)


def test_offline_fetch_fails_closed_when_cache_is_missing(tmp_path, monkeypatch):
    missing = tmp_path / "missing-asassn.csv"
    monkeypatch.setattr(m35, "CACHE", str(missing))
    with pytest.raises(FileNotFoundError, match="pass --refetch"):
        m35.fetch(refetch=False)


def test_plus_one_permutation_p_value_has_a_nonzero_floor():
    assert plus_one_pvalue(0, 500) == pytest.approx(1.0 / 501.0)
    assert plus_one_pvalue(0, 2_000) == pytest.approx(1.0 / 2_001.0)
    assert plus_one_pvalue(2_000, 2_000) == 1.0


def test_camera_correction_and_binning_leave_one_point_per_night():
    # Each night has repeated visits from two cameras. Camera B is offset by 10 mag,
    # while the physical signal moves by 2 mag between nights.
    times = np.array([100.60, 100.61, 100.70, 100.71, 101.60, 101.61, 101.70, 101.71])
    cameras = np.array(["A", "A", "B", "B", "A", "A", "B", "B"])
    values = np.array([10.0, 10.2, 20.0, 20.2, 12.0, 12.2, 22.0, 22.2])

    plan = make_binning_plan(times, cameras)
    binned = apply_nightly_binning(values, plan)

    assert plan.unique_nights.tolist() == [100, 101]
    assert plan.binned_times.tolist() == pytest.approx([100.655, 101.655])
    assert binned.tolist() == pytest.approx([-1.0, 1.0])


def test_deterministic_phase_grid_recovers_a_strong_injected_semiamplitude():
    # Irregular nights and alternating cameras exercise the same preprocessing as the
    # cached analysis. A pure injected sinusoid should clear a deliberately modest null
    # threshold at every deterministic phase.
    nights = np.arange(160, dtype=float)
    base_times = 2_450_000.6 + 2.37 * nights + 0.11 * np.sin(nights)
    times = np.repeat(base_times, 2) + np.tile([0.0, 0.015], len(base_times))
    cameras = np.tile(["A", "B"], len(base_times))
    values = np.where(cameras == "A", 11.0, 11.4)
    plan = make_binning_plan(times, cameras)

    curve = phase_completeness(
        times,
        values,
        plan,
        target_null_powers=np.full(199, 0.20),
        semiamplitudes_mmag=(20,),
        n_phases=180,
        convergence_grid_sizes=(45, 90, 180),
        alpha=0.01,
    )

    assert curve[0]["semiamplitude_mmag"] == 20
    assert curve[0]["recovered_phases"] == 180
    assert curve[0]["phase_fraction"] == 1.0
    assert curve[0]["phase_fraction_by_grid"] == {
        "45": 1.0,
        "90": 1.0,
        "180": 1.0,
    }
    assert fixed_period_power(
        plan.binned_times,
        apply_nightly_binning(
            values + 0.020 * np.sin(2 * np.pi * times / P_RV_DAYS), plan
        ),
        P_RV_DAYS,
    ) > 0.95


def test_phase_convergence_grids_must_be_nested_divisors():
    times = np.arange(12, dtype=float)
    cameras = np.full(12, "A")
    plan = make_binning_plan(times, cameras)
    with pytest.raises(ValueError, match="increasing divisors"):
        phase_completeness(
            times,
            np.zeros(12),
            plan,
            target_null_powers=np.linspace(0.0, 1.0, 99),
            semiamplitudes_mmag=(1,),
            n_phases=100,
            convergence_grid_sizes=(30, 100),
        )


def test_committed_m35_phase_sensitivity_is_grid_resolved_not_binomial():
    root = Path(__file__).resolve().parents[1]
    artifact = json.loads((root / "data/m35-photometry-v2.json").read_text("utf-8"))
    assert artifact["input"]["rows"] == 6658
    assert artifact["input"]["sha256"] == (
        "8a7174d15449c9cef9c74122178f4721d9b0fae978032c4d0ded4d76121b5cf8"
    )
    assert artifact["input"]["sha256"] == m35._sha256(
        str(root / artifact["input"]["path"])
    )
    assert artifact["implementation"]["sha256"] == m35._sha256(
        str(root / artifact["implementation"]["path"])
    )
    assert artifact["method"]["deterministic_phase_grid_sizes"] == [720, 1440, 2880]
    assert "not a binomial sample" in artifact["method"]["phase_fraction_inference"]
    assert artifact["target_source_relationship"]["sampling_keys_identical"] is True
    assert artifact["target_source_relationship"]["shared_timestamp_filter_camera_rows"] == 2173

    targets = [
        series
        for series in artifact["series"]
        if series["physical_source_role"] == "cd35_2722_host"
    ]
    assert len(targets) == 4
    grid_limits = []
    five_mmag_fractions = []
    for series in targets:
        recovery = series["injection_recovery"]
        limits = set(recovery["k90_mmag_by_phase_grid"].values())
        grid_limit = recovery[
            "first_sampled_K_mmag_with_phase_fraction_ge_0.90_on_all_grids"
        ]
        assert limits == {grid_limit}
        assert recovery["max_abs_successive_grid_fraction_change_over_curve"] <= 1 / 720
        assert series["rv_period_detection_rule"]["max_null_exceedances"] == 19
        grid_limits.append(grid_limit)
        five_mmag_fractions.append(
            next(
                point["phase_fraction"]
                for point in recovery["curve"]
                if point["semiamplitude_mmag"] == 5.0
            )
        )
        assert all("wilson" not in key.lower() for point in recovery["curve"] for key in point)
    assert sorted(grid_limits) == [12.0, 12.0, 13.0, 13.0]
    assert min(five_mmag_fractions) >= 0.43
    assert max(five_mmag_fractions) <= 0.45
