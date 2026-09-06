"""Render the pilot's complete, count-based table without hand-transcribed numbers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from scripts.m38_selection_coverage import (
    _source_hashes,
    canonical_sha256,
    summarize_trials,
    trial_seed,
    validate_plan,
)

BEGIN = "<!-- BEGIN GENERATED M38 COVERAGE -->"
END = "<!-- END GENERATED M38 COVERAGE -->"


def summaries_match(actual: dict, stored: dict) -> bool:
    """Counts/rates/nulls are exact; binomial solver endpoints allow tiny version drift."""
    if actual.keys() != stored.keys():
        return False
    for key, value in actual.items():
        candidate = stored[key]
        if not isinstance(candidate, dict) or value.keys() != candidate.keys():
            return False
        for field, expected in value.items():
            observed = candidate[field]
            if field in ("lower", "upper") and expected is not None:
                if type(observed) not in (float, int) or not math.isclose(
                    expected, observed, rel_tol=1e-10, abs_tol=1e-12
                ):
                    return False
            elif type(observed) is not type(expected) or observed != expected:
                return False
    return True


def validate_events(record: dict, truth: float, plan: dict) -> None:
    """Recompute event flags from the numerical interval, not from stored summaries."""
    for key in ("complete", "covered", "attrition_passed", "interval_gate_passed"):
        if type(record[key]) is not bool:
            raise ValueError("event flags must be boolean")
    lo, hi = record["lower"], record["upper"]
    if record["complete"]:
        if (
            any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (lo, hi, record["slope"])
            )
            or lo > hi
        ):
            raise ValueError("complete interval must have finite ordered bounds")
    elif lo is not None or hi is not None:
        raise ValueError("incomplete interval cannot have bounds")
    expected_coverage = bool(record["complete"] and lo <= truth <= hi)
    delta = plan["equivalence_delta"]
    expected_gate = bool(
        record["complete"] and record["attrition_passed"] and lo >= 1 - delta and hi <= 1 + delta
    )
    outside = truth <= 1 - delta or truth >= 1 + delta
    expected_false = expected_gate if outside else None
    if (
        record["covered"] is not expected_coverage
        or record["interval_gate_passed"] is not expected_gate
        or record["false_equivalence"] is not expected_false
    ):
        raise ValueError("stored event flags disagree with interval semantics")
    failed, unrun = record["failed_bootstrap_repetitions"], record["unrun_bootstrap_repetitions"]
    if any(type(x) is not int or x < 0 for x in (failed, unrun)):
        raise ValueError("invalid bootstrap failure counts")
    if failed + unrun > plan["bootstrap_repetitions"]:
        raise ValueError("bootstrap failure counts exceed planned repetitions")
    if record["complete"] != (failed + unrun == 0):
        raise ValueError("completion and bootstrap failure counts disagree")


def validated_table(result: dict) -> str:
    plan = result["plan"]
    validate_plan(plan)
    if result["plan_sha256"] != canonical_sha256(plan):
        raise ValueError("plan digest mismatch")
    if result["source_sha256"] != _source_hashes():
        raise ValueError("source digest mismatch; use the recorded source snapshot")
    expected = [
        (scenario, truth) for scenario in plan["scenarios"] for truth in plan["true_slopes"]
    ]
    if len(result["cells"]) != len(expected):
        raise ValueError("incomplete cell roster")
    lines = [
        BEGIN,
        "",
        f"Plan SHA-256: `{result['plan_sha256']}`.",
        f"All {len(expected) * plan['trials_per_cell']:,} planned response trials are retained.",
        f"Coverage is all-planned; brackets are pointwise "
        f"{100 * plan['monte_carlo_confidence_level']:g}% exact Monte Carlo intervals.",
        "An absent recovery interval is a non-covering trial, not silently excluded.",
        "Gate passes at the equivalence boundaries or outside them are false-equivalence events.",
        "",
        "| Scenario | True slope | Complete / planned | Coverage % [MC interval] | Interval gate passes / planned |",
        "|---|---:|---:|---:|---:|",
    ]
    for cell, (scenario, truth) in zip(result["cells"], expected, strict=True):
        if cell["scenario"] != scenario or cell["true_slope"] != truth:
            raise ValueError("cell identity mismatch")
        records = cell["trials"]
        if len(records) != plan["trials_per_cell"]:
            raise ValueError("incomplete trial roster")
        for i, record in enumerate(records):
            validate_events(record, truth, plan)
            if record["trial"] != i:
                raise ValueError("trial identity mismatch")
            for field, domain in (
                ("data_seed", "response-noise"),
                ("bootstrap_seed", "cluster-bootstrap"),
            ):
                if record[field] != trial_seed(plan, scenario, truth, i, domain):
                    raise ValueError("trial seed mismatch")
        summary = summarize_trials(records, plan["monte_carlo_confidence_level"])
        if not summaries_match(summary, cell["summary"]):
            raise ValueError("stored summary does not match trial ledger")
        c = summary["covered"]
        n = len(records)
        lines.append(
            f"| {scenario['id']} | {truth:g} | {summary['complete']['successes']}/{n} | "
            f"{100 * c['rate']:.1f} [{100 * c['lower']:.1f}, {100 * c['upper']:.1f}] | "
            f"{summary['interval_gate_passed']['successes']}/{n} |"
        )
    lines += ["", END]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    raw = args.result.read_bytes()
    result = json.loads(raw)
    table = validated_table(result)
    original = args.document.read_text(encoding="utf-8")
    if original.count(BEGIN) != 1 or original.count(END) != 1:
        parser.error("document requires exactly one ordered generated block")
    start, end = original.index(BEGIN), original.index(END) + len(END)
    if end < start:
        parser.error("generated block markers are reversed")
    updated = original[:start] + table + original[end:]
    if args.check:
        if updated != original:
            parser.error("generated coverage table is stale")
    else:
        with args.document.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
    print(f"Verified result SHA256 {hashlib.sha256(raw).hexdigest()}")


if __name__ == "__main__":
    main()
