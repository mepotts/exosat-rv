"""M37: recompute the CD-35 period evidence with and without the internal screen.

This is deliberately a thin orchestrator around the existing reference calculations:
``m14_score`` owns order combination/night binning and ``m28_nullcal`` owns the BIC
landscape and residual-permutation calibration.  The new work here is to run the same
calibration on both the complete 18-night series and the internally screened 17-night
series, side by side, from the M37 evidence bundle.

Writes ``data/m37-cd35-reaudit.json`` by default.  The ``published()`` data loader is never
called and no published RV value enters the calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INJECTION = ROOT / "scripts" / "injection"
sys.path.insert(0, str(INJECTION))

import m28_nullcal as nullcal
from m14_score import bin_frames, combine, order_matrix

DEFAULT_SERIES = ROOT / "data/repro/viper/results/M14_NODT2.rvo.dat"
DEFAULT_OUTPUT = ROOT / "data/m37-cd35-reaudit.json"
SEED = 20260813
IMPLEMENTATION_FILES = (
    ROOT / "scripts/m37_reaudit.py",
    INJECTION / "m14_score.py",
    INJECTION / "m28_nullcal.py",
    INJECTION / "vs_published.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_value(value):
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [json_value(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def adopted_series(path: Path):
    """Return the three reference combines and the blind-search internal screen."""
    t_frame, berv_frame, order_rvs, orders = order_matrix(str(path))
    t_frame = np.asarray(t_frame, float)
    berv_frame = np.asarray(berv_frame, float)

    combined = {}
    t_night = berv_night = None
    for how in ("mean", "median", "clip"):
        values = combine(order_rvs, how)
        t_binned, values_binned, berv_binned = bin_frames(t_frame, values, berv_frame)
        if t_night is None:
            t_night, berv_night = t_binned, berv_binned
        else:
            if not np.array_equal(t_night, t_binned):
                raise RuntimeError("night binning differs between combination methods")
        combined[how] = values_binned

    spread_frame = np.nanstd(
        order_rvs - np.nanmedian(order_rvs, axis=0)[None, :], axis=0
    )
    _, spread_night, _ = bin_frames(t_frame, spread_frame, berv_frame)
    bad, threshold = nullcal.internal_screen(spread_night)
    return t_night, berv_night, combined, spread_night, bad, orders, threshold


def run_audit(path: Path, *, nperm: int, ngrid: int) -> dict[str, object]:
    t, berv, combined, spread, bad, orders, threshold = adopted_series(path)
    try:
        source_label = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        source_label = str(path)
    variants: dict[str, object] = {}
    for how, values in combined.items():
        variants[how] = {}
        for screen_name, keep in (
            ("all_epochs", np.ones(len(t), dtype=bool)),
            ("internal_screen", ~bad),
        ):
            # Resetting makes every recorded result reproducible in isolation and avoids
            # an accidental dependence on loop ordering.
            nullcal.RNG = np.random.default_rng(SEED)
            rows = nullcal.run(
                f"{how}/{screen_name}",
                t[keep],
                values[keep],
                berv[keep],
                nperm,
                ngrid,
            )
            variants[how][screen_name] = rows

    return json_value(
        {
            "schema_version": 1,
            "method": {
                "order_combination_and_night_binning": "scripts/injection/m14_score.py",
                "landscape_and_permutation_calibration":
                    "scripts/injection/m28_nullcal.py",
                "published_loader_called": False,
                "published_rvs_used": False,
                "permutations": nperm,
                "period_grid_points": ngrid,
                "period_min_days": nullcal.P_MIN,
                "period_max_days": nullcal.P_MAX,
                "reference_period_days": nullcal.P_REF,
                "reference_log_tolerance": nullcal.LOG_TOL,
                "rng_seed": SEED,
                "permutation_p_value": "(1 + exceedances) / (1 + permutations)",
                "permutation_scope": (
                    "nominal conditional probabilities assuming exchangeable fitted "
                    "base-model residuals; heteroskedasticity/leverage and the choice of "
                    "epoch screen are not included in the null calibration"
                ),
            },
            "source": {
                "path": source_label,
                "sha256": sha256_file(path),
                "orders": [int(order) for order in orders],
            },
            "implementation": {
                "files": {
                    str(source.relative_to(ROOT)).replace("\\", "/"): sha256_file(source)
                    for source in IMPLEMENTATION_FILES
                },
                "python": sys.version.split()[0],
                "numpy": np.__version__,
            },
            "internal_screen": {
                "rule": "nightly across-order spread > 3 * median nightly spread",
                "n_all": len(t),
                "n_dropped": int(bad.sum()),
                "threshold_m_per_s": threshold,
                "dropped_bjd": t[bad],
                "dropped_spread_m_per_s": spread[bad],
            },
            "variants": variants,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", nargs="?", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--nperm", type=int, default=5000)
    parser.add_argument("--grid", type=int, default=4000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = run_audit(args.series.resolve(), nperm=args.nperm, ngrid=args.grid)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
