"""Offline CLI regressions for archive inventory and installed-package storage."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from exosat_rv import cli, config


def test_inventory_writes_report_after_successful_query(monkeypatch, tmp_path):
    summary = {
        "nights_total": 2,
        "usable_now": 1,
        "reduction_gap": 1,
        "embargoed": 0,
        "usable_baseline": None,
        "gap_nights": [],
        "embargo_lifts": [],
    }
    inventory = SimpleNamespace(
        summary=lambda band: summary, nights=[], now=datetime(2026, 9, 5, tzinfo=UTC)
    )
    monkeypatch.setattr(cli, "build_inventory", lambda *args: inventory)
    storage = tmp_path / "nested" / "data"
    monkeypatch.setattr(cli, "DATA", storage)
    result = CliRunner().invoke(cli.app, ["inventory"])
    assert result.exit_code == 0, result.output
    assert "historical preprint used 20 usable epochs" in result.output
    assert json.loads((storage / "m0-inventory.json").read_text())["summary"] == summary


def test_explicit_data_directory_is_resolved_without_creating_it(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXOSAT_DATA_DIR", "chosen/data")
    assert config._data_directory() == tmp_path / "chosen" / "data"
    assert not (tmp_path / "chosen").exists()


def test_source_checkout_keeps_its_data_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("EXOSAT_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert config._data_directory() == Path(config.__file__).resolve().parents[2] / "data"


def test_wheel_storage_uses_caller_directory_not_installation(monkeypatch, tmp_path):
    monkeypatch.delenv("EXOSAT_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        config, "__file__", str(tmp_path / "venv/lib/site-packages/exosat_rv/config.py")
    )
    assert config._data_directory() == tmp_path / "data"
    assert not (tmp_path / "data").exists()
