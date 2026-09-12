"""Retained, generated-only bridge evidence and fail-closed report checks."""

import json

import pytest
from scripts import m38_render_viper_bridge as report


def test_retained_report_matches_source_bound_evidence():
    result = json.loads(report.EVIDENCE.read_text())
    generated = report.render(result)
    document = report.REPORT.read_text(encoding="utf-8")
    assert document.split(report.START)[1].split(report.END)[0] == "\n\n" + generated + "\n\n"


@pytest.mark.parametrize("corruption", ["missing_case", "template_leak", "source_hash"])
def test_report_rejects_corrupted_evidence(corruption):
    result = json.loads(report.EVIDENCE.read_text())
    if corruption == "missing_case":
        del result["cases"]["negative"]
    elif corruption == "source_hash":
        result["bridge_sha256"] = "0" * 64
    else:
        result["cases"]["heldout_perturb"]["history"][0]["native_arrays_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        report.render(result)
