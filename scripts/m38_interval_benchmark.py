"""Paired, target-free comparison with exact Gaussian response-level benchmarks.

Reuses the pilot generator and production scorer/bootstrap. Exact benchmarks are
restricted to homogeneous, equal-sized independent Gaussian blocks. They are not
production estimators and do not validate spectra, estimated errors, or selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import chi2, norm, t
from scripts import m38_selection_coverage as pilot

from exosat_rv.m38 import provenance, selection


def source_hashes():
    paths = {
        "benchmark": __file__,
        "generator": pilot.__file__,
        "selection": selection.__file__,
        "provenance": provenance.__file__,
    }
    return {key: hashlib.sha256(Path(path).read_bytes()).hexdigest() for key, path in paths.items()}


LOADED_HASHES = source_hashes()


def generator_plan(plan):
    """Explicit input adapter to the unchanged, already audited response generator."""
    return {
        "schema": "m38-selection-coverage-pilot-v1",
        "master_seed": plan["master_seed"],
        "trials_per_cell": plan["trials_per_case"],
        "bootstrap_repetitions": min(plan["bootstrap_repetitions"]),
        "confidence_level": plan["confidence_level"],
        "monte_carlo_confidence_level": plan["monte_carlo_confidence_level"],
        "equivalence_delta": 0.2,  # Required by pilot schema; no equivalence test is run here.
        "minimum_independent_clusters": plan["minimum_independent_clusters"],
        "true_slopes": [plan["true_slope"]],
        **{
            key: plan[key]
            for key in (
                "injected_velocities_m_s",
                "order_count",
                "night_slope_sd",
                "night_offset_sd_m_s",
                "order_noise_sd_m_s",
            )
        },
        "scenarios": [generator_case(case) for case in plan["cases"]],
    }


def generator_case(case):
    return {
        "id": case["id"],
        "nights": case["nights"],
        "noise": case["noise"],
        "cluster": "night",
        "attrition": False,
    }


def validate_plan(plan):
    if plan["schema"] != "m38-interval-benchmark-plan-v1":
        raise ValueError("unsupported benchmark schema")
    repetitions = plan["bootstrap_repetitions"]
    if (
        not isinstance(repetitions, list)
        or len(repetitions) != 2
        or any(type(x) is not int or x < 2 for x in repetitions)
        or repetitions != sorted(set(repetitions))
    ):
        raise ValueError("require two increasing bootstrap repetition counts")
    pilot.validate_plan(generator_plan(plan))
    if plan["trials_per_case"] < 2:
        raise ValueError("at least two trials required for variance diagnostic")
    for case in plan["cases"]:
        if case["noise"] not in ("independent", "season"):
            raise ValueError("exact benchmark requires homogeneous Gaussian blocks")
        labels = ["night"] if case["noise"] == "independent" else ["night", "season"]
        if case["bootstrap_labels"] != labels:
            raise ValueError("exact ordered bootstrap-label roster required")


def seed_for(plan, case, trial, domain):
    return int(
        provenance.canonical_sha256({"plan": plan, "case": case, "trial": trial, "domain": domain})[
            :16
        ],
        16,
    )


def oracle_variance(plan, case):
    """Known covariance, reduced analytically using the symmetric injection bank.

    Let c_j=w_j*x_j/sum(w_j*x_j^2). The global WLS slope is the mean
    night slope. Its variance is tau^2/G + sigma^2/O * sum(c_j^2)/n.
    G is the TRUE independent block count, never the supplied bootstrap labels.
    """
    if case["noise"] not in ("independent", "season"):
        raise ValueError("homogeneous noise only")
    n = case["nights"]
    if case["noise"] == "season" and n % 4:
        raise ValueError("equal complete blocks required")
    x = np.asarray(plan["injected_velocities_m_s"], dtype=float)
    if set(x) != set(-x):
        raise ValueError("symmetric bank required for offset cancellation")
    tau, omega, sigma = (
        plan[k] for k in ("night_slope_sd", "night_offset_sd_m_s", "order_noise_sd_m_s")
    )
    w = 1 / ((tau * x) ** 2 + omega**2 + sigma**2)
    c = w * x / np.sum(w * x * x)
    blocks = n // 4 if case["noise"] == "season" else n
    return float(tau * tau / blocks + sigma * sigma / plan["order_count"] * np.sum(c * c) / n)


def block_slopes(reference, injections, responses, block_size):
    """Use the reference WLS computation for each truly independent block."""
    x = np.column_stack([p.velocities for p in injections])
    y = np.column_stack([np.mean(r.rv - reference.rv, axis=1) for r in responses])
    error = np.column_stack([np.mean(r.response_uncertainty, axis=1) for r in responses])
    values = []
    for start in range(0, len(reference.epoch_ids), block_size):
        block = slice(start, start + block_size)
        _, slope = selection._fit_line(x[block].ravel(), y[block].ravel(), error[block].ravel())
        values.append(slope)
    return np.asarray(values)


def interval_record(lower, upper, truth, *, failed=0, unrun=0):
    complete = lower is not None and upper is not None
    if complete and (not math.isfinite(lower) or not math.isfinite(upper) or lower > upper):
        raise ValueError("invalid interval")
    return {
        "lower": lower,
        "upper": upper,
        "complete": complete,
        "covered": bool(complete and lower <= truth <= upper),
        "width": float(upper - lower) if complete else None,
        "failed_bootstrap_repetitions": failed,
        "unrun_bootstrap_repetitions": unrun,
    }


def run_trial(plan, case, trial):
    data_seed = seed_for(plan, case, trial, "response-noise")
    ref, injections, responses = pilot.generate_response_trial(
        generator_plan(plan), generator_case(case), plan["true_slope"], data_seed
    )
    independent_size = 4 if case["noise"] == "season" else 1
    blocks = block_slopes(ref, injections, responses, independent_size)
    center = float(np.mean(blocks))
    truth = plan["true_slope"]
    variance = oracle_variance(plan, case)
    probability = (1 + plan["confidence_level"]) / 2
    oracle_half = float(norm.ppf(probability) * np.sqrt(variance))
    t_half = float(
        t.ppf(probability, len(blocks) - 1) * np.std(blocks, ddof=1) / np.sqrt(len(blocks))
    )
    intervals = {
        "oracle-normal": interval_record(center - oracle_half, center + oracle_half, truth),
        "independent-block-t": interval_record(center - t_half, center + t_half, truth),
    }
    score_ids, bootstrap_seeds = {}, {}
    for label in case["bootstrap_labels"]:
        labeled = replace(
            ref,
            cluster_ids=tuple(
                f"cluster-{i // 4 if label == 'season' else i}" for i in range(len(ref.epoch_ids))
            ),
        )
        policy = selection.AttritionPolicy(
            plan["order_count"], plan["order_count"], 0, 0.0, "fail_primary"
        )
        score = selection.score_injection_responses(labeled, injections, responses, policy)
        score_ids[label] = score.score_id
        bootstrap_seed = seed_for(plan, case, trial, f"bootstrap-{label}")
        bootstrap_seeds[label] = bootstrap_seed
        previous = None
        for repetitions in plan["bootstrap_repetitions"]:
            estimate = selection.estimate_recovery_slope(
                score,
                seed=bootstrap_seed,
                repetitions=repetitions,
                confidence_level=plan["confidence_level"],
                minimum_independent_clusters=plan["minimum_independent_clusters"],
            )
            if estimate.slope is not None and not np.isclose(
                estimate.slope, center, rtol=1e-11, atol=1e-12
            ):
                raise ValueError("block mean and production point estimate disagree")
            if previous is not None:
                k = previous.requested_repetitions
                if previous.cluster_draws != estimate.cluster_draws[:k]:
                    raise ValueError("bootstrap draws are not prefix paired")
                if not np.array_equal(
                    previous.bootstrap_slopes, estimate.bootstrap_slopes[:k], equal_nan=True
                ):
                    raise ValueError("bootstrap statistics are not prefix paired")
            previous = estimate
            intervals[f"percentile-{label}-{repetitions}"] = interval_record(
                estimate.confidence_lower,
                estimate.confidence_upper,
                truth,
                failed=len(estimate.failures) if estimate.fit_failure_reason is None else 0,
                unrun=repetitions if estimate.fit_failure_reason is not None else 0,
            )
    return {
        "trial": trial,
        "data_seed": data_seed,
        "bootstrap_seeds": bootstrap_seeds,
        "score_sha256": score_ids,
        "slope": center,
        "independent_block_slopes": blocks.tolist(),
        "prefix_pairing_verified": True,
        "intervals": intervals,
    }


def summarize(plan, case, records):
    n = len(records)
    confidence = plan["monte_carlo_confidence_level"]
    methods = list(records[0]["intervals"])
    if any(list(row["intervals"]) != methods for row in records):
        raise ValueError("method roster changed")
    rates = {}
    for method in methods:
        values = [row["intervals"][method] for row in records]
        widths = [v["width"] for v in values if v["complete"]]
        rates[method] = {
            "coverage_all_planned": pilot.binomial_summary(
                sum(v["covered"] for v in values), n, confidence
            ),
            "complete": sum(v["complete"] for v in values),
            "mean_width_given_complete": float(np.mean(widths)) if widths else None,
        }
    comparisons = []
    pairs = [
        (
            f"percentile-{label}-{plan['bootstrap_repetitions'][0]}",
            f"percentile-{label}-{plan['bootstrap_repetitions'][1]}",
        )
        for label in case["bootstrap_labels"]
    ]
    if case["noise"] == "season":
        pairs.append(
            (
                f"percentile-night-{plan['bootstrap_repetitions'][-1]}",
                f"percentile-season-{plan['bootstrap_repetitions'][-1]}",
            )
        )
    for first, second in pairs:
        counts = {"00": 0, "01": 0, "10": 0, "11": 0}
        for row in records:
            key = "".join(str(int(row["intervals"][name]["covered"])) for name in (first, second))
            counts[key] += 1
        comparisons.append(
            {
                "first": first,
                "second": second,
                "coverage_pairs": counts,
                "second_minus_first": (counts["01"] - counts["10"]) / n,
            }
        )
    slopes = [row["slope"] for row in records]
    variance = oracle_variance(plan, case)
    alpha = (1 - confidence) / 2
    return {
        "methods": rates,
        "paired_comparisons": comparisons,
        "mean_slope": float(np.mean(slopes)),
        "sample_variance_ddof1": float(np.var(slopes, ddof=1)),
        "oracle_variance": variance,
        "sample_to_oracle_variance_ratio": float(np.var(slopes, ddof=1) / variance),
        "variance_ratio_reference_envelope": (
            chi2.ppf([alpha, 1 - alpha], n - 1) / (n - 1)
        ).tolist(),
    }


def run_case(plan, case, progress=False):
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed before case")
    records = []
    for i in range(plan["trials_per_case"]):
        records.append(run_trial(plan, case, i))
        if progress and (i + 1) % 100 == 0:
            print(f"{case['id']}: {i + 1}/{plan['trials_per_case']} independent trials", flush=True)
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed during case")
    return {"case": case, "trials": records, "summary": summarize(plan, case, records)}


def run_study(plan, *, workers=1, progress=False):
    validate_plan(plan)
    if type(workers) is not int or not 1 <= workers <= 2:
        raise ValueError("workers must be 1 or 2")
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed after import")
    if workers == 1:
        cases = [run_case(plan, case, progress) for case in plan["cases"]]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_case, plan, case, progress) for case in plan["cases"]]
            cases = [f.result() for f in futures]
    if source_hashes() != LOADED_HASHES:
        raise RuntimeError("source changed during study")
    return {
        "schema": "m38-interval-benchmark-result-v1",
        "plan": plan,
        "plan_sha256": provenance.canonical_sha256(plan),
        "source_sha256": LOADED_HASHES,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "workers": workers,
        },
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a new path")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    result = run_study(plan, workers=args.workers, progress=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Result written; plan SHA256 {result['plan_sha256']}", flush=True)


if __name__ == "__main__":
    main()
