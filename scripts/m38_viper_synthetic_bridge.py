"""Run a bounded, entirely generated real-VIPER engineering experiment.

Example (external source/runtime is not bundled):
python -m scripts.m38_viper_synthetic_bridge --viper-source /path/to/viper \
    --output /fresh/private/experiment
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np

from exosat_rv.m38.viper_bridge import (
    C_MPS,
    analytic_flux,
    copy_runtime,
    execute_viper,
    native_template,
    sha256,
    synthetic_berv_mps,
    write_synthetic_fits,
)


def arrays_digest(arrays: tuple[np.ndarray, ...]) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        digest.update(np.asarray(array, dtype="<f8").tobytes())
    return digest.hexdigest()


def run_case(
    source: Path,
    output: Path,
    training_velocity: np.ndarray,
    evaluation_velocity: np.ndarray,
    *,
    noise_seed: int = 1847,
    noise_sigma: float = 0.0,
    iterations: int = 3,
) -> dict:
    """One fresh split/chain. Truth arrays never enter template-builder inputs."""
    if iterations < 1 or not np.isfinite(noise_sigma) or noise_sigma < 0:
        raise ValueError("invalid engineering run configuration")
    output.mkdir(parents=True, exist_ok=False)
    manifest = copy_runtime(source, output / "runtime")
    wave = np.linspace(1550.0, 1554.0, 2048)
    berv = synthetic_berv_mps()
    sigma = np.full(wave.size, max(noise_sigma, 1e-4))
    rng = np.random.default_rng(noise_seed)
    for role, velocities in (("training", training_velocity), ("evaluation", evaluation_velocity)):
        inputs = output / role
        inputs.mkdir()
        for index, velocity in enumerate(velocities):
            observed = analytic_flux(wave, float(velocity), berv)
            observed += rng.normal(0, noise_sigma, wave.size)
            write_synthetic_fits(inputs / f"epoch{index:02d}.fits", wave, observed, sigma)
    training_inputs = {path.name: sha256(path) for path in (output / "training").glob("*.fits")}
    history = []
    template = None
    previous_arrays = None
    for iteration in range(iterations + 1):
        step = output / f"build{iteration}"
        fit = execute_viper(output / "runtime", output / "training", step, template, rebuild=True)
        template = step / "fit_tpl.fits"
        arrays = native_template(template)
        change = None
        if previous_arrays is not None:
            if not np.array_equal(arrays[0], previous_arrays[0]):
                raise RuntimeError("native template grid drift")
            valid = np.isfinite(arrays[1])
            if not np.array_equal(valid, np.isfinite(previous_arrays[1])):
                raise RuntimeError("native template mask drift")
            change = float(np.max(np.abs(arrays[1][valid] - previous_arrays[1][valid])))
        history.append(
            {
                "iteration": iteration,
                "template_sha256": sha256(template),
                "native_arrays_sha256": arrays_digest(arrays),
                "max_adjacent_flux_change": change,
                "fit": fit,
            }
        )
        previous_arrays = arrays
    learned = execute_viper(
        output / "runtime", output / "evaluation", output / "heldout", template, rebuild=False
    )
    # Deliberate oracle arm: known rest template for absolute sign/scale comparison.
    # Created only after learned-template products, and never passed to the builder.
    oracle = output / "oracle_tpl.fits"
    write_synthetic_fits(oracle, wave, analytic_flux(wave, 0.0, 0.0), sigma, template=True)
    known = execute_viper(
        output / "runtime", output / "evaluation", output / "known", oracle, rebuild=False
    )
    if training_inputs != {
        path.name: sha256(path) for path in (output / "training").glob("*.fits")
    }:
        raise RuntimeError("training inputs changed during run")
    expected = C_MPS * np.log1p(np.asarray(evaluation_velocity) / C_MPS)
    learned_values = np.array(
        [learned["rows"][f"epoch{i:02d}.fits"]["rv0"] for i in range(len(expected))]
    )
    known_values = np.array(
        [known["rows"][f"epoch{i:02d}.fits"]["rv0"] for i in range(len(expected))]
    )
    return {
        "source_sha256": manifest,
        "synthetic_berv_mps": berv,
        "noise_seed": noise_seed,
        "noise_sigma": noise_sigma,
        "training_velocity_mps": training_velocity.tolist(),
        "evaluation_velocity_mps": evaluation_velocity.tolist(),
        "expected_log_velocity_mps": expected.tolist(),
        "history": history,
        "training_input_sha256": training_inputs,
        "heldout": learned,
        "known": known,
        "learned_minus_expected_mps": (learned_values - expected).tolist(),
        "known_minus_expected_mps": (known_values - expected).tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viper-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--evidence", type=Path, help="Optional fresh retained JSON evidence path")
    parser.add_argument("--single", action="store_true", help="reference engineering smoke only")
    args = parser.parse_args()
    if args.evidence is not None and args.evidence.exists():
        raise ValueError("retained evidence destination must be fresh")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    training = np.array([-300.0, -100.0, 400.0])
    evaluation = np.array([-1200.0, -150.0, 150.0, 1200.0])
    cases = {"reference": (training, evaluation)}
    if not args.single:
        cases.update(
            {
                "zero_repeat": (training, evaluation),
                "positive": (
                    training + [-100.0, 0.0, 100.0],
                    evaluation + [-200.0, -30.0, 30.0, 200.0],
                ),
                "negative": (
                    training - [-100.0, 0.0, 100.0],
                    evaluation - [-200.0, -30.0, 30.0, 200.0],
                ),
                "heldout_perturb": (training, evaluation + [0.0, 0.0, 0.0, 400.0]),
            }
        )
    result = {
        "schema": "m38-viper-generated-engineering-v1",
        "status": "engineering only; no convergence or scientific gate adopted",
        "driver_sha256": sha256(Path(__file__)),
        "bridge_sha256": sha256(Path(__file__).parents[1] / "src/exosat_rv/m38/viper_bridge.py"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "cases": {},
    }
    for name, (train, evaluate) in cases.items():
        print(f"Running generated case {name}", flush=True)
        result["cases"][name] = run_case(
            args.viper_source.resolve(), output / name, train, evaluate, iterations=args.iterations
        )
        (output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if not args.single:
        for seed in (1847, 1848):
            name = f"noise_{seed}"
            print(f"Running generated case {name}", flush=True)
            result["cases"][name] = run_case(
                args.viper_source.resolve(),
                output / name,
                training,
                evaluation,
                noise_seed=seed,
                noise_sigma=1e-4,
                iterations=args.iterations,
            )
            (output / "result.json").write_text(
                json.dumps(result, indent=2, allow_nan=False) + "\n"
            )
    if args.evidence is not None:
        args.evidence.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(output / "result.json")


if __name__ == "__main__":
    main()
