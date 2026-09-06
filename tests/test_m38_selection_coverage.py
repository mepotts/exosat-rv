"""Only synthetic response fixtures; no observational products are loaded."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest
from scripts import m38_selection_coverage as coverage


@pytest.fixture
def plan():
    return {
        "schema": "m38-selection-coverage-pilot-v1",
        "master_seed": 16,
        "trials_per_cell": 2,
        "bootstrap_repetitions": 19,
        "confidence_level": 0.95,
        "monte_carlo_confidence_level": 0.95,
        "equivalence_delta": 0.2,
        "minimum_independent_clusters": 2,
        "true_slopes": [0.8, 1.0],
        "injected_velocities_m_s": [-1500.0, -500.0, 500.0, 1500.0],
        "order_count": 3,
        "night_slope_sd": 0.25,
        "night_offset_sd_m_s": 80.0,
        "order_noise_sd_m_s": 40.0,
        "scenarios": [
            {
                "id": "test",
                "nights": 12,
                "noise": "independent",
                "cluster": "night",
                "attrition": False,
            }
        ],
    }


def test_deterministic_complete_study(plan):
    a = coverage.run_study(plan)
    b = coverage.run_study(plan)
    assert a == b
    assert len(a["cells"]) == 2
    assert all(len(c["trials"]) == 2 for c in a["cells"])
    assert all(r["complete"] for c in a["cells"] for r in c["trials"])
    assert a["plan_sha256"] == coverage.canonical_sha256(plan)


def test_seed_domains_and_plan_binding(plan):
    scenario = plan["scenarios"][0]
    seeds = [
        coverage.trial_seed(plan, scenario, truth, trial, domain)
        for truth in plan["true_slopes"]
        for trial in range(2)
        for domain in ("response-noise", "cluster-bootstrap")
    ]
    assert len(set(seeds)) == len(seeds)
    changed = deepcopy(plan)
    changed["master_seed"] += 1
    assert seeds[0] != coverage.trial_seed(changed, scenario, 0.8, 0, "response-noise")


def test_truth_translation_and_paired_uncertainty(plan):
    scenario = plan["scenarios"][0]
    ref, injections, low = coverage.generate_response_trial(plan, scenario, 0.7, 55)
    _, _, high = coverage.generate_response_trial(plan, scenario, 1.0, 55)
    for injection, lo, hi in zip(injections, low, high, strict=True):
        expected = np.broadcast_to((0.3 * injection.velocities)[:, None], ref.rv.shape)
        np.testing.assert_allclose(hi.rv - lo.rv, expected)
        v = injection.velocities[0]
        marginal_sd = np.sqrt((0.25 * v) ** 2 + 80**2 + 40**2)
        np.testing.assert_allclose(lo.response_uncertainty, marginal_sd)


def test_cluster_labels_do_not_change_synthetic_physics(plan):
    scenario = dict(plan["scenarios"][0], noise="season")
    a = coverage.generate_response_trial(plan, scenario, 1.0, 24)
    b = coverage.generate_response_trial(plan, dict(scenario, cluster="season"), 1.0, 24)
    assert len(set(a[0].cluster_ids)) == 12
    assert len(set(b[0].cluster_ids)) == 3
    for left, right in zip(a[2], b[2], strict=True):
        np.testing.assert_array_equal(left.rv, right.rv)


def test_order_loss_cannot_gain_eligibility(plan):
    scenario = dict(plan["scenarios"][0], attrition=True, nights=48)
    result = coverage.run_trial(plan, scenario, 1.0, 0)
    assert not result["attrition_passed"]
    assert not result["complete"]
    assert not result["interval_gate_passed"]
    assert result["failed_bootstrap_repetitions"] == 0
    assert result["unrun_bootstrap_repetitions"] == plan["bootstrap_repetitions"]


def test_denominators_retain_failed_trials():
    records = [
        {
            "complete": True,
            "covered": True,
            "attrition_passed": True,
            "interval_gate_passed": True,
            "false_equivalence": False,
        },
        {
            "complete": False,
            "covered": False,
            "attrition_passed": False,
            "interval_gate_passed": False,
            "false_equivalence": False,
        },
    ]
    result = coverage.summarize_trials(records, 0.95)
    assert result["covered"]["rate"] == 0.5
    assert result["coverage_given_complete"]["rate"] == 1.0
    assert result["complete"]["total"] == 2
    assert coverage.binomial_summary(0, 0, 0.95)["rate"] is None
    assert coverage.binomial_summary(0, 200, 0.95)["upper"] > 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("trials_per_cell", True),
        ("bootstrap_repetitions", 0),
        ("confidence_level", float("nan")),
        ("minimum_independent_clusters", 1),
        ("true_slopes", [1.0, 1.0]),
        ("injected_velocities_m_s", [-1.0, 2.0]),
    ],
)
def test_reject_invalid_plans(plan, key, value):
    plan[key] = value
    with pytest.raises(ValueError):
        coverage.validate_plan(plan)


def test_no_duplicate_or_incomplete_scenarios(plan):
    plan["scenarios"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        coverage.validate_plan(plan)
    plan["scenarios"] = [dict(plan["scenarios"][0], noise="season", nights=13)]
    with pytest.raises(ValueError, match="four-night"):
        coverage.validate_plan(plan)


def test_source_change_before_execution_rejected(plan, monkeypatch):
    monkeypatch.setattr(coverage, "_source_hashes", lambda: {"driver": "changed"})
    with pytest.raises(RuntimeError, match="source changed after module load"):
        coverage.run_study(plan)


def test_source_change_during_execution_rejected(plan, monkeypatch):
    snapshots = iter([coverage._LOADED_SOURCE_HASHES, {"driver": "changed"}])
    monkeypatch.setattr(coverage, "_source_hashes", lambda: next(snapshots))
    with pytest.raises(RuntimeError, match="source changed during study"):
        coverage.run_study(plan)


def test_false_equivalence_is_not_applicable_inside_margin(plan):
    result = coverage.run_trial(plan, plan["scenarios"][0], 1.0, 0)
    assert result["false_equivalence"] is None
    assert coverage.summarize_trials([result], 0.95)["false_equivalence"]["rate"] is None


def test_generated_table_checks_ledger_and_roster(plan):
    from scripts.m38_render_selection_coverage import validated_table

    result = coverage.run_study(plan)
    assert "All 4 planned response trials" in validated_table(result)
    broken = deepcopy(result)
    broken["cells"][0]["summary"]["covered"]["successes"] += 1
    with pytest.raises(ValueError, match="trial ledger"):
        validated_table(broken)
    broken = deepcopy(result)
    broken["cells"].pop()
    with pytest.raises(ValueError, match="cell roster"):
        validated_table(broken)


def test_renderer_rejects_consistently_recounted_false_flags(plan):
    from scripts.m38_render_selection_coverage import validated_table

    result = coverage.run_study(plan)
    cell = result["cells"][0]
    cell["trials"][0]["covered"] = not cell["trials"][0]["covered"]
    cell["summary"] = coverage.summarize_trials(cell["trials"], 0.95)
    with pytest.raises(ValueError, match="interval semantics"):
        validated_table(result)


def test_renderer_labels_actual_monte_carlo_confidence(plan):
    from scripts.m38_render_selection_coverage import validated_table

    plan["monte_carlo_confidence_level"] = 0.9
    assert "pointwise 90% exact" in validated_table(coverage.run_study(plan))


def test_renderer_tolerates_solver_roundoff_but_not_changed_result(plan):
    from scripts.m38_render_selection_coverage import validated_table

    result = coverage.run_study(plan)
    result["cells"][0]["summary"]["covered"]["upper"] -= 4e-13
    validated_table(result)
    result["cells"][0]["summary"]["covered"]["upper"] -= 1e-4
    with pytest.raises(ValueError, match="trial ledger"):
        validated_table(result)
