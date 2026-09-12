"""Render the retained synthetic-only real VIPER bridge numbers, without running VIPER."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from exosat_rv.m38.viper_bridge import C_MPS, sha256

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/m38-viper-synthetic-bridge-2026-09-12.json"
REPORT = ROOT / "docs/milestones/M38-VIPER-SYNTHETIC-BRIDGE.md"
START = "<!-- BEGIN GENERATED VIPER BRIDGE -->"
END = "<!-- END GENERATED VIPER BRIDGE -->"


def render(result: dict) -> str:
    if result["schema"] != "m38-viper-generated-engineering-v1":
        raise ValueError("unknown bridge evidence schema")
    for key, filename in (
        ("driver_sha256", "scripts/m38_viper_synthetic_bridge.py"),
        ("bridge_sha256", "src/exosat_rv/m38/viper_bridge.py"),
    ):
        if result[key] != sha256(ROOT / filename):
            raise ValueError(f"retained bridge source mismatch: {filename}")
    cases = result["cases"]
    required = {
        "reference",
        "zero_repeat",
        "positive",
        "negative",
        "heldout_perturb",
        "noise_1847",
        "noise_1848",
    }
    if set(cases) != required:
        raise ValueError("incomplete engineering campaign")
    lines = [
        "| Case | Max absolute learned-template residual (m/s) | Max absolute known-template residual (m/s) | Final adjacent flux change |",
        "|---|---:|---:|---:|",
    ]
    for name, case in cases.items():
        if [item["iteration"] for item in case["history"]] != [0, 1, 2, 3]:
            raise ValueError("expected exactly four native template stages")
        if len(case["expected_log_velocity_mps"]) != 4:
            raise ValueError("expected exactly four heldout velocities")
        vectors = {}
        for key in (
            "evaluation_velocity_mps",
            "expected_log_velocity_mps",
            "learned_minus_expected_mps",
            "known_minus_expected_mps",
        ):
            vector = np.asarray(case[key], dtype=float)
            if vector.shape != (4,) or not np.isfinite(vector).all():
                raise ValueError("invalid finite four-epoch vector")
            vectors[key] = vector
        if np.any(abs(vectors["evaluation_velocity_mps"]) > 10000) or not np.allclose(
            C_MPS * np.log1p(vectors["evaluation_velocity_mps"] / C_MPS),
            vectors["expected_log_velocity_mps"],
            rtol=0,
            atol=1e-10,
        ):
            raise ValueError("physical/log velocity convention mismatch")
        for stage in case["history"][1:]:
            change = stage["max_adjacent_flux_change"]
            if not np.isfinite(change) or change < 0:
                raise ValueError("invalid adjacent flux change")
        for role in ("heldout", "known"):
            if set(case[role]["rows"]) != {f"epoch{i:02d}.fits" for i in range(4)}:
                raise ValueError("unexpected heldout identity roster")
            measured = np.array([case[role]["rows"][f"epoch{i:02d}.fits"]["rv0"] for i in range(4)])
            residual_key = ("learned" if role == "heldout" else "known") + "_minus_expected_mps"
            if not np.isfinite(measured).all() or not np.allclose(
                measured - vectors["expected_log_velocity_mps"],
                vectors[residual_key],
                rtol=0,
                atol=1e-10,
            ):
                raise ValueError("stored residual does not match named RV rows")
        lines.append(
            f"| `{name}` | {max(abs(np.asarray(case['learned_minus_expected_mps']))):.6f} | "
            f"{max(abs(np.asarray(case['known_minus_expected_mps']))):.6f} | "
            f"{case['history'][-1]['max_adjacent_flux_change']:.9g} |"
        )
    reference = cases["reference"]
    for name in ("zero_repeat", "heldout_perturb"):
        if [item["native_arrays_sha256"] for item in reference["history"]] != [
            item["native_arrays_sha256"] for item in cases[name]["history"]
        ]:
            raise ValueError("training template isolation/replay failed")
    for name in ("positive", "negative"):
        if any(
            left["native_arrays_sha256"] == right["native_arrays_sha256"]
            for left, right in zip(cases[name]["history"], reference["history"], strict=True)
        ):
            raise ValueError("training perturbation did not alter every template stage")
    lines += [
        "",
        "Every retained native template wavelength/flux/scatter array is bitwise identical",
        "between `reference`, `zero_repeat`, and `heldout_perturb` at all four stages.",
        "Perturbing the training velocities changes the reconstructed template.",
        "",
        "| Paired injection case | Slope (with intercept) | Intercept (m/s) |",
        "|---|---:|---:|",
    ]
    epoch_keys = [f"epoch{i:02d}.fits" for i in range(4)]
    ref_rv = np.array([reference["heldout"]["rows"][key]["rv0"] for key in epoch_keys])
    for name in ("positive", "negative"):
        case = cases[name]
        injection = np.asarray(case["expected_log_velocity_mps"]) - np.asarray(
            reference["expected_log_velocity_mps"]
        )
        delta = np.array([case["heldout"]["rows"][key]["rv0"] for key in epoch_keys]) - ref_rv
        slope, intercept = np.polyfit(injection, delta, 1)
        lines.append(f"| `{name}` | {slope:.9f} | {intercept:.6f} |")
    lines += [
        "",
        "Paired slopes use expected log-velocity differences, consistently with the absolute residuals.",
        "These four-epoch paired slopes are engineering summaries, not calibrated recovery",
        "intervals. Template zero-point shifts are shown as intercepts, not fitted away",
        "from the absolute-residual table. Two noise seeds do not establish uncertainty coverage.",
        "",
        f"Retained evidence SHA-256: `{sha256(EVIDENCE)}`.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = REPORT.read_text(encoding="utf-8")
    before, rest = document.split(START)
    _, after = rest.split(END)
    updated = (
        before + START + "\n\n" + render(json.loads(EVIDENCE.read_text())) + "\n\n" + END + after
    )
    if args.check:
        if updated != document:
            raise ValueError("bridge report is stale")
        print("bridge source hashes and generated report verified")
    else:
        REPORT.write_text(updated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
