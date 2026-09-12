"""Independent ledger checks, not independent scientific protocol approval."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import beta, norm, t

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"


@pytest.fixture(scope="module")
def retained():
    return json.loads((EVIDENCE / "m38-heterogeneous-intervals-result-2026-09-12.json").read_text())


def test_sources_and_declared_plan_are_content_bound(retained):
    plan = json.loads((EVIDENCE / "m38-heterogeneous-intervals-plan-2026-09-12.json").read_text())
    assert retained["plan"] == plan
    paths = {
        "driver": "scripts/m38_heterogeneous_intervals.py",
        "selection": "src/exosat_rv/m38/selection.py",
        "provenance": "src/exosat_rv/m38/provenance.py",
    }
    assert set(retained["source_sha256"]) == set(paths)
    for key, relative in paths.items():
        assert (
            hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            == retained["source_sha256"][key]
        )


def test_every_retained_interval_and_summary_independently(retained):
    plan = retained["plan"]
    truth = plan["true_slope"]
    probability = (1 + plan["confidence_level"]) / 2
    all_seeds = []
    total = 0
    for cell in retained["cases"]:
        rows = cell["trials"]
        assert [row["trial"] for row in rows] == list(range(plan["trials_per_case"]))
        for row in rows:
            all_seeds.extend((row["data_seed"], row["bootstrap_seed"]))
            assert row["bootstrap_failure_reason"] is None
            assert row["failed_bootstrap_repetitions"] == 0
            assert row["unrun_bootstrap_repetitions"] == 0
            assert row["production_slope"] == pytest.approx(row["projected_slope"], abs=1e-12)
            for name, entry in row["intervals"].items():
                total += 1
                assert entry["complete"] is True
                assert entry["covered"] == (entry["lower"] <= truth <= entry["upper"])
                assert entry["width"] == pytest.approx(entry["upper"] - entry["lower"])
                if name == "known-covariance-normal":
                    center = row["projected_slope"]
                    half = norm.ppf(probability) * np.sqrt(row["oracle_variance"])
                elif name == "unweighted-block-t":
                    slopes = np.asarray(row["block_slopes"])
                    center = slopes.mean()
                    half = (
                        t.ppf(probability, len(slopes) - 1)
                        * slopes.std(ddof=1)
                        / np.sqrt(len(slopes))
                    )
                else:
                    continue
                assert entry["lower"] == pytest.approx(center - half, abs=1e-12)
                assert entry["upper"] == pytest.approx(center + half, abs=1e-12)
        for method in rows[0]["intervals"]:
            entries = [row["intervals"][method] for row in rows]
            covered = sum(e["lower"] <= truth <= e["upper"] for e in entries)
            summary = cell["summary"][method]
            assert summary["covered"] == covered
            assert summary["complete"] == summary["planned"] == len(rows)
            assert summary["coverage"] == covered / len(rows)
            # Direct beta-quantile Clopper-Pearson formula, independently of driver's binomtest.
            alpha = 1 - plan["monte_carlo_confidence_level"]
            lo = beta.ppf(alpha / 2, covered, len(rows) - covered + 1) if covered else 0
            hi = (
                beta.ppf(1 - alpha / 2, covered + 1, len(rows) - covered)
                if covered < len(rows)
                else 1
            )
            assert summary["mc_lower"] == pytest.approx(lo, abs=1e-10)
            assert summary["mc_upper"] == pytest.approx(hi, abs=1e-10)
            assert summary["mean_complete_width"] == pytest.approx(
                np.mean([e["upper"] - e["lower"] for e in entries])
            )
    assert total == 4500
    assert len(all_seeds) == len(set(all_seeds)) == 3000


@pytest.mark.parametrize("case_index", [0, 1, 2])
def test_independent_full_covariance_and_wls_projection(retained, case_index):
    plan = retained["plan"]
    cell = retained["cases"][case_index]
    case = cell["case"]
    blocks = np.repeat(np.arange(len(case["block_sizes"])), case["block_sizes"])
    bank = np.asarray(case["velocities_m_s"])
    x = np.tile(bank, len(blocks))
    block = np.repeat(blocks, len(bank))
    scale = np.asarray(case["block_scales"])[block]
    slope_loading = plan["slope_sd"] * scale * x
    offset = plan["offset_sd_m_s"]
    noise_variance = plan["order_noise_sd_m_s"] ** 2 * scale
    design = np.column_stack((np.ones(len(x)), x))
    weight = 1 / (slope_loading**2 + offset**2 + noise_variance)
    whitened = np.sqrt(weight)[:, None] * design
    coefficient = np.linalg.pinv(whitened)[1] * np.sqrt(weight)
    shared = block[:, None] == block[None, :]
    covariance = shared * (np.outer(slope_loading, slope_loading) + offset**2)
    covariance += np.diag(noise_variance / plan["order_count"])
    expected = coefficient @ covariance @ coefficient
    assert all(row["oracle_variance"] == pytest.approx(expected) for row in cell["trials"])
    assert coefficient.sum() == pytest.approx(0, abs=1e-12)
    assert coefficient @ x == pytest.approx(1, abs=1e-12)
