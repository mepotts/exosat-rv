"""Night- and camera-aware ASAS-SN check of the 171.454 d RV period.

This is the corrected, version-2 M35 analysis. The original result is retained as
``data/m35-photometry.json``; this script writes the explicitly versioned
``data/m35-photometry-v2.json`` instead.

ASAS-SN commonly takes several exposures of a field on one night, sometimes with more
than one camera. Treating those exposures as independent makes both periodogram
significance and injection completeness too optimistic. This implementation therefore:

* removes a robust, per-camera magnitude zero point within each source/filter series;
* takes a median within each camera/night and then across cameras, leaving one equally
  weighted datum per Chilean observing night;
* permutes those complete night bins and uses the conservative plus-one p-value;
* injects sinusoids into the raw cached measurements and passes every phase through the
  same camera correction and nightly binning; and
* evaluates nested deterministic, uniform phase grids and reports the complete recovery
  curve plus numerical grid convergence. The phase points are quadrature nodes, not
  independent binomial trials, so no confidence interval is attached to their fraction.

The injected quantity is always a *semiamplitude*: ``K_mmag`` is the peak displacement
from the mean in millimagnitudes, so the peak-to-peak modulation is ``2 K_mmag``.

Usage: python scripts/m35_asassn_photometry.py [--refetch]
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np

_ROOT = os.environ.get("EXOSAT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

RA, DEC = 92.3300338228, -35.82529604851
P_RV_DAYS = 171.454
CACHE = os.path.join(_ROOT, "data", "m35-asassn-cd35.csv")
OUT = os.path.join(_ROOT, "data", "m35-photometry-v2.json")
LEGACY_OUT = os.path.join(_ROOT, "data", "m35-photometry.json")
TARGET_IDS = {609885843909, 661427779128}

PMIN_DAYS = 2.0
PMAX_CAP_DAYS = 2000.0
N_FREQUENCIES = 20_000
N_PERMUTATIONS = 2_000
PHASE_GRID_SIZES = (720, 1440, 2880)
N_PHASES = max(PHASE_GRID_SIZES)
DETECTION_ALPHA = 0.01
INJECTION_SEMIAMPLITUDES_MMAG = tuple(range(1, 21)) + (25, 30, 40, 50, 75, 100)
BASE_SEED = 20260831


@dataclass(frozen=True)
class NightBinningPlan:
    """Indices needed to repeat identical camera/night preprocessing on injections."""

    times: np.ndarray
    cameras: np.ndarray
    night_ids: np.ndarray
    unique_cameras: tuple[str, ...]
    unique_nights: np.ndarray
    camera_indices: tuple[np.ndarray, ...]
    camera_night_indices: tuple[np.ndarray, ...]
    camera_night_nights: np.ndarray
    binned_times: np.ndarray


def fetch(refetch: bool = False):
    """Load the committed cache, or explicitly refresh it when requested."""
    if os.path.exists(CACHE) and not refetch:
        with open(CACHE, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return (
            [float(r["jd"]) for r in rows],
            [float(r["mag"]) for r in rows],
            [float(r["mag_err"]) for r in rows],
            [r["phot_filter"] for r in rows],
            [int(r["asas_sn_id"]) for r in rows],
            [r["camera"] for r in rows],
        )
    if not refetch:
        raise FileNotFoundError(
            f"committed cache is missing: {CACHE}; pass --refetch to permit network access"
        )

    import warnings

    warnings.filterwarnings("ignore")
    from pyasassn.client import SkyPatrolClient

    client = SkyPatrolClient()
    lcs = client.cone_search(
        ra_deg=RA,
        dec_deg=DEC,
        radius=0.02,
        catalog="master_list",
        download=True,
        threads=2,
    )
    df = lcs.data
    keep = df[df["quality"] == "G"]
    keep = keep[(keep["mag_err"] > 0) & (keep["mag_err"] < 0.5)]
    keep.to_csv(
        CACHE,
        index=False,
        columns=["asas_sn_id", "jd", "mag", "mag_err", "phot_filter", "camera"],
    )
    return (
        list(keep["jd"]),
        list(keep["mag"]),
        list(keep["mag_err"]),
        list(keep["phot_filter"]),
        list(keep["asas_sn_id"]),
        list(keep["camera"]),
    )


def plus_one_pvalue(n_exceedances: int, n_permutations: int) -> float:
    """Return the finite-simulation p-value, including its non-zero floor."""
    if n_permutations < 1:
        raise ValueError("n_permutations must be positive")
    if not 0 <= n_exceedances <= n_permutations:
        raise ValueError("exceedances must lie between zero and n_permutations")
    return (n_exceedances + 1.0) / (n_permutations + 1.0)


def observing_night(jd: np.ndarray) -> np.ndarray:
    """Noon-to-noon UTC night identifier, which keeps a Chilean night together."""
    return np.floor(np.asarray(jd, dtype=float)).astype(np.int64)


def make_binning_plan(times, cameras) -> NightBinningPlan:
    """Build a camera-aware plan with one final point per observing night."""
    times = np.asarray(times, dtype=float)
    cameras = np.asarray(cameras, dtype=str)
    if times.ndim != 1 or cameras.shape != times.shape or len(times) == 0:
        raise ValueError("times and cameras must be non-empty one-dimensional arrays")
    if not np.all(np.isfinite(times)):
        raise ValueError("times must be finite")

    nights = observing_night(times)
    unique_cameras = tuple(sorted(np.unique(cameras).tolist()))
    unique_nights = np.unique(nights)
    camera_indices = tuple(np.flatnonzero(cameras == camera) for camera in unique_cameras)

    camera_night_indices = []
    camera_night_nights = []
    for night in unique_nights:
        on_night = nights == night
        for camera in unique_cameras:
            idx = np.flatnonzero(on_night & (cameras == camera))
            if len(idx):
                camera_night_indices.append(idx)
                camera_night_nights.append(night)

    binned_times = np.array([np.median(times[nights == night]) for night in unique_nights])
    return NightBinningPlan(
        times=times,
        cameras=cameras,
        night_ids=nights,
        unique_cameras=unique_cameras,
        unique_nights=unique_nights,
        camera_indices=camera_indices,
        camera_night_indices=tuple(camera_night_indices),
        camera_night_nights=np.asarray(camera_night_nights, dtype=np.int64),
        binned_times=binned_times,
    )


def apply_nightly_binning(values, plan: NightBinningPlan):
    """Camera-centre and bin one vector or a matrix whose rows are injected trials."""
    values = np.asarray(values, dtype=float)
    was_vector = values.ndim == 1
    if was_vector:
        values = values[None, :]
    if values.ndim != 2 or values.shape[1] != len(plan.times):
        raise ValueError("values must have one column per raw observation")
    if not np.all(np.isfinite(values)):
        raise ValueError("values must be finite")

    centred = values.copy()
    for idx in plan.camera_indices:
        centred[:, idx] -= np.median(values[:, idx], axis=1)[:, None]

    camera_night = np.empty((values.shape[0], len(plan.camera_night_indices)))
    for column, idx in enumerate(plan.camera_night_indices):
        camera_night[:, column] = np.median(centred[:, idx], axis=1)

    nightly = np.empty((values.shape[0], len(plan.unique_nights)))
    for column, night in enumerate(plan.unique_nights):
        use = plan.camera_night_nights == night
        nightly[:, column] = np.median(camera_night[:, use], axis=1)
    return nightly[0] if was_vector else nightly


def bounded_pmax(times) -> float:
    """Search no longer than half the baseline (at least two observed cycles)."""
    times = np.asarray(times, dtype=float)
    return min(PMAX_CAP_DAYS, float(np.ptp(times)) / 2.0)


def frequency_grid(times, n_frequencies: int = N_FREQUENCIES) -> np.ndarray:
    if n_frequencies < 2:
        raise ValueError("n_frequencies must be at least two")
    return np.linspace(1.0 / bounded_pmax(times), 1.0 / PMIN_DAYS, n_frequencies)


def fixed_period_power(times, values, period_days: float) -> np.ndarray | float:
    """Unweighted floating-mean LS power, vectorised over rows of ``values``."""
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    was_vector = values.ndim == 1
    if was_vector:
        values = values[None, :]
    if values.ndim != 2 or values.shape[1] != len(times):
        raise ValueError("values must have one column per time")

    angle = 2.0 * np.pi * times / period_days
    design = np.column_stack((np.ones(len(times)), np.sin(angle), np.cos(angle)))
    coefficients = values @ design @ np.linalg.pinv(design.T @ design)
    residual = values - coefficients @ design.T
    null_residual = values - values.mean(axis=1, keepdims=True)
    chi2 = np.sum(residual * residual, axis=1)
    chi2_null = np.sum(null_residual * null_residual, axis=1)
    power = np.divide(
        chi2_null - chi2,
        chi2_null,
        out=np.zeros_like(chi2),
        where=chi2_null > 0,
    )
    power = np.clip(power, 0.0, 1.0)
    return float(power[0]) if was_vector else power


def permutation_calibration(times, values, frequencies, rng, n_permutations):
    """Permute complete night bins and calibrate global and fixed-period powers."""
    from astropy.timeseries import LombScargle

    observed_ls = LombScargle(times, values)
    observed_grid = observed_ls.power(frequencies)
    best_index = int(np.argmax(observed_grid))
    observed_best = float(observed_grid[best_index])
    observed_target = float(fixed_period_power(times, values, P_RV_DAYS))

    max_null = np.empty(n_permutations)
    target_null = np.empty(n_permutations)
    for k in range(n_permutations):
        permuted = rng.permutation(values)
        max_null[k] = LombScargle(times, permuted).power(frequencies).max()
        target_null[k] = fixed_period_power(times, permuted, P_RV_DAYS)

    global_exceed = int(np.count_nonzero(max_null >= observed_best))
    target_exceed = int(np.count_nonzero(target_null >= observed_target))
    max_detection_exceedances = int(
        np.floor(DETECTION_ALPHA * (n_permutations + 1) - 1.0)
    )
    if max_detection_exceedances < 0:
        raise ValueError("permutation count is too small for the requested detection alpha")
    sorted_target_null = np.sort(target_null)
    critical_null_power = float(sorted_target_null[-(max_detection_exceedances + 1)])
    return {
        "best_period_days": float(1.0 / frequencies[best_index]),
        "best_power": observed_best,
        "power_at_rv_period": observed_target,
        "global_exceedances": global_exceed,
        "global_p_plus_one": plus_one_pvalue(global_exceed, n_permutations),
        "rv_period_exceedances": target_exceed,
        "rv_period_p_plus_one": plus_one_pvalue(target_exceed, n_permutations),
        "rv_period_detection_rule": {
            "alpha": DETECTION_ALPHA,
            "comparison": "(1 + count(null_power >= injected_power)) / (1 + N) <= alpha",
            "max_null_exceedances": max_detection_exceedances,
            "critical_null_power_boundary": critical_null_power,
            "boundary_note": (
                "with no ties, injected power must exceed this order statistic"
            ),
        },
        "rv_period_null_power_quantiles": {
            "q90": float(np.quantile(target_null, 0.90)),
            "q95": float(np.quantile(target_null, 0.95)),
            "q99": float(np.quantile(target_null, 0.99)),
        },
        "target_null_powers": target_null,
    }


def phase_completeness(
    raw_times,
    raw_values,
    plan,
    target_null_powers,
    semiamplitudes_mmag=INJECTION_SEMIAMPLITUDES_MMAG,
    n_phases=N_PHASES,
    convergence_grid_sizes=None,
    alpha=DETECTION_ALPHA,
):
    """Inject deterministic phases and report phase-fraction quadrature convergence."""
    if n_phases < 1:
        raise ValueError("n_phases must be positive")
    if convergence_grid_sizes is None:
        convergence_grid_sizes = (n_phases,)
    convergence_grid_sizes = tuple(int(size) for size in convergence_grid_sizes)
    if (
        not convergence_grid_sizes
        or convergence_grid_sizes[-1] != n_phases
        or tuple(sorted(set(convergence_grid_sizes))) != convergence_grid_sizes
        or any(size < 1 or n_phases % size for size in convergence_grid_sizes)
    ):
        raise ValueError(
            "convergence grids must be unique increasing divisors ending at n_phases"
        )
    target_null_powers = np.sort(np.asarray(target_null_powers, dtype=float))
    if target_null_powers.ndim != 1 or len(target_null_powers) < 1:
        raise ValueError("target_null_powers must be a non-empty vector")

    phases = np.linspace(0.0, 2.0 * np.pi, n_phases, endpoint=False)
    angle = 2.0 * np.pi * np.asarray(raw_times, dtype=float) / P_RV_DAYS
    waveform = np.sin(angle[None, :] + phases[:, None])
    curve = []
    for semiamplitude_mmag in semiamplitudes_mmag:
        semiamplitude_mag = float(semiamplitude_mmag) / 1000.0
        injected_raw = np.asarray(raw_values)[None, :] + semiamplitude_mag * waveform
        injected_nightly = apply_nightly_binning(injected_raw, plan)
        powers = np.asarray(fixed_period_power(plan.binned_times, injected_nightly, P_RV_DAYS))
        insertion = np.searchsorted(target_null_powers, powers, side="left")
        exceedances = len(target_null_powers) - insertion
        p_values = (exceedances + 1.0) / (len(target_null_powers) + 1.0)
        detected = p_values <= alpha
        recovered_by_grid = {
            str(size): int(np.count_nonzero(detected[:: n_phases // size]))
            for size in convergence_grid_sizes
        }
        fraction_by_grid = {
            key: recovered_by_grid[key] / int(key) for key in recovered_by_grid
        }
        successive_changes = [
            abs(fraction_by_grid[str(right)] - fraction_by_grid[str(left)])
            for left, right in pairwise(convergence_grid_sizes)
        ]
        successes = recovered_by_grid[str(n_phases)]
        curve.append(
            {
                "semiamplitude_mmag": float(semiamplitude_mmag),
                "semiamplitude_mag": semiamplitude_mag,
                "peak_to_peak_mmag": 2.0 * float(semiamplitude_mmag),
                "recovered_phases": successes,
                "phase_grid_size": n_phases,
                "phase_fraction": successes / n_phases,
                "recovered_phases_by_grid": recovered_by_grid,
                "phase_fraction_by_grid": fraction_by_grid,
                "max_abs_successive_grid_fraction_change": (
                    max(successive_changes) if successive_changes else 0.0
                ),
                "min_permutation_p_plus_one": float(np.min(p_values)),
                "max_permutation_p_plus_one": float(np.max(p_values)),
            }
        )
    return curve


def first_limit(curve, *, grid_sizes=None):
    """First sampled semiamplitude reaching 90% on the requested deterministic grids."""
    for point in curve:
        if grid_sizes is None:
            fractions = [point["phase_fraction"]]
        else:
            fractions = [point["phase_fraction_by_grid"][str(size)] for size in grid_sizes]
        if all(fraction >= 0.90 for fraction in fractions):
            return point["semiamplitude_mmag"]
    return None


def _series_seed(label: str) -> int:
    return BASE_SEED + zlib.crc32(label.encode("utf-8"))


def analyse_series(times, values, errors, cameras, label, source_id, phot_filter):
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    errors = np.asarray(errors, dtype=float)
    cameras = np.asarray(cameras, dtype=str)
    ok = (
        np.isfinite(times)
        & np.isfinite(values)
        & np.isfinite(errors)
        & (errors > 0)
        & (cameras != "")
    )
    times, values, errors, cameras = times[ok], values[ok], errors[ok], cameras[ok]
    if len(times) < 50:
        raise ValueError(f"{label} has only {len(times)} usable raw observations")

    plan = make_binning_plan(times, cameras)
    nightly_values = apply_nightly_binning(values, plan)
    frequencies = frequency_grid(plan.binned_times)
    rng = np.random.default_rng(_series_seed(label))
    calibration = permutation_calibration(
        plan.binned_times,
        nightly_values,
        frequencies,
        rng,
        N_PERMUTATIONS,
    )
    curve = phase_completeness(
        times,
        values,
        plan,
        calibration.pop("target_null_powers"),
        convergence_grid_sizes=PHASE_GRID_SIZES,
    )
    k90_by_grid = {
        str(size): first_limit(curve, grid_sizes=(size,)) for size in PHASE_GRID_SIZES
    }
    grid_resolved_k90 = first_limit(curve, grid_sizes=PHASE_GRID_SIZES)

    offsets = {
        camera: float(np.median(values[cameras == camera]))
        for camera in plan.unique_cameras
    }
    result = {
        "series": label,
        "asas_sn_id": int(source_id),
        "physical_source_role": (
            "cd35_2722_host" if source_id in TARGET_IDS else "field_control_40arcsec"
        ),
        "phot_filter": phot_filter,
        "n_raw_observations": len(times),
        "n_camera_night_bins": len(plan.camera_night_indices),
        "n_observing_nights": len(plan.unique_nights),
        "baseline_days": float(np.ptp(plan.binned_times)),
        "cameras": list(plan.unique_cameras),
        "camera_median_magnitudes": offsets,
        "permutation_seed": _series_seed(label),
        "grid_max_period_days": bounded_pmax(plan.binned_times),
        **calibration,
        "injection_recovery": {
            "quantity": "sinusoidal photometric semiamplitude K",
            "units": "millimagnitude",
            "peak_to_peak_relation": "peak-to-peak modulation = 2 K",
            "period_days": P_RV_DAYS,
            "detection_alpha": DETECTION_ALPHA,
            "phase_grid": "uniform deterministic [0, 2pi), endpoint excluded",
            "phase_grid_sizes": list(PHASE_GRID_SIZES),
            "finest_phase_grid_size": N_PHASES,
            "interpretation": (
                "deterministic uniform-phase fraction conditional on the observed residual "
                "series, camera/night preprocessing, and fixed-period permutation threshold"
            ),
            "curve": curve,
            "first_sampled_K_mmag_with_fine_grid_phase_fraction_ge_0.90": first_limit(curve),
            "k90_mmag_by_phase_grid": k90_by_grid,
            "first_sampled_K_mmag_with_phase_fraction_ge_0.90_on_all_grids": (
                grid_resolved_k90
            ),
            "max_abs_successive_grid_fraction_change_over_curve": max(
                point["max_abs_successive_grid_fraction_change"] for point in curve
            ),
        },
    }

    print(
        f"{label:16s} raw={len(times):4d} nights={len(plan.unique_nights):4d} "
        f"best={result['best_period_days']:9.3f} d "
        f"global p={result['global_p_plus_one']:.6f}"
    )
    fine_limit = result["injection_recovery"][
        "first_sampled_K_mmag_with_fine_grid_phase_fraction_ge_0.90"
    ]
    grid_resolved_limit = result["injection_recovery"][
        "first_sampled_K_mmag_with_phase_fraction_ge_0.90_on_all_grids"
    ]
    print(
        f"{'':16s} P={P_RV_DAYS:.3f} d power={result['power_at_rv_period']:.5f} "
        f"p={result['rv_period_p_plus_one']:.6f}; "
        f"K90(fine grid)={fine_limit} mmag, "
        f"K90(all nested grids)={grid_resolved_limit} mmag"
    )
    return result


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    jd, mag, err, filt, aid, camera = fetch("--refetch" in sys.argv)
    jd = np.asarray(jd, dtype=float)
    mag = np.asarray(mag, dtype=float)
    err = np.asarray(err, dtype=float)
    filt = np.asarray(filt, dtype=str)
    aid = np.asarray(aid, dtype=np.int64)
    camera = np.asarray(camera, dtype=str)

    print(f"# M35 photometry v2: night/camera-aware test at {P_RV_DAYS:.3f} d")
    access = (
        "network refresh requested"
        if "--refetch" in sys.argv
        else "committed cache; no network"
    )
    print(f"# input: {os.path.relpath(CACHE, _ROOT)} ({len(jd)} rows; {access})")
    print(
        f"# {N_PERMUTATIONS} night permutations; plus-one p-values; "
        f"{N_PHASES} deterministic injection phases\n"
    )

    results = []
    for source_id in sorted(np.unique(aid)):
        for phot_filter in ("V", "g"):
            use = (aid == source_id) & (filt == phot_filter)
            if np.count_nonzero(use) >= 50:
                label = f"{source_id}/{phot_filter}"
                results.append(
                    analyse_series(
                        jd[use],
                        mag[use],
                        err[use],
                        camera[use],
                        label,
                        int(source_id),
                        phot_filter,
                    )
                )

    import astropy

    target_sampling = []
    target_row_counts = {}
    for source_id in sorted(TARGET_IDS):
        use = aid == source_id
        target_row_counts[str(source_id)] = int(np.count_nonzero(use))
        target_sampling.append(Counter(zip(jd[use], filt[use], camera[use])))
    shared_target_rows = sum((target_sampling[0] & target_sampling[1]).values())

    artifact = {
        "schema_version": "m35-photometry-v2.1",
        "analysis_date": datetime.now(UTC).date().isoformat(),
        "input": {
            "path": str(Path(CACHE).relative_to(_ROOT)).replace("\\", "/"),
            "sha256": _sha256(CACHE),
            "rows": len(jd),
            "network_used": "--refetch" in sys.argv,
            "cache_refresh_query": {
                "service": "ASAS-SN Sky Patrol master_list cone search",
                "ra_deg": RA,
                "dec_deg": DEC,
                "radius_deg": 0.02,
                "row_filter": "quality == 'G' and 0 < mag_err < 0.5",
                "cached_columns": [
                    "asas_sn_id",
                    "jd",
                    "mag",
                    "mag_err",
                    "phot_filter",
                    "camera",
                ],
            },
        },
        "legacy_artifact_preserved": str(Path(LEGACY_OUT).relative_to(_ROOT)).replace("\\", "/"),
        "method": {
            "observing_night": "floor(JD), a noon-to-noon UTC interval",
            "camera_correction": "subtract per-camera median within each source/filter series",
            "binning": "median within camera/night, then median across cameras; one point/night",
            "periodogram_weighting": "equal weight per observing night",
            "search_period_days": [PMIN_DAYS, "min(2000, baseline/2)"],
            "n_frequency_grid": N_FREQUENCIES,
            "permutation_unit": "complete camera-corrected observing-night bin",
            "n_permutations": N_PERMUTATIONS,
            "p_value": "(1 + null statistics >= observed) / (1 + n_permutations)",
            "p_value_floor": plus_one_pvalue(0, N_PERMUTATIONS),
            "permutation_scope": (
                "nominal conditional p-values assuming exchangeability of final night bins; "
                "camera/season heteroskedasticity has not been calibrated"
            ),
            "rv_period_days": P_RV_DAYS,
            "injection_location": (
                "raw cached magnitudes, before camera correction and night binning"
            ),
            "injection_quantity": "sinusoidal semiamplitude K in millimagnitudes",
            "deterministic_phase_grid_sizes": list(PHASE_GRID_SIZES),
            "phase_fraction_inference": (
                "numerical uniform-phase quadrature with nested-grid convergence; "
                "not a binomial sample and no confidence interval"
            ),
        },
        "software": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "astropy": astropy.__version__,
        },
        "implementation": {
            "path": "scripts/m35_asassn_photometry.py",
            "sha256": _sha256(__file__),
        },
        "target_source_relationship": {
            "asas_sn_ids": sorted(TARGET_IDS),
            "rows_by_id": target_row_counts,
            "shared_timestamp_filter_camera_rows": shared_target_rows,
            "sampling_keys_identical": target_sampling[0] == target_sampling[1],
            "interpretation": (
                "paired catalog/aperture light curves of the same unresolved host; "
                "not independent replications"
            ),
        },
        "series": results,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    print(f"\nwrote {os.path.relpath(OUT, _ROOT)}")
    print(f"preserved legacy artifact {os.path.relpath(LEGACY_OUT, _ROOT)}")


if __name__ == "__main__":
    main()
