"""Score a generic injection arm.

The score is the slope of ``RV_injected - RV_reference`` on injected velocity.
Injected and reference epoch means are formed from the same intersection of valid
orders. This matters whenever one of the two fits rejects an order.

Usage: ``inject_score2.py ARMNAME REF_RVO [--json]``

The historical text report remains the default. ``--json`` emits full-precision,
machine-readable values for selection scripts and provenance records, including each
epoch's injected velocity, common-valid-order response, per-order differences, and the
injected/reference valid-order sets.
"""

import argparse
import json
import os

import numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PLAN = os.path.join(SP, "inject_plan_big.json")


def rvo_rows(path):
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, []
    hdr = lines[0].split()
    orders = sorted(int(n[2:]) for n in hdr if n.startswith("rv") and n[2:].isdigit())
    out = {}
    for ln in lines[1:]:
        values = ln.split()
        out[values[-1]] = {
            name: float(value) for name, value in zip(hdr[:-1], values[:-1])
        }
    return out, orders


def ok(row, order):
    return (
        np.isfinite(row.get(f"rv{order}", np.nan))
        and np.isfinite(row.get(f"e_rv{order}", np.nan))
        and row[f"e_rv{order}"] > 0
    )


def fit(injected_velocity, recovered_velocity):
    injected_velocity = np.asarray(injected_velocity, float)
    recovered_velocity = np.asarray(recovered_velocity, float)
    good = np.isfinite(injected_velocity) & np.isfinite(recovered_velocity)
    injected_velocity = injected_velocity[good]
    recovered_velocity = recovered_velocity[good]
    if len(injected_velocity) < 4:
        return np.nan, np.nan, np.nan, len(injected_velocity)
    design = np.column_stack([injected_velocity, np.ones_like(injected_velocity)])
    coefficients, *_ = np.linalg.lstsq(design, recovered_velocity, rcond=None)
    residuals = recovered_velocity - design @ coefficients
    covariance = np.linalg.inv(design.T @ design)
    stderr = np.sqrt(
        np.sum(residuals**2) / (len(injected_velocity) - 2) * covariance[0, 0]
    )
    return (
        float(coefficients[0]),
        float(stderr),
        float(residuals.std(ddof=2)),
        len(injected_velocity),
    )


def _finite_or_none(value):
    return float(value) if np.isfinite(value) else None


