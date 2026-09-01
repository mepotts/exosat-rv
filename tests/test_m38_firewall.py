"""Synthetic-only tests for the M38 application information firewall."""

from __future__ import annotations

import hashlib
import json
from collections import UserDict
from pathlib import Path

import pytest

from exosat_rv.m38.firewall import (
    FirewallViolation,
    InformationFirewall,
    enforce_output_fields,
)


class IntSubclass(int):
    """A JSON-looking scalar that the output barrier must reject."""


def fixed_clock():
    return "2030-01-01T00:00:00Z"


def test_checked_open_allows_and_logs_content_bound_read(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "control.txt"
    source.write_text("synthetic control\n", encoding="utf-8")
    log_path = tmp_path / "access.jsonl"
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        access_log_path=log_path,
        clock=fixed_clock,
    )

    with firewall.checked_open(source, "r") as handle:
        assert handle.read() == "synthetic control\n"

    event = firewall.access_log[0]
    assert event["decision"] == "allowed"
    assert event["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert event["size_bytes"] == source.stat().st_size
    assert event["timestamp"] == fixed_clock()
    persisted = [json.loads(line) for line in log_path.read_text("utf-8").splitlines()]
    assert persisted == list(firewall.access_log)


def test_path_rules_and_resolved_escape_fail_before_open(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    denied = allowed / "blocked.bin"
    denied.write_bytes(b"safe bytes")
    patterned = allowed / "notes.secret"
    patterned.write_text("ordinary", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        denied_paths={denied: "explicit synthetic denial"},
        denied_path_patterns={"*.secret": "secret suffix denied"},
        clock=fixed_clock,
    )

    with pytest.raises(FirewallViolation, match="explicit synthetic denial"):
        firewall.preflight(denied)
    with pytest.raises(FirewallViolation, match="secret suffix denied"):
        firewall.preflight(patterned)
    with pytest.raises(FirewallViolation, match="outside"):
        firewall.preflight(allowed / ".." / "outside.txt")

    assert [event["decision"] for event in firewall.access_log] == [
        "denied",
        "denied",
        "denied",
    ]


def test_content_and_hash_rules_are_caller_supplied_and_fail_closed(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    content_denied = allowed / "content.txt"
    content_denied.write_text("prefix FORBIDDEN_TOKEN suffix", encoding="utf-8")
    hash_denied = allowed / "hash.txt"
    hash_denied.write_text("otherwise ordinary", encoding="utf-8")
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        denied_content={b"FORBIDDEN_TOKEN": "synthetic content denied"},
        denied_hashes={
            hashlib.sha256(hash_denied.read_bytes()).hexdigest(): "synthetic hash denied"
        },
        clock=fixed_clock,
    )

    with pytest.raises(FirewallViolation, match="content denied"):
        firewall.preflight(content_denied)
    with pytest.raises(FirewallViolation, match="hash denied"):
        firewall.preflight(hash_denied)


def test_content_scan_detects_pattern_across_streaming_block_boundary(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "large.bin"
    source.write_bytes(b"x" * (1024 * 1024 - 3) + b"ABCDEF" + b"y" * 10)
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        denied_content={b"ABCDEF": "boundary-spanning pattern"},
        clock=fixed_clock,
    )

    with pytest.raises(FirewallViolation, match="boundary-spanning"):
        firewall.preflight(source)


def test_tree_audit_applies_rules_before_a_runnable_image_is_accepted(tmp_path):
    allowed = tmp_path / "image"
    allowed.mkdir()
    (allowed / "ordinary.txt").write_text("ordinary", encoding="utf-8")
    forbidden = allowed / "blocked.txt"
    forbidden.write_text("synthetic blocked phrase", encoding="utf-8")
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        denied_content={"blocked phrase": "tree audit denial"},
        clock=fixed_clock,
    )

    with pytest.raises(FirewallViolation, match="tree audit denial"):
        firewall.audit_allowed_tree()


def test_allowed_file_can_be_explicit_and_write_modes_are_refused(tmp_path):
    allowed_root = tmp_path / "root"
    allowed_root.mkdir()
    exact = tmp_path / "exact.txt"
    exact.write_text("exact", encoding="utf-8")
    firewall = InformationFirewall(
        allowed_roots=[allowed_root],
        allowed_files=[exact],
        clock=fixed_clock,
    )

    with firewall.checked_open(exact) as handle:
        assert handle.read() == b"exact"
    with pytest.raises(FirewallViolation, match="read-only"), firewall.checked_open(exact, "w"):
        pass
    denied = firewall.access_log[-1]
    assert denied["decision"] == "denied"
    assert denied["operation"] == "open"
    assert "read-only" in denied["reason"]


def test_symlink_is_rejected_even_when_it_resolves_inside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "source.txt"
    link = allowed / "link.txt"
    source.write_text("content", encoding="utf-8")
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")
    firewall = InformationFirewall(allowed_roots=[allowed], clock=fixed_clock)

    with pytest.raises(FirewallViolation, match="symlink"):
        firewall.preflight(link)


def test_output_barrier_is_recursive_case_insensitive_and_allowlisted(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    firewall = InformationFirewall(
        allowed_roots=[allowed],
        allowed_output_fields={"status", "winner_id", "hashes", "diagnostics"},
        denied_output_fields={
            "combined_values": "combined values may not cross this barrier",
            "*period_diagnostic*": "period diagnostics may not cross this barrier",
        },
        clock=fixed_clock,
    )
    safe = {
        "status": "complete",
        "winner_id": "arm-02",
        "hashes": {"manifest": "a" * 64},
        "diagnostics": ({"converged": True},),
    }
    detached = firewall.check_output(safe)
    assert detached == safe | {"diagnostics": [{"converged": True}]}
    assert detached is not safe
    assert detached["hashes"] is not safe["hashes"]
    safe["hashes"]["manifest"] = "changed after barrier"
    assert detached["hashes"]["manifest"] == "a" * 64

    with pytest.raises(FirewallViolation, match="allowlist"):
        firewall.check_output(safe | {"unexpected": 1})
    with pytest.raises(FirewallViolation, match="combined values"):
        firewall.check_output(safe | {"diagnostics": {"Combined_Values": [1, 2]}})
    with pytest.raises(FirewallViolation, match="period diagnostics"):
        firewall.check_output(safe | {"diagnostics": {"period_diagnostic_grid": [1]}})

    assert [event["decision"] for event in firewall.access_log] == [
        "allowed",
        "denied",
        "denied",
        "denied",
    ]


def test_standalone_output_barrier_rejects_non_string_and_nested_denied_fields():
    with pytest.raises(FirewallViolation, match="native strings"):
        enforce_output_fields({1: "not allowed"})
    with pytest.raises(FirewallViolation, match="sealed field"):
        enforce_output_fields(
            {"outer": [{"sealed": "value"}]},
            denied_fields={"sealed": "sealed field"},
        )


def test_output_barrier_normalises_tuples_before_recursive_denials():
    payload = {"items": ({"safe": [1, 2]},)}
    detached = enforce_output_fields(payload)

    assert detached == {"items": [{"safe": [1, 2]}]}
    assert detached is not payload
    assert detached["items"][0] is not payload["items"][0]
    with pytest.raises(FirewallViolation, match="sealed field"):
        enforce_output_fields(
            {"outer": ({"sealed": "value"},)},
            denied_fields={"sealed": "sealed field"},
        )


def test_output_barrier_is_cycle_and_depth_safe_and_logs_denials(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    firewall = InformationFirewall(allowed_roots=[allowed], clock=fixed_clock)

    shared = {"value": 1}
    detached = firewall.check_output({"left": shared, "right": shared})
    assert detached == {"left": {"value": 1}, "right": {"value": 1}}
    assert detached["left"] is not shared
    assert detached["right"] is not shared
    assert detached["left"] is not detached["right"]

    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(FirewallViolation, match="reference cycle"):
        firewall.check_output(cycle)

    too_deep = {}
    cursor = too_deep
    for _ in range(300):
        child = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(FirewallViolation, match="maximum nesting depth"):
        firewall.check_output(too_deep)

    assert [event["decision"] for event in firewall.access_log] == [
        "allowed",
        "denied",
        "denied",
    ]
    assert "reference cycle" in firewall.access_log[1]["reason"]
    assert "maximum nesting depth" in firewall.access_log[2]["reason"]


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": {1, 2}},
        {"value": IntSubclass(1)},
        UserDict({"value": 1}),
    ],
)
def test_output_barrier_rejects_non_json_and_non_native_values(payload):
    with pytest.raises(FirewallViolation, match="finite|native JSON"):
        enforce_output_fields(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"Status": 1, "status": 2},
        {"outer": {"Token": 1, "token": 2}},
    ],
)
def test_output_barrier_rejects_casefold_duplicate_fields(payload):
    with pytest.raises(FirewallViolation, match="duplicate fields"):
        enforce_output_fields(payload)


def test_resolution_and_reopen_errors_are_logged(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    firewall = InformationFirewall(allowed_roots=[allowed], clock=fixed_clock)

    real_resolve = Path.resolve

    def failing_resolve(self, strict=False):
        if self == source:
            raise OSError("synthetic resolution error")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", failing_resolve)
    with pytest.raises(FirewallViolation, match="resolution failed"):
        firewall.preflight(source)
    resolution_event = firewall.access_log[-1]
    assert resolution_event["decision"] == "denied"
    assert "synthetic resolution error" in resolution_event["reason"]

    monkeypatch.setattr(Path, "resolve", real_resolve)
    resolved_source = source.resolve(strict=True)
    real_open = Path.open
    source_open_count = 0

    def failing_second_open(self, *args, **kwargs):
        nonlocal source_open_count
        if self == resolved_source:
            source_open_count += 1
            if source_open_count == 2:
                raise PermissionError("synthetic reopen error")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_second_open)
    with (
        pytest.raises(FirewallViolation, match="checked open failed"),
        firewall.checked_open(source),
    ):
        pass
    reopen_event = firewall.access_log[-1]
    assert reopen_event["decision"] == "denied"
    assert "synthetic reopen error" in reopen_event["reason"]
