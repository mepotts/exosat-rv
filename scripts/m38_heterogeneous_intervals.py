"""Synthetic response-only interval stress: no target, selection, or method adoption.

Uses actual production scoring/bootstrap. Known-covariance normal intervals are
exact only for Gaussian errors. The block-mean t interval is exact only for iid
Gaussian block slopes and deliberately has a different center in stressed cases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import binomtest, norm, t

from exosat_rv.m38 import provenance, selection


def source_hashes():
    return {
        name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for name, module in (("selection", selection), ("provenance", provenance))
    } | {"driver": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


LOADED_HASHES = source_hashes()
METHODS = ("known-covariance-normal", "unweighted-block-t", "production-block-percentile")


def validate_plan(plan):
    if plan["schema"] != "m38-heterogeneous-intervals-plan-v1":
        raise ValueError("unsupported schema")
    for key in ("master_seed", "trials_per_case", "bootstrap_repetitions", "order_count"):
        if type(plan[key]) is not int or plan[key] < (0 if key == "master_seed" else 2):
            raise ValueError(f"invalid {key}")
    for key in ("confidence_level", "monte_carlo_confidence_level"):
        if type(plan[key]) not in (int, float) or not 0 < plan[key] < 1:
            raise ValueError(f"invalid {key}")
    for key in ("slope_sd", "offset_sd_m_s", "order_noise_sd_m_s"):
        if type(plan[key]) not in (int, float) or not np.isfinite(plan[key]) or plan[key] <= 0:
            raise ValueError(f"invalid {key}")
    if type(plan["true_slope"]) not in (int, float) or not np.isfinite(plan["true_slope"]):
        raise ValueError("invalid truth")
    if plan["scale_exponents"] != {"slope": 1.0, "offset": 0.0, "order_noise": 0.5}:
        raise ValueError("require explicit supported scale exponents")
    if not isinstance(plan["cases"], list) or not plan["cases"]:
        raise ValueError("cases required")
    ids = set()
    for case in plan["cases"]:
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in ids:
            raise ValueError("invalid case identity")
        ids.add(case["id"])
        sizes, scales, velocities = (
            case[k] for k in ("block_sizes", "block_scales", "velocities_m_s")
        )
        if not isinstance(sizes, list) or len(sizes) < 2:
            raise ValueError("at least two independent blocks required")
        if any(type(n) is not int or n < 1 for n in sizes):
            raise ValueError("invalid block size")
        if len(scales) != len(sizes) or any(
            type(s) not in (int, float) or not np.isfinite(s) or s <= 0 for s in scales
        ):
            raise ValueError("invalid block scales")
        if (
            not isinstance(velocities, list)
            or len(velocities) < 2
            or any(type(v) not in (int, float) or not np.isfinite(v) for v in velocities)
        ):
            raise ValueError("invalid injection bank")
        if len(set(velocities)) != len(velocities):
            raise ValueError("distinct injection velocities required")
        if case["noise"] not in ("gaussian", "standardized-t5"):
            raise ValueError("unsupported noise")


def seed_for(plan, case, trial, domain):
    return int(
        provenance.canonical_sha256({"plan": plan, "case": case, "trial": trial, "domain": domain})[
            :16
        ],
        16,
    )


def geometry(plan, case):
    """WLS slope coefficients and true block covariance projection; no data needed."""
    block = np.repeat(np.arange(len(case["block_sizes"])), case["block_sizes"])
    scale = np.asarray(case["block_scales"])[block]
    x = np.broadcast_to(case["velocities_m_s"], (len(block), len(case["velocities_m_s"])))
    tau = plan["slope_sd"] * scale
    omega = np.full(len(block), plan["offset_sd_m_s"])
    sigma = plan["order_noise_sd_m_s"] * np.sqrt(scale)
    uncertainty = np.sqrt((tau[:, None] * x) ** 2 + omega[:, None] ** 2 + sigma[:, None] ** 2)
    design = np.column_stack((np.ones(x.size), x.ravel()))
    w = uncertainty.ravel() ** -2
    coefficient = np.linalg.solve(design.T @ (w[:, None] * design), design.T * w)[1]
    c = coefficient.reshape(x.shape)
    slope_load = np.asarray(
        [
            np.sum(c[block == g] * x[block == g] * tau[block == g, None])
            for g in range(len(case["block_sizes"]))
        ]
    )
    offset_load = np.asarray(
        [np.sum(c[block == g] * omega[block == g, None]) for g in range(len(case["block_sizes"]))]
    )
    variance = float(
        np.sum(slope_load**2 + offset_load**2)
        + np.sum(c**2 * sigma[:, None] ** 2) / plan["order_count"]
    )
    return block, x, uncertainty, tau, omega, sigma, c, variance


def generate(plan, case, seed):
    block, x, uncertainty, tau, omega, sigma, _, _ = geometry(plan, case)
    rng = np.random.default_rng(seed)

    def noise(shape):
        if case["noise"] == "gaussian":
            return rng.normal(size=shape)
        return rng.standard_t(5, size=shape) * np.sqrt(3 / 5)

    n, orders = len(block), plan["order_count"]
    groups = len(case["block_sizes"])
    slope, offset = noise(groups)[block] * tau, noise(groups)[block] * omega
    epochs, order_ids = (
        tuple(f"night-{i}" for i in range(n)),
        tuple(f"order-{i}" for i in range(orders)),
    )
    mask = np.ones((n, orders), dtype=bool)
    reference = selection.ReferenceResponse(
        epochs,
        tuple(f"block-{g}" for g in block),
        order_ids,
        np.zeros((n, orders)),
        np.ones((n, orders)),
        mask,
    )
    injections, responses = [], []
    for j in range(x.shape[1]):
        injection = selection.InjectionPlan(f"injection-{j}", epochs, x[:, j].copy())
        rv = ((plan["true_slope"] + slope) * x[:, j] + offset)[:, None]
        rv = rv + noise((n, orders)) * sigma[:, None]
        paired = np.broadcast_to(uncertainty[:, j, None], (n, orders)).copy()
        injections.append(injection)
        responses.append(
            selection.InjectedResponse(
                injection.injection_id,
                epochs,
                order_ids,
                rv,
                np.ones((n, orders)),
                paired,
                mask.copy(),
            )
        )
    return reference, tuple(injections), tuple(responses)


def interval(lower, upper, truth):
    if (lower is None) != (upper is None):
        raise ValueError("inconsistent missing endpoints")
    complete = lower is not None
    if complete and (not np.isfinite([lower, upper]).all() or lower > upper):
        raise ValueError("invalid interval")
    return {
        "lower": lower,
        "upper": upper,
        "complete": complete,
        "covered": bool(complete and lower <= truth <= upper),
        "width": float(upper - lower) if complete else None,
    }


def run_trial(plan, case, trial):
    data_seed = seed_for(plan, case, trial, "response-noise")
    bootstrap_seed = seed_for(plan, case, trial, "bootstrap")
    reference, injections, responses = generate(plan, case, data_seed)
    block, x, uncertainty, _, _, _, coefficient, variance = geometry(plan, case)
    y = np.column_stack([np.mean(r.rv, axis=1) for r in responses])
    policy = selection.AttritionPolicy(
        plan["order_count"], plan["order_count"], 0, 0.0, "fail_primary"
    )
    score = selection.score_injection_responses(reference, injections, responses, policy)
    estimate = selection.estimate_recovery_slope(
        score,
        seed=bootstrap_seed,
        repetitions=plan["bootstrap_repetitions"],
        confidence_level=plan["confidence_level"],
        minimum_independent_clusters=2,
    )
    center = float(np.sum(coefficient * y))
    if estimate.slope is not None and not np.isclose(
        estimate.slope, center, rtol=1e-10, atol=1e-12
    ):
        raise ValueError("matrix projection disagrees with production slope")
    block_slopes = np.asarray(
        [
            selection._fit_line(
                x[block == g].ravel(), y[block == g].ravel(), uncertainty[block == g].ravel()
            )[1]
            for g in range(len(case["block_sizes"]))
        ]
    )
    probability = (1 + plan["confidence_level"]) / 2
    normal_half = float(norm.ppf(probability) * np.sqrt(variance))
    block_center = float(np.mean(block_slopes))
    block_half = float(
        t.ppf(probability, len(block_slopes) - 1)
        * np.std(block_slopes, ddof=1)
        / np.sqrt(len(block_slopes))
    )
    truth = plan["true_slope"]
    return {
        "trial": trial,
        "data_seed": data_seed,
        "bootstrap_seed": bootstrap_seed,
        "score_sha256": score.score_id,
        "production_slope": estimate.slope,
        "projected_slope": center,
        "block_slopes": block_slopes.tolist(),
        "block_mean_slope": block_center,
        "oracle_variance": variance,
        "bootstrap_failure_reason": estimate.fit_failure_reason,
        "failed_bootstrap_repetitions": len(estimate.failures)
        if estimate.fit_failure_reason is None
        else 0,
        "unrun_bootstrap_repetitions": plan["bootstrap_repetitions"]
        if estimate.fit_failure_reason is not None
        else 0,
        "intervals": {
            METHODS[0]: interval(center - normal_half, center + normal_half, truth),
            METHODS[1]: interval(block_center - block_half, block_center + block_half, truth),
            METHODS[2]: interval(estimate.confidence_lower, estimate.confidence_upper, truth),
        },
    }


def summarize(plan, records):
    output = {}
    for method in METHODS:
        entries = [r["intervals"][method] for r in records]
        count = sum(e["covered"] for e in entries)
        bounds = binomtest(count, len(entries)).proportion_ci(
            plan["monte_carlo_confidence_level"], method="exact"
        )
        widths = [e["width"] for e in entries if e["complete"]]
        output[method] = {
            "covered": count,
            "complete": len(widths),
            "planned": len(entries),
            "coverage": count / len(entries),
            "mc_lower": float(bounds.low),
            "mc_upper": float(bounds.high),
            "mean_complete_width": float(np.mean(widths)) if widths else None,
        }
    output["centers"] = {
        "mean_production": float(np.mean([r["projected_slope"] for r in records])),
        "mean_block": float(np.mean([r["block_mean_slope"] for r in records])),
        "production_sample_variance": float(
            np.var([r["projected_slope"] for r in records], ddof=1)
        ),
    }
    return output


def run_study(plan, progress=False):
    validate_plan(plan)
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed since import")
    cases = []
    for case in plan["cases"]:
        records = []
        for i in range(plan["trials_per_case"]):
            records.append(run_trial(plan, case, i))
            if progress and (i + 1) % 100 == 0:
                print(f"{case['id']}: {i + 1}/{plan['trials_per_case']}", flush=True)
        cases.append({"case": case, "trials": records, "summary": summarize(plan, records)})
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed during study")
    return {
        "schema": "m38-heterogeneous-intervals-result-v1",
        "plan": plan,
        "plan_sha256": provenance.canonical_sha256(plan),
        "source_sha256": LOADED_HASHES,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "scope": "synthetic response-only diagnostic; no method adoption or target access",
        "cases": cases,
    }


def assert_close(actual, expected):
    """Exact structures/counts and roundoff-tolerant floating point replay."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError("mapping mismatch")
        for key in expected:
            assert_close(actual[key], expected[key])
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError("list mismatch")
        for a, e in zip(actual, expected, strict=True):
            assert_close(a, e)
    elif type(expected) is float:
        if type(actual) not in (float, int) or not np.isclose(
            actual, expected, rtol=1e-10, atol=1e-12
        ):
            raise ValueError("numeric mismatch")
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError("exact value mismatch")