def score_injections(arm, ref_path, plan, working_dir="."):
    """Return the injection recovery result as JSON-safe Python values."""
    ref, ref_orders = rvo_rows(ref_path)
    if not ref:
        raise ValueError(f"reference RVO has no data rows: {ref_path}")

    injected_velocities = []
    recovered_velocities = []
    per_order = {}
    epoch_details = []

    for index, epoch in enumerate(plan):
        filename = epoch["file"]
        injected_velocity = float(epoch["v"])
        inj_path = os.path.join(working_dir, f"{arm}_inj{index:02d}.rvo.dat")
        detail = {
            "index": index,
            "file": filename,
            "injected_velocity": injected_velocity,
            "injection_valid_orders": [],
            "reference_valid_orders": [],
            "matched_orders": [],
            "orders_lost_in_injection": [],
            "recovered_velocity": None,
            "per_order": [],
        }
        if not os.path.exists(inj_path) or filename not in ref:
            detail["status"] = "missing injection RVO or reference epoch"
            epoch_details.append(detail)
            continue

        inj, inj_orders = rvo_rows(inj_path)
        if not inj:
            detail["status"] = "empty injection RVO"
            epoch_details.append(detail)
            continue

        # Injection RVOs contain one epoch. Prefer the named row when available, while
        # retaining compatibility with old viper outputs whose final path was rewritten.
        inj_row = inj.get(filename)
        if inj_row is None and len(inj) == 1:
            inj_row = next(iter(inj.values()))
        if inj_row is None:
            detail["status"] = "injection epoch not uniquely identifiable"
            epoch_details.append(detail)
            continue

        ref_row = ref[filename]
        injection_valid_orders = [order for order in inj_orders if ok(inj_row, order)]
        reference_valid_orders = [order for order in ref_orders if ok(ref_row, order)]
        common_orders = sorted(set(injection_valid_orders) & set(reference_valid_orders))
        detail["injection_valid_orders"] = injection_valid_orders
        detail["reference_valid_orders"] = reference_valid_orders
        detail["matched_orders"] = common_orders
        detail["orders_lost_in_injection"] = sorted(
            set(reference_valid_orders) - set(injection_valid_orders)
        )
        if not common_orders:
            detail["status"] = "no common valid orders"
            epoch_details.append(detail)
            continue

        # Use one shared mask. Separate means can silently compare different physical
        # orders when either the injected or reference fit rejects an order.
        differences = [
            inj_row[f"rv{order}"] - ref_row[f"rv{order}"] for order in common_orders
        ]
        recovered_velocity = float(np.mean(differences))
        injected_velocities.append(injected_velocity)
        recovered_velocities.append(recovered_velocity)
        detail["recovered_velocity"] = recovered_velocity
        detail["per_order"] = [
            {"order": order, "difference": float(difference)}
            for order, difference in zip(common_orders, differences)
        ]
        detail["status"] = "used"
        epoch_details.append(detail)

        for order, difference in zip(common_orders, differences):
            per_order.setdefault(order, []).append((injected_velocity, difference))

    slope, slope_stderr, residual_rms, n_epochs = fit(
        injected_velocities, recovered_velocities
    )
    order_results = []
    for order in sorted(per_order):
        order_slope, order_stderr, order_rms, order_n = fit(
            [velocity for velocity, _ in per_order[order]],
            [difference for _, difference in per_order[order]],
        )
        order_results.append(
            {
                "order": order,
                "slope": _finite_or_none(order_slope),
                "slope_stderr": _finite_or_none(order_stderr),
                "residual_rms_m_s": _finite_or_none(order_rms),
                "n_epochs": order_n,
            }
        )

    return {
        "schema_version": 1,
        "arm": arm,
        "reference_rvo": os.path.abspath(ref_path),
        "plan_epochs": len(plan),
        "n_epochs": n_epochs,
        "slope": _finite_or_none(slope),
        "slope_stderr": _finite_or_none(slope_stderr),
        "residual_rms_m_s": _finite_or_none(residual_rms),
        "per_order": order_results,
        "epochs": epoch_details,
    }


def print_human(result):
    """Print the legacy, deliberately compact report."""
    slope = result["slope"] if result["slope"] is not None else np.nan
    stderr = result["slope_stderr"] if result["slope_stderr"] is not None else np.nan
    rms = result["residual_rms_m_s"]
    rms = rms if rms is not None else np.nan
    print(
        f"{result['arm']}: n={result['n_epochs']}  recovery={100 * slope:.0f}% "
        f"+- {100 * stderr:.0f}%  resid_rms={rms:.0f} m/s"
    )
    print("per-order recovery (%):")
    for order in result["per_order"]:
        order_slope = order["slope"] if order["slope"] is not None else np.nan
        order_stderr = (
            order["slope_stderr"] if order["slope_stderr"] is not None else np.nan
        )
        order_rms = (
            order["residual_rms_m_s"]
            if order["residual_rms_m_s"] is not None
            else np.nan
        )
        print(
            f"  o={order['order']:2d}: {100 * order_slope:6.0f}% +- "
            f"{100 * order_stderr:3.0f}%  rms={order_rms:6.0f}  "
            f"n={order['n_epochs']}"
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm")
    parser.add_argument("reference_rvo")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--plan", default=DEFAULT_PLAN)
    parser.add_argument("--working-dir", default=".")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    result = score_injections(args.arm, args.reference_rvo, plan, args.working_dir)
    if args.as_json:
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
