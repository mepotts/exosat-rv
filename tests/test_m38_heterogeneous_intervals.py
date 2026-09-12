"""Wholly synthetic checks; no observational fixtures are read."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from scripts import m38_heterogeneous_intervals as study


@pytest.fixture
def plan():
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/evidence/m38-heterogeneous-intervals-plan-2026-09-12.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    value["trials_per_case"] = 2
    value["bootstrap_repetitions"] = 9
    return value


@pytest.mark.parametrize("case_index", [0, 1, 2])
def test_covariance_projection_matches_full_matrix(plan, case_index):
    case = plan["cases"][case_index]
    block, x, _, tau, omega, sigma, coefficient, variance = study.geometry(plan, case)
    flatblock = np.repeat(block, x.shape[1])
    shared = flatblock[:, None] == flatblock[None, :]
    a = (tau[:, None] * x).ravel()
    b = np.broadcast_to(omega[:, None], x.shape).ravel()
    d = np.broadcast_to(sigma[:, None] ** 2 / plan["order_count"], x.shape).ravel()
    covariance = shared * (np.outer(a, a) + np.outer(b, b)) + np.diag(d)
    c = coefficient.ravel()
    assert variance == pytest.approx(c @ covariance @ c, rel=1e-12)
    assert np.sum(coefficient) == pytest.approx(0, abs=1e-15)
    assert np.sum(coefficient * x) == pytest.approx(1, abs=1e-12)


@pytest.mark.parametrize("case_index", [0, 1, 2])
def test_production_fit_and_replay(plan, case_index):
    case = plan["cases"][case_index]
    a = study.run_trial(plan, case, 0)
    b = study.run_trial(plan, case, 0)
    assert a == b
    assert a["production_slope"] == pytest.approx(a["projected_slope"], rel=1e-12)
    assert a["data_seed"] != a["bootstrap_seed"]
    assert all(e["complete"] for e in a["intervals"].values())
    assert a["failed_bootstrap_repetitions"] == a["unrun_bootstrap_repetitions"] == 0


def test_equal_blocks_share_center_but_unequal_do_not(plan):
    equal = study.run_trial(plan, plan["cases"][0], 0)
    unequal = study.run_trial(plan, plan["cases"][1], 0)
    assert equal["projected_slope"] == pytest.approx(equal["block_mean_slope"], abs=1e-12)
    assert abs(unequal["projected_slope"] - unequal["block_mean_slope"]) > 1e-4


def test_asymmetric_heterogeneous_design_retains_offset_coupling(plan):
    block, _, _, _, omega, _, coefficient, _ = study.geometry(plan, plan["cases"][1])
    loads = [np.sum(coefficient[block == g] * omega[block == g, None]) for g in range(6)]
    assert max(abs(v) for v in loads) > 1e-4


def test_changing_truth_translates_all_centers_and_intervals(plan):
    case = plan["cases"][1]
    shifted = copy.deepcopy(plan)
    shifted["true_slope"] += 0.7
    # Fix the noise seed to test translation, not content-derived stream changes.
    first = study.generate(plan, case, 42)
    second = study.generate(shifted, case, 42)
    for a, b, injection in zip(first[2], second[2], first[1], strict=True):
        assert np.allclose(b.rv - a.rv, 0.7 * injection.velocities[:, None])


@pytest.mark.parametrize(
    "key,value",
    [
        ("bootstrap_repetitions", 1),
        ("trials_per_case", True),
        ("slope_sd", float("nan")),
        ("confidence_level", 1),
    ],
)
def test_bad_plan_rejected(plan, key, value):
    plan[key] = value
    with pytest.raises(ValueError):
        study.validate_plan(plan)


@pytest.mark.parametrize(
    "key,value",
    [
        ("block_sizes", [0, 2]),
        ("block_scales", [1]),
        ("velocities_m_s", [2, 2]),
        ("noise", "cauchy"),
    ],
)
def test_bad_case_rejected(plan, key, value):
    plan["cases"][0][key] = value
    with pytest.raises(ValueError):
        study.validate_plan(plan)


def test_complete_ledger_checks_and_tamper_rejection(plan):
    result = study.run_study(plan)
    study.validate_result(result, replay=True)
    assert "Coverage" in study.render_table(result)
    bad = copy.deepcopy(result)
    bad["cases"][0]["trials"][0]["intervals"][study.METHODS[0]]["covered"] = "true"
    with pytest.raises(ValueError):
        study.validate_result(bad)
    bad = copy.deepcopy(result)
    bad["cases"][0]["trials"].pop()
    with pytest.raises(ValueError, match="roster"):
        study.validate_result(bad)
    bad = copy.deepcopy(result)
    bad["cases"][0]["trials"][0]["data_seed"] += 1
    with pytest.raises(ValueError):
        study.validate_result(bad)


def test_source_change_rejected(plan, monkeypatch):
    monkeypatch.setattr(study, "source_hashes", lambda: {"changed": "source"})
    with pytest.raises(RuntimeError, match="source changed"):
        study.run_study(plan)


def test_absent_interval_counts_in_all_planned_denominator(plan):
    row = study.run_trial(plan, plan["cases"][0], 0)
    row["intervals"][study.METHODS[2]] = study.interval(None, None, plan["true_slope"])
    summary = study.summarize(plan, [row, row])[study.METHODS[2]]
    assert summary["complete"] == summary["covered"] == 0
    assert summary["planned"] == 2
    assert summary["mean_complete_width"] is None


def test_partial_or_reversed_interval_rejected():
    with pytest.raises(ValueError):
        study.interval(None, 2.0, 1.0)
    with pytest.raises(ValueError):
        study.interval(2.0, 0.0, 1.0)


def test_retained_plan_identity_and_generated_document_table():
    root = Path(__file__).resolve().parents[1]
    evidence = root / "docs/evidence"
    declared = json.loads(
        (evidence / "m38-heterogeneous-intervals-plan-2026-09-12.json").read_text(encoding="utf-8")
    )
    result = json.loads(
        (evidence / "m38-heterogeneous-intervals-result-2026-09-12.json").read_text(
            encoding="utf-8"
        )
    )
    study.assert_close(result["plan"], declared)
    assert result["plan_sha256"] == study.provenance.canonical_sha256(declared)
    document = (root / "docs/milestones/M38-HETEROGENEOUS-INTERVALS.md").read_text(encoding="utf-8")
    begin = "<!-- BEGIN GENERATED M38 HETEROGENEOUS INTERVALS -->"
    end = "<!-- END GENERATED M38 HETEROGENEOUS INTERVALS -->"
    assert document.count(begin) == document.count(end) == 1
    actual = document.split(begin)[1].split(end)[0].strip()
    assert actual == study.render_table(result)
