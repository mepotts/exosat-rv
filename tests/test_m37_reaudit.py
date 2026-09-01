"""Regression tests for the central M37 all-epochs/screened distinction."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "m37_reaudit.py"
SPEC = importlib.util.spec_from_file_location("m37_reaudit", SCRIPT)
assert SPEC and SPEC.loader
M37 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M37
SPEC.loader.exec_module(M37)


def test_adopted_series_has_one_internally_identified_bad_night(monkeypatch):
    # The downstream loader must not consult the published RV table merely to reduce the
    # bundled series. A future accidental call will make this test fail loudly.
    import vs_published

    monkeypatch.setattr(
        vs_published,
        "published",
        lambda: (_ for _ in ()).throw(AssertionError("published RV loader was called")),
    )
    times, _, combines, _, bad, orders, _ = M37.adopted_series(M37.DEFAULT_SERIES)

    assert len(times) == 18
    assert set(combines) == {"mean", "median", "clip"}
    assert len(orders) == 11
    assert np.flatnonzero(bad).tolist() == [12]
    assert times[bad][0] == pytest.approx(2460604.817957461)


def test_committed_reaudit_supports_only_the_conditional_detection_claim():
    result = json.loads((ROOT / "data/m37-cd35-reaudit.json").read_text(encoding="utf-8"))
    assert result["method"]["published_rvs_used"] is False
    assert result["method"]["permutations"] == 5000
    assert result["internal_screen"]["n_all"] == 18
    assert result["internal_screen"]["n_dropped"] == 1

    for combination in ("mean", "median", "clip"):
        all_berv = next(
            row for row in result["variants"][combination]["all_epochs"] if row["berv"]
        )
        screened_berv = next(
            row
            for row in result["variants"][combination]["internal_screen"]
            if row["berv"]
        )
        assert all_berv["p_max"] > 0.05
        assert screened_berv["p_max"] < 0.01
        assert abs(np.log(screened_berv["P_max"] / 171.45)) < 0.06


def test_reaudit_series_hash_matches_the_evidence_manifest():
    result = json.loads((ROOT / "data/m37-cd35-reaudit.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "data/repro/manifest.json").read_text(encoding="utf-8"))
    source = next(
        record
        for record in manifest["included_files"]
        if record["path"] == "viper/results/M14_NODT2.rvo.dat"
    )
    assert result["source"]["sha256"] == source["sha256"]

    implementation = result["implementation"]["files"]
    assert set(implementation) == {
        str(path.relative_to(ROOT)).replace("\\", "/") for path in M37.IMPLEMENTATION_FILES
    }
    for relative_path, expected_hash in implementation.items():
        assert M37.sha256_file(ROOT / relative_path) == expected_hash
