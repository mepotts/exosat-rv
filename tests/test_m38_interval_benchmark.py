"""Target-free checks of the restricted Gaussian benchmark and paired accounting."""

from copy import deepcopy

import numpy as np
import pytest
from scipy.stats import t
from scripts import m38_interval_benchmark as benchmark


@pytest.fixture
def plan():
    return {
        "schema": "m38-interval-benchmark-plan-v1",
        "master_seed": 42,
        "trials_per_case": 3,
        "bootstrap_repetitions": [5, 11],
        "confidence_level": 0.95,
        "monte_carlo_confidence_level": 0.95,
        "true_slope": 1.0,
        "injected_velocities_m_s": [-1800.0, -600.0, 600.0, 1800.0],
        "order_count": 3,
        "night_slope_sd": 0.25,
        "night_offset_sd_m_s": 80.0,
        "order_noise_sd_m_s": 40.0,
        "minimum_independent_clusters": 2,
        "cases": [
            {
                "id": "independent",
                "nights": 8,
                "noise": "independent",
                "bootstrap_labels": ["night"],
            },
            {
                "id": "season",
                "nights": 8,
                "noise": "season",
                "bootstrap_labels": ["night", "season"],
            },
        ],
    }


@pytest.mark.parametrize("index", [0, 1])
def test_oracle_matches_full_covariance_projection(plan, index):
    case = plan["cases"][index]
    n = case["nights"]
    x = np.tile(plan["injected_velocities_m_s"], n)
    nights = np.repeat(np.arange(n), len(plan["injected_velocities_m_s"]))
    groups = nights // 4 if case["noise"] == "season" else nights
    same = groups[:, None] == groups[None, :]
    tau, omega, sigma = 0.25, 80.0, 40.0
    covariance = same * (tau**2 * np.outer(x, x) + omega**2)
    covariance += np.eye(len(x)) * sigma**2 / plan["order_count"]
    w = 1 / (tau**2 * x * x + omega**2 + sigma**2)
    coefficient = w * x / np.sum(w * x * x)
    exact = float(coefficient @ covariance @ coefficient)
    assert benchmark.oracle_variance(plan, case) == pytest.approx(exact, rel=1e-13)


def test_true_blocks_determine_oracle_not_bootstrap_label(plan):
    independent, season = plan["cases"]
    difference = benchmark.oracle_variance(plan, season) - benchmark.oracle_variance(
        plan, independent
    )
    assert difference == pytest.approx(0.25**2 * (1 / 2 - 1 / 8))
    renamed = dict(season, bootstrap_labels=["night"])
    assert benchmark.oracle_variance(plan, renamed) == benchmark.oracle_variance(plan, season)


def test_trial_pairs_draws_and_uses_true_block_t(plan):
    row = benchmark.run_trial(plan, plan["cases"][1], 0)
    assert row["prefix_pairing_verified"]
    values = row["independent_block_slopes"]
    assert len(values) == 2
    assert row["slope"] == pytest.approx(np.mean(values))
    half = t.ppf(0.975, 1) * np.std(values, ddof=1) / np.sqrt(2)
    interval = row["intervals"]["independent-block-t"]
    assert interval["upper"] - row["slope"] == pytest.approx(half)
    assert len(row["intervals"]) == 6
    assert len(row["bootstrap_seeds"]) == 2


def test_deterministic_complete_ledger(plan):
    left = benchmark.run_study(plan)
    right = benchmark.run_study(plan)
    assert left == right
    assert sum(len(c["trials"]) for c in left["cases"]) == 6
    for case in left["cases"]:
        for comparison in case["summary"]["paired_comparisons"]:
            counts = comparison["coverage_pairs"]
            assert sum(counts.values()) == 3
            assert comparison["second_minus_first"] == (counts["01"] - counts["10"]) / 3


def test_parallel_execution_preserves_scientific_result(plan):
    serial = benchmark.run_study(plan)
    parallel = benchmark.run_study(plan, workers=2)
    assert parallel["cases"] == serial["cases"]
    assert parallel["source_sha256"] == serial["source_sha256"]


def test_seed_domains_and_generator_data_reuse(plan):
    case = plan["cases"][1]
    row = benchmark.run_trial(plan, case, 0)
    all_seeds = [row["data_seed"], *row["bootstrap_seeds"].values()]
    assert len(set(all_seeds)) == 3
    ref, injections, responses = benchmark.pilot.generate_response_trial(
        benchmark.generator_plan(plan), benchmark.generator_case(case), 1.0, row["data_seed"]
    )
    slopes = benchmark.block_slopes(ref, injections, responses, 4)
    np.testing.assert_array_equal(slopes, row["independent_block_slopes"])


