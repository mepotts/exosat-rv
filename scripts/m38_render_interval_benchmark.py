"""Validate and render every declared interval-benchmark case without manual numbers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import norm, t
from scripts import m38_interval_benchmark as benchmark

BEGIN = "<!-- BEGIN GENERATED M38 INTERVAL BENCHMARK -->"
END = "<!-- END GENERATED M38 INTERVAL BENCHMARK -->"


def equivalent(expected, observed):
    """Exact structure/counts/flags; numerical solver values permit declared roundoff."""
    if isinstance(expected, dict):
        return (
            isinstance(observed, dict)
            and expected.keys() == observed.keys()
            and all(equivalent(value, observed[key]) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(observed, list)
            and len(expected) == len(observed)
            and all(equivalent(a, b) for a, b in zip(expected, observed, strict=True))
        )
    if type(expected) is float:
        return type(observed) is float and math.isclose(
            expected, observed, rel_tol=1e-10, abs_tol=1e-12
        )
    return type(expected) is type(observed) and expected == observed


def validate_interval(value, truth, repetitions):
    for flag in ("complete", "covered"):
        if type(value[flag]) is not bool:
            raise ValueError("interval flags must be boolean")
    lo, hi = value["lower"], value["upper"]
    failed, unrun = value["failed_bootstrap_repetitions"], value["unrun_bootstrap_repetitions"]
    if any(type(x) is not int or x < 0 for x in (failed, unrun)) or failed + unrun > repetitions:
        raise ValueError("invalid failed/unrun accounting")
    if value["complete"]:
        if failed or unrun:
            raise ValueError("complete interval carries failures")
        if any(type(x) not in (float, int) or not math.isfinite(x) for x in (lo, hi)) or lo > hi:
            raise ValueError("invalid finite interval bounds")
        expected = benchmark.interval_record(lo, hi, truth)
    else:
        if lo is not None or hi is not None or failed + unrun == 0:
            raise ValueError("incomplete interval has endpoints or lacks failures")
        expected = benchmark.interval_record(None, None, truth, failed=failed, unrun=unrun)
    if not equivalent(expected, value):
        raise ValueError("interval event or width disagrees with bounds")


def validate_result(result):
    if result["schema"] != "m38-interval-benchmark-result-v1":
        raise ValueError("unsupported result schema")
    plan = result["plan"]
    benchmark.validate_plan(plan)
    if result["plan_sha256"] != benchmark.provenance.canonical_sha256(plan):
        raise ValueError("plan digest mismatch")
    if result["source_sha256"] != benchmark.source_hashes():
        raise ValueError("source digest mismatch")
    if len(result["cases"]) != len(plan["cases"]):
        raise ValueError("incomplete case roster")
    for cell, case in zip(result["cases"], plan["cases"], strict=True):
        if cell["case"] != case or len(cell["trials"]) != plan["trials_per_case"]:
            raise ValueError("case identity or trial count mismatch")
        methods = ["oracle-normal", "independent-block-t"] + [
            f"percentile-{label}-{repetitions}"
            for label in case["bootstrap_labels"]
            for repetitions in plan["bootstrap_repetitions"]
        ]
        for i, row in enumerate(cell["trials"]):
            if row["trial"] != i or row["data_seed"] != benchmark.seed_for(
                plan, case, i, "response-noise"
            ):
                raise ValueError("trial identity or data seed mismatch")
            if row["prefix_pairing_verified"] is not True or list(row["intervals"]) != methods:
                raise ValueError("pairing assertion or method roster mismatch")
            seeds = {
                label: benchmark.seed_for(plan, case, i, f"bootstrap-{label}")
                for label in case["bootstrap_labels"]
            }
            if row["bootstrap_seeds"] != seeds or set(row["score_sha256"]) != set(seeds):
                raise ValueError("bootstrap seed or score roster mismatch")
            groups = case["nights"] // 4 if case["noise"] == "season" else case["nights"]
            blocks = row["independent_block_slopes"]
            if len(blocks) != groups or not all(
                type(v) is float and math.isfinite(v) for v in blocks
            ):
                raise ValueError("invalid independent block slopes")
            center = float(np.mean(blocks))
            if not equivalent(center, row["slope"]):
                raise ValueError("point slope disagrees with block mean")
            probability = (1 + plan["confidence_level"]) / 2
            widths = {
                "oracle-normal": float(
                    norm.ppf(probability) * np.sqrt(benchmark.oracle_variance(plan, case))
                ),
                "independent-block-t": float(
                    t.ppf(probability, groups - 1) * np.std(blocks, ddof=1) / np.sqrt(groups)
                ),
            }
            for method, interval in row["intervals"].items():
                repetitions = 0 if method in widths else int(method.rsplit("-", 1)[1])
                validate_interval(interval, plan["true_slope"], repetitions)
                if method in widths:
                    half = widths[method]
                    expected = benchmark.interval_record(
                        center - half, center + half, plan["true_slope"]
                    )
                    if not equivalent(expected, interval):
                        raise ValueError("exact benchmark interval mismatch")
        if not equivalent(benchmark.summarize(plan, case, cell["trials"]), cell["summary"]):
            raise ValueError("summary does not match ledger")


def render(result):
    validate_result(result)
    plan = result["plan"]
    lines = [
        BEGIN,
        "",
        f"Plan SHA-256: `{result['plan_sha256']}`.",
        f"Retained {len(plan['cases']) * plan['trials_per_case']:,} independent noise trials. "
        "Methods within a trial are paired, not additional independent evidence.",
        "",
        f"All coverage intervals below are pointwise {100 * plan['monte_carlo_confidence_level']:g}% "
        "exact binomial Monte Carlo intervals.",
        "",
        "| Case | Method | Complete / planned | Coverage % [MC interval] | Mean width |",
        "|---|---|---:|---:|---:|",
    ]
    for cell in result["cases"]:
        for method, values in cell["summary"]["methods"].items():
            c = values["coverage_all_planned"]
            width = values["mean_width_given_complete"]
            width_text = "unavailable" if width is None else f"{width:.5f}"
            lines.append(
                f"| {cell['case']['id']} | {method} | {values['complete']}/{c['total']} | "
                f"{100 * c['rate']:.1f} [{100 * c['lower']:.1f}, {100 * c['upper']:.1f}] | {width_text} |"
            )
    lines += [
        "",
        "Paired coverage changes (second minus first; percentage points):",
        "",
        "| Case | First -> second | Neither | Second only | First only | Both | Change |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for cell in result["cases"]:
        for pair in cell["summary"]["paired_comparisons"]:
            c = pair["coverage_pairs"]
            lines.append(
                f"| {cell['case']['id']} | {pair['first']} -> {pair['second']} | "
                f"{c['00']} | {c['01']} | {c['10']} | {c['11']} | {100 * pair['second_minus_first']:+.1f} |"
            )
    lines += [
        "",
        "Known-variance diagnostic (sample variance uses `ddof=1`):",
        "",
        "| Case | Mean slope | Sample variance | Oracle variance | Ratio | Reference envelope |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cell in result["cases"]:
        s = cell["summary"]
        lo, hi = s["variance_ratio_reference_envelope"]
        lines.append(
            f"| {cell['case']['id']} | {s['mean_slope']:.5f} | "
            f"{s['sample_variance_ddof1']:.7f} | {s['oracle_variance']:.7f} | "
            f"{s['sample_to_oracle_variance_ratio']:.4f} | [{lo:.4f}, {hi:.4f}] |"
        )
    return "\n".join(lines + ["", END])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    raw = args.result.read_bytes()
    table = render(json.loads(raw))
    original = args.document.read_text(encoding="utf-8")
    if (
        original.count(BEGIN) != 1
        or original.count(END) != 1
        or original.index(BEGIN) > original.index(END)
    ):
        parser.error("document requires exactly one ordered generated block")
    updated = original[: original.index(BEGIN)] + table + original[original.index(END) + len(END) :]
    if args.check:
        if updated != original:
            parser.error("generated benchmark table is stale")
    else:
        with args.document.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
    print(f"Verified result SHA256 {hashlib.sha256(raw).hexdigest()}")


if __name__ == "__main__":
    main()