def validate_result(result, replay=False):
    plan = result["plan"]
    validate_plan(plan)
    assert_close(result["schema"], "m38-heterogeneous-intervals-result-v1")
    assert_close(result["plan_sha256"], provenance.canonical_sha256(plan))
    assert_close(result["source_sha256"], source_hashes())
    if len(result["cases"]) != len(plan["cases"]):
        raise ValueError("case roster mismatch")
    for case, retained in zip(plan["cases"], result["cases"], strict=True):
        assert_close(retained["case"], case)
        rows = retained["trials"]
        if len(rows) != plan["trials_per_case"]:
            raise ValueError("incomplete trial roster")
        variance = geometry(plan, case)[-1]
        probability = (1 + plan["confidence_level"]) / 2
        for i, row in enumerate(rows):
            assert_close(row["trial"], i)
            for key, domain in (("data_seed", "response-noise"), ("bootstrap_seed", "bootstrap")):
                assert_close(row[key], seed_for(plan, case, i, domain))
            if list(row["intervals"]) != list(METHODS):
                raise ValueError("method roster mismatch")
            for entry in row["intervals"].values():
                assert_close(entry, interval(entry["lower"], entry["upper"], plan["true_slope"]))
            assert_close(row["oracle_variance"], variance)
            center = row["projected_slope"]
            half = float(norm.ppf(probability) * np.sqrt(variance))
            assert_close(
                row["intervals"][METHODS[0]],
                interval(center - half, center + half, plan["true_slope"]),
            )
            slopes = row["block_slopes"]
            if len(slopes) != len(case["block_sizes"]):
                raise ValueError("block roster mismatch")
            block_center = float(np.mean(slopes))
            block_half = float(
                t.ppf(probability, len(slopes) - 1) * np.std(slopes, ddof=1) / np.sqrt(len(slopes))
            )
            assert_close(row["block_mean_slope"], block_center)
            assert_close(
                row["intervals"][METHODS[1]],
                interval(block_center - block_half, block_center + block_half, plan["true_slope"]),
            )
            if row["production_slope"] is not None:
                assert_close(row["production_slope"], center)
            for key in ("failed_bootstrap_repetitions", "unrun_bootstrap_repetitions"):
                if type(row[key]) is not int or not 0 <= row[key] <= plan["bootstrap_repetitions"]:
                    raise ValueError("invalid failure accounting")
            if replay and i in (0, len(rows) // 2, len(rows) - 1):
                assert_close(row, run_trial(plan, case, i))
        assert_close(retained["summary"], summarize(plan, rows))


def render_table(result):
    validate_result(result)
    lines = [
        "| Case | Method | Complete/planned | Coverage % [pointwise MC interval] | Mean width |",
        "|---|---|---:|---:|---:|",
    ]
    for cell in result["cases"]:
        for method in METHODS:
            s = cell["summary"][method]
            width = (
                "absent" if s["mean_complete_width"] is None else f"{s['mean_complete_width']:.5f}"
            )
            lines.append(
                f"| {cell['case']['id']} | {method} | {s['complete']}/{s['planned']} | "
                f"{100 * s['coverage']:.1f} "
                f"[{100 * s['mc_lower']:.1f}, {100 * s['mc_upper']:.1f}] | {width} |"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", type=Path)
    group.add_argument(
        "--check", type=Path, help="validate retained ledger and replay three trials per case"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.check:
        result = json.loads(args.check.read_text(encoding="utf-8"))
        validate_result(result, replay=True)
        print(render_table(result))
        return
    if args.output is None or args.output.exists():
        parser.error("require a new output path")
    result = run_study(json.loads(args.plan.read_text(encoding="utf-8")), progress=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(render_table(result))


if __name__ == "__main__":
    main()
