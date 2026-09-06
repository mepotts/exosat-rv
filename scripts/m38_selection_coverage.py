"""Target-free Monte Carlo stress test of the existing M38 recovery interval.

This is a response-level experiment, not a spectral/full-pipeline injection. The
plan is explicit and report-only: no scenario or threshold is selected by a run.
Each trial calls the production scorer and estimator, not a replacement fit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import binomtest

from exosat_rv.m38 import provenance, selection
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.selection import (
    AttritionPolicy,
    InjectedResponse,
    InjectionPlan,
    ReferenceResponse,
    estimate_recovery_slope,
    score_injection_responses,
)


def _source_hashes() -> dict:
    files = {
        "driver": Path(__file__),
        "selection": Path(selection.__file__),
        "provenance": Path(provenance.__file__),
    }
    return {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}


# Bind the source at module load, not after a potentially long simulation.
_LOADED_SOURCE_HASHES = _source_hashes()


def validate_plan(plan: dict) -> None:
    """Reject ambiguous designs before any simulation is performed."""
    if plan["schema"] != "m38-selection-coverage-pilot-v1":
        raise ValueError("unsupported plan schema")
    for key in (
        "master_seed",
        "trials_per_cell",
        "bootstrap_repetitions",
        "order_count",
        "minimum_independent_clusters",
    ):
        if type(plan[key]) is not int or plan[key] < (0 if key == "master_seed" else 1):
            raise ValueError(f"invalid {key}")
    if plan["minimum_independent_clusters"] < 2:
        raise ValueError("at least two independent clusters required")
    for key in ("confidence_level", "monte_carlo_confidence_level", "equivalence_delta"):
        if type(plan[key]) not in (float, int) or not 0 < plan[key] < 1:
            raise ValueError(f"invalid {key}")
    for key in ("night_slope_sd", "night_offset_sd_m_s", "order_noise_sd_m_s"):
        if type(plan[key]) not in (float, int) or not np.isfinite(plan[key]) or plan[key] <= 0:
            raise ValueError(f"invalid {key}")
    for key in ("true_slopes", "injected_velocities_m_s"):
        values = plan[key]
        if not isinstance(values, list) or not values:
            raise ValueError(f"invalid {key}")
        if any(type(v) not in (float, int) or not np.isfinite(v) for v in values):
            raise ValueError(f"invalid {key}")
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {key}")
    velocities = plan["injected_velocities_m_s"]
    if len(velocities) < 2 or set(velocities) != {-v for v in velocities}:
        raise ValueError("injection bank must contain distinct symmetric velocities")
    scenarios = plan["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios required")
    identifiers = set()
    for scenario in scenarios:
        identifier = scenario["id"]
        if type(identifier) is not str or not identifier or identifier in identifiers:
            raise ValueError("invalid or duplicate scenario identity")
        identifiers.add(identifier)
        n = scenario["nights"]
        if type(n) is not int or n < 4:
            raise ValueError("at least four nights required")
        if scenario["noise"] not in ("independent", "heterogeneous", "season"):
            raise ValueError("unknown noise model")
        if scenario["cluster"] not in ("night", "season"):
            raise ValueError("unknown cluster model")
        if scenario["noise"] == "season" or scenario["cluster"] == "season":
            if n % 4 or n < 8:
                raise ValueError("season models require complete four-night blocks")
        if type(scenario["attrition"]) is not bool:
            raise ValueError("attrition must be boolean")


def trial_seed(plan: dict, scenario: dict, truth: float, trial: int, domain: str) -> int:
    """Content-bound, separate simulation/bootstrap streams for every cell and trial."""
    payload = {"plan": plan, "scenario": scenario, "truth": truth, "trial": trial, "domain": domain}
    return int(canonical_sha256(payload)[:16], 16)


def generate_response_trial(plan: dict, scenario: dict, truth: float, seed: int):
    """Generate exact-mean linear responses with known correlated random slopes.

    y[j,e,o] = (truth + slope_error[e]) * x[j] + offset[e] + epsilon[j,e,o].
    Slope/offset errors are shared across injections and orders; season noise shares
    them across consecutive groups of four nights. Heterogeneous noise multiplies
    both by a deterministic geometric scale spanning 0.4 to 2.5. Per-order paired
    uncertainties are the exact marginal SD, not a guessed fitted error bar.
    """
    rng = np.random.default_rng(seed)
    n, orders = scenario["nights"], plan["order_count"]
    shape = (n, orders)
    epochs = tuple(f"night-{i}" for i in range(n))
    cluster = tuple(f"cluster-{i // 4 if scenario['cluster'] == 'season' else i}" for i in range(n))
    reference = ReferenceResponse(
        epoch_ids=epochs,
        cluster_ids=cluster,
        order_ids=tuple(f"order-{i}" for i in range(orders)),
        rv=np.zeros(shape),
        uncertainty=np.ones(shape),
        valid_mask=np.ones(shape, dtype=bool),
    )
    independent_units = n // 4 if scenario["noise"] == "season" else n
    slope_error = rng.normal(size=independent_units)
    offset = rng.normal(size=independent_units)
    if scenario["noise"] == "season":
        slope_error, offset = np.repeat(slope_error, 4), np.repeat(offset, 4)
    scale = np.geomspace(0.4, 2.5, n) if scenario["noise"] == "heterogeneous" else np.ones(n)
    slope_sd = plan["night_slope_sd"] * scale
    offset_sd = plan["night_offset_sd_m_s"] * scale
    slope_error *= slope_sd
    offset *= offset_sd
    plans, responses = [], []
    for j, velocity in enumerate(plan["injected_velocities_m_s"]):
        injection = InjectionPlan(f"injection-{j}", epochs, np.full(n, velocity))
        noise = rng.normal(0, plan["order_noise_sd_m_s"], size=shape)
        rv = ((truth + slope_error) * velocity + offset)[:, None] + noise
        paired = np.broadcast_to(
            np.sqrt((slope_sd * velocity) ** 2 + offset_sd**2 + plan["order_noise_sd_m_s"] ** 2)[
                :, None
            ],
            shape,
        ).copy()
        mask = np.ones(shape, dtype=bool)
        if scenario["attrition"]:
            # Deliberately velocity-dependent loss; no favourable surviving subset is fitted.
            probability = 0.005 + 0.035 * abs(velocity) / max(
                abs(v) for v in plan["injected_velocities_m_s"]
            )
            mask = rng.random(shape) >= probability
        rv[~mask], paired[~mask] = np.nan, np.nan
        fit_uncertainty = np.where(mask, 1.0, np.nan)
        plans.append(injection)
        responses.append(
            InjectedResponse(
                injection.injection_id,
                epochs,
                reference.order_ids,
                rv,
                fit_uncertainty,
                paired,
                mask,
            )
        )
    return reference, tuple(plans), tuple(responses)


def run_trial(plan: dict, scenario: dict, truth: float, trial: int) -> dict:
    data_seed = trial_seed(plan, scenario, truth, trial, "response-noise")
    bootstrap_seed = trial_seed(plan, scenario, truth, trial, "cluster-bootstrap")
    reference, injections, responses = generate_response_trial(plan, scenario, truth, data_seed)
    policy = AttritionPolicy(plan["order_count"], plan["order_count"], 0, 0.0, "fail_primary")
    score = score_injection_responses(reference, injections, responses, policy)
    estimate = estimate_recovery_slope(
        score,
        seed=bootstrap_seed,
        repetitions=plan["bootstrap_repetitions"],
        confidence_level=plan["confidence_level"],
        minimum_independent_clusters=plan["minimum_independent_clusters"],
    )
    lo, hi = estimate.confidence_lower, estimate.confidence_upper
    complete = estimate.complete
    covered = bool(complete and lo <= truth <= hi)
    passed = bool(
        complete
        and score.attrition_gate_passed
        and lo >= 1 - plan["equivalence_delta"]
        and hi <= 1 + plan["equivalence_delta"]
    )
    # Boundary truths belong to the non-equivalence null, not to successful transmission.
    non_equivalent = (
        truth <= 1 - plan["equivalence_delta"] or truth >= 1 + plan["equivalence_delta"]
    )
    return {
        "trial": trial,
        "data_seed": data_seed,
        "bootstrap_seed": bootstrap_seed,
        "score_sha256": score.score_id,
        "complete": complete,
        "attrition_passed": score.attrition_gate_passed,
        "slope": estimate.slope,
        "lower": lo,
        "upper": hi,
        "covered": covered,
        "interval_gate_passed": passed,
        "false_equivalence": bool(passed) if non_equivalent else None,
        "failed_bootstrap_repetitions": (
            len(estimate.failures) if estimate.fit_failure_reason is None else 0
        ),
        "unrun_bootstrap_repetitions": (
            plan["bootstrap_repetitions"] if estimate.fit_failure_reason is not None else 0
        ),
        "failure_reason": estimate.fit_failure_reason,
    }


def binomial_summary(successes: int, total: int, confidence: float) -> dict:
    if total == 0:
        return {"successes": successes, "total": 0, "rate": None, "lower": None, "upper": None}
    interval = binomtest(successes, total).proportion_ci(confidence, method="exact")
    return {
        "successes": successes,
        "total": total,
        "rate": successes / total,
        "lower": float(interval.low),
        "upper": float(interval.high),
    }


def summarize_trials(records: list[dict], confidence: float) -> dict:
    """Incomplete trials remain in all-planned denominators; conditional coverage is separate."""
    total = len(records)
    complete = sum(r["complete"] for r in records)
    result = {
        key: binomial_summary(sum(r[key] for r in records), total, confidence)
        for key in (
            "complete",
            "attrition_passed",
            "covered",
            "interval_gate_passed",
        )
    }
    false_events = [r["false_equivalence"] for r in records if r["false_equivalence"] is not None]
    result["false_equivalence"] = binomial_summary(sum(false_events), len(false_events), confidence)
    result["coverage_given_complete"] = binomial_summary(
        sum(r["covered"] for r in records), complete, confidence
    )
    return result


def run_study(plan: dict, *, progress=False) -> dict:
    validate_plan(plan)
    if _source_hashes() != _LOADED_SOURCE_HASHES:
        raise RuntimeError("source changed after module load; restart in an unchanged checkout")
    cells = []
    for scenario in plan["scenarios"]:
        for truth in plan["true_slopes"]:
            records = [run_trial(plan, scenario, truth, i) for i in range(plan["trials_per_cell"])]
            cells.append(
                {
                    "scenario": scenario,
                    "true_slope": truth,
                    "trials": records,
                    "summary": summarize_trials(records, plan["monte_carlo_confidence_level"]),
                }
            )
            if progress:
                print(
                    f"Completed {scenario['id']} slope={truth}: {len(records)} trials", flush=True
                )
    if _source_hashes() != _LOADED_SOURCE_HASHES:
        raise RuntimeError("source changed during study; refusing a mislabeled result")
    return {
        "schema": "m38-selection-coverage-result-v1",
        "plan": plan,
        "plan_sha256": canonical_sha256(plan),
        "source_sha256": dict(_LOADED_SOURCE_HASHES),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "scope": "response-level single-arm interval/attrition gates only; not spectral or adaptive-pipeline validation",
        "cells": cells,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a new path to preserve previous evidence")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    result = run_study(plan, progress=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Wrote {args.output}; plan SHA256 {result['plan_sha256']}", flush=True)


if __name__ == "__main__":
    main()
