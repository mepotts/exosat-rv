"""Render the script-owned numerical block in M37-RESULTS.md.

Numbers come only from the committed M35/M37 JSON artifacts and evidence manifest. Use
``--check`` in tests/CI to detect prose tables that have drifted from those sources.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/milestones/M37-RESULTS.md"
START = "<!-- BEGIN GENERATED M37 NUMBERS -->"
END = "<!-- END GENERATED M37 NUMBERS -->"


def _load(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _berv_row(result, combination: str, variant: str):
    return next(row for row in result["variants"][combination][variant] if row["berv"])


def _curve_point(series, semiamplitude: float):
    return next(
        point
        for point in series["injection_recovery"]["curve"]
        if point["semiamplitude_mmag"] == semiamplitude
    )


def render_generated() -> str:
    rv = _load("data/m37-cd35-reaudit.json")
    photometry = _load("data/m35-photometry-v2.json")
    manifest = _load("data/repro/manifest.json")

    lines = [
        START,
        "",
        "### 2.1 CD-35 2722 B: complete series versus internal screen",
        "",
        (
            f"The reference screen drops **{rv['internal_screen']['n_dropped']} of "
            f"{rv['internal_screen']['n_all']} nights**, BJD "
            f"**{rv['internal_screen']['dropped_bjd'][0]:.6f}**, whose nightly "
            f"across-order spread is "
            f"**{rv['internal_screen']['dropped_spread_m_per_s'][0]:.1f} m/s** against "
            f"the **{rv['internal_screen']['threshold_m_per_s']:.1f} m/s** threshold."
        ),
        "",
        (
            f"BERV-covariate results below use **{rv['method']['permutations']:,}** "
            "plus-one residual permutations over the full period grid. `p_global` is "
            "calibrated against the largest peak anywhere on that grid, conditional on "
            "the stated epoch selection; it does not charge for choosing the screen. These "
            "are nominal probabilities under exchangeable fitted base-model residuals, an "
            "assumption not established for these heteroscedastic 17/18-night series."
        ),
        "",
        (
            "| combine | all nights: best P (d) | all ΔBIC | all `p_global` | "
            "screened: best P (d) | screened ΔBIC | screened `p_global` |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for combination in ("mean", "median", "clip"):
        all_epochs = _berv_row(rv, combination, "all_epochs")
        screened = _berv_row(rv, combination, "internal_screen")
        lines.append(
            f"| {combination} | {all_epochs['P_max']:.2f} | "
            f"{all_epochs['dbic_max']:+.2f} | {all_epochs['p_max']:.4f} | "
            f"{screened['P_max']:.2f} | {screened['dbic_max']:+.2f} | "
            f"{screened['p_max']:.4f} |"
        )

    target_series = [
        series
        for series in photometry["series"]
        if series["physical_source_role"] == "cd35_2722_host"
    ]
    lines.extend(
        [
            "",
            "### 2.2 Host photometry: corrected night/camera-aware analysis",
            "",
            (
                "| ASAS-SN series | nights | fixed-period plus-one p | "
                "fine-grid K90 (mmag) | all-grid K90 (mmag) | max successive ΔC |"
            ),
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for series in target_series:
        injection = series["injection_recovery"]
        lines.append(
            f"| `{series['series']}` | {series['n_observing_nights']} | "
            f"{series['rv_period_p_plus_one']:.5f} | "
            f"{injection['first_sampled_K_mmag_with_fine_grid_phase_fraction_ge_0.90']:.0f} | "
            f"{injection['first_sampled_K_mmag_with_phase_fraction_ge_0.90_on_all_grids']:.0f} | "
            f"{injection['max_abs_successive_grid_fraction_change_over_curve']:.4f} |"
        )

    five_mmag = [_curve_point(series, 5.0)["phase_fraction"] for series in target_series]
    grid_resolved = [
        series["injection_recovery"][
            "first_sampled_K_mmag_with_phase_fraction_ge_0.90_on_all_grids"
        ]
        for series in target_series
    ]
    lines.extend(
        [
            "",
            (
                "The earlier 5 mmag semiamplitude is recovered in only "
                f"**{100 * min(five_mmag):.1f}–{100 * max(five_mmag):.1f}%** of "
                "the finest deterministic phase grid. The cross-series, grid-resolved "
                f"sensitivity is **{max(grid_resolved):.0f} mmag semiamplitude "
                f"({2 * max(grid_resolved):.0f} mmag peak to peak)**: the first sampled K "
                "reaching a 90% phase fraction on every 720-, 1,440-, and 2,880-point grid. "
                "This is numerical grid convergence, not a confidence interval. The four "
                "rows are paired aperture/filter reductions, not independent replications."
            ),
            "",
            "### 2.3 Evidence-bundle integrity",
            "",
            (
                f"The manifest verifies **{len(manifest['included_files'])} included files** "
                f"under combined digest `{manifest['bundle_sha256']}`. It separately "
                f"fingerprints **{len(manifest['external_hash_only_files'])} external-only "
                "inputs**."
            ),
            "",
            END,
        ]
    )
    return "\n".join(lines)


def update_document(text: str) -> str:
    if text.count(START) != 1 or text.count(END) != 1:
        raise RuntimeError("M37 document must contain exactly one generated block")
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    return before + render_generated() + after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = DOCUMENT.read_text(encoding="utf-8")
    rendered = update_document(current)
    if args.check:
        if rendered != current:
            print(f"stale generated block: {DOCUMENT.relative_to(ROOT)}")
            return 1
        print(f"current: {DOCUMENT.relative_to(ROOT)}")
        return 0
    DOCUMENT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {DOCUMENT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