def test_truth_translation_preserves_interval_width_for_same_seed(plan):
    case = plan["cases"][0]
    base = benchmark.generator_plan(plan)
    low = benchmark.pilot.generate_response_trial(base, benchmark.generator_case(case), 0.7, 123)
    high = benchmark.pilot.generate_response_trial(base, benchmark.generator_case(case), 1.0, 123)
    a, b = benchmark.block_slopes(*low, 1), benchmark.block_slopes(*high, 1)
    np.testing.assert_allclose(b - a, 0.3, atol=1e-12)
    assert np.std(a, ddof=1) == pytest.approx(np.std(b, ddof=1))


@pytest.mark.parametrize("repetitions", [[11, 5], [5, 5], [True, 11], [5]])
def test_invalid_repetition_grid(plan, repetitions):
    plan["bootstrap_repetitions"] = repetitions
    with pytest.raises(ValueError):
        benchmark.validate_plan(plan)


def test_reject_non_exact_or_incomplete_design(plan):
    changed = deepcopy(plan)
    changed["cases"][0]["noise"] = "heterogeneous"
    with pytest.raises(ValueError, match="homogeneous"):
        benchmark.validate_plan(changed)
    changed = deepcopy(plan)
    changed["cases"][1]["bootstrap_labels"] = ["season"]
    with pytest.raises(ValueError, match="roster"):
        benchmark.validate_plan(changed)
    changed = deepcopy(plan)
    changed["cases"][1]["nights"] = 9
    with pytest.raises(ValueError, match="four-night"):
        benchmark.validate_plan(changed)


def test_source_changes_stop_study(plan, monkeypatch):
    monkeypatch.setattr(benchmark, "source_hashes", lambda: {"benchmark": "changed"})
    with pytest.raises(RuntimeError, match="source changed"):
        benchmark.run_study(plan)


def test_incomplete_interval_stays_in_denominator(plan):
    case = plan["cases"][0]
    rows = [benchmark.run_trial(plan, case, i) for i in range(3)]
    rows[0]["intervals"]["percentile-night-5"] = benchmark.interval_record(None, None, 1, unrun=5)
    summary = benchmark.summarize(plan, case, rows)["methods"]["percentile-night-5"]
    assert summary["complete"] == 2
    assert summary["coverage_all_planned"]["total"] == 3


def test_renderer_checks_all_methods_and_interval_semantics(plan):
    from scripts import m38_render_interval_benchmark as renderer

    result = benchmark.run_study(plan)
    assert "Retained 6 independent noise trials" in renderer.render(result)
    broken = deepcopy(result)
    row = broken["cases"][0]["trials"][0]
    row["intervals"]["percentile-night-5"]["covered"] = not row["intervals"]["percentile-night-5"][
        "covered"
    ]
    broken["cases"][0]["summary"] = benchmark.summarize(
        plan, plan["cases"][0], broken["cases"][0]["trials"]
    )
    with pytest.raises(ValueError, match="event or width"):
        renderer.render(broken)
    broken = deepcopy(result)
    broken["cases"][0]["trials"][0]["intervals"].pop("oracle-normal")
    with pytest.raises(ValueError, match="method roster"):
        renderer.render(broken)


def test_renderer_allows_roundoff_not_changed_counts(plan):
    from scripts import m38_render_interval_benchmark as renderer

    result = benchmark.run_study(plan)
    summary = result["cases"][0]["summary"]
    summary["methods"]["oracle-normal"]["coverage_all_planned"]["upper"] -= 4e-13
    renderer.render(result)
    summary["methods"]["oracle-normal"]["complete"] -= 1
    with pytest.raises(ValueError, match="summary does not match"):
        renderer.render(result)


def test_renderer_rejects_inconsistent_incomplete_records():
    from scripts import m38_render_interval_benchmark as renderer

    malformed = benchmark.interval_record(None, None, 1.0, unrun=5)
    malformed["lower"] = 0.5
    with pytest.raises(ValueError, match="incomplete interval"):
        renderer.validate_interval(malformed, 1.0, 5)
    malformed = benchmark.interval_record(0.5, 1.5, 1.0, failed=1)
    with pytest.raises(ValueError, match="complete interval carries failures"):
        renderer.validate_interval(malformed, 1.0, 5)


def test_renderer_rejects_changed_oracle_even_with_recounted_summary(plan):
    from scripts import m38_render_interval_benchmark as renderer

    result = benchmark.run_study(plan)
    cell = result["cases"][0]
    row = cell["trials"][0]
    row["intervals"]["oracle-normal"] = benchmark.interval_record(-20.0, 20.0, 1.0)
    cell["summary"] = benchmark.summarize(plan, cell["case"], cell["trials"])
    with pytest.raises(ValueError, match="exact benchmark interval"):
        renderer.render(result)


def test_renderer_uses_declared_confidence(plan):
    from scripts import m38_render_interval_benchmark as renderer

    plan["monte_carlo_confidence_level"] = 0.9
    assert "pointwise 90% exact" in renderer.render(benchmark.run_study(plan))
