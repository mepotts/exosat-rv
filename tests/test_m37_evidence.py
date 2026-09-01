"""Offline integrity tests for the M37 evidence packager."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "m37_package_evidence.py"
SPEC = importlib.util.spec_from_file_location("m37_package_evidence", SCRIPT)
assert SPEC and SPEC.loader
M37 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M37
SPEC.loader.exec_module(M37)

RENDER_SCRIPT = ROOT / "scripts" / "m37_render_results.py"
RENDER_SPEC = importlib.util.spec_from_file_location("m37_render_results", RENDER_SCRIPT)
assert RENDER_SPEC and RENDER_SPEC.loader
M37_RENDER = importlib.util.module_from_spec(RENDER_SPEC)
sys.modules[RENDER_SPEC.name] = M37_RENDER
RENDER_SPEC.loader.exec_module(M37_RENDER)


def test_declared_evidence_destinations_and_hashes_are_unambiguous():
    destinations = [spec.destination for spec in M37.INCLUDED_FILES]
    assert None not in destinations
    assert len(destinations) == len(set(destinations))

    for spec in (*M37.INCLUDED_FILES, *M37.HASH_ONLY_FILES):
        assert spec.size > 0
        assert len(spec.sha256) == 64
        int(spec.sha256, 16)


def test_script_only_science_dependencies_are_declared():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    requirements = project["optional-dependencies"]["science"]
    assert "dynesty>=2.1,<4" in requirements
    assert any(requirement.startswith("matplotlib") for requirement in requirements)


def test_verify_file_fails_closed_on_content_drift(tmp_path):
    path = tmp_path / "result.dat"
    path.write_bytes(b"audited result\n")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    M37.verify_file(path, size=15, sha256=expected)

    path.write_bytes(b"altered result\n")
    with pytest.raises(RuntimeError, match="hash drift"):
        M37.verify_file(path, size=15, sha256=expected)


def test_verify_bundle_checks_each_file_and_the_combined_digest(tmp_path):
    payload = tmp_path / "viper" / "result.dat"
    payload.parent.mkdir()
    payload.write_bytes(b"result\n")
    record = {
        "path": "viper/result.dat",
        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "size_bytes": payload.stat().st_size,
    }
    manifest = {
        "included_files": [record],
        "bundle_sha256": M37._bundle_digest([record]),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert M37.verify_bundle(tmp_path, enforce_contract=False)["bundle_sha256"] == manifest[
        "bundle_sha256"
    ]

    payload.write_bytes(b"tampered\n")
    with pytest.raises(RuntimeError):
        M37.verify_bundle(tmp_path, enforce_contract=False)


def test_committed_evidence_bundle_matches_its_frozen_contract():
    manifest = M37.verify_bundle(ROOT / "data" / "repro")
    expected = M37._expected_manifest()
    assert len(manifest["included_files"]) == len(expected["included_files"])
    assert manifest["bundle_sha256"] == M37._bundle_digest(manifest["included_files"])


def test_verify_rejects_self_consistent_manifest_contract_drift():
    manifest = M37._expected_manifest()
    M37.validate_manifest_contract(manifest)

    manifest["included_files"] = manifest["included_files"][:-1]
    manifest["bundle_sha256"] = M37._bundle_digest(manifest["included_files"])
    with pytest.raises(RuntimeError, match="manifest contract drift"):
        M37.validate_manifest_contract(manifest)


def test_m37_generated_numerical_block_is_current():
    document = (ROOT / "docs" / "milestones" / "M37-RESULTS.md").read_text(
        encoding="utf-8"
    )
    assert M37_RENDER.update_document(document) == document
