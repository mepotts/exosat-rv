# Research scripts

These are source-checkout tools, not all installed CLI commands. Run Python drivers from the
repository root after installing the package. Check the relevant milestone and the driver's
inputs/outputs before executing it; many historical scripts contact archives or modify an
external reduction/VIPER working directory.

## Entry points

| Task | Driver | Scope |
|---|---|---|
| Verify frozen evidence | `python scripts/m37_package_evidence.py --verify` | Offline hash verification, no repackaging |
| Check audit tables | `python scripts/m37_render_results.py --check` | Compare rendered numbers with retained JSON |
| Recompute downstream audit | `python scripts/m37_reaudit.py --output build/replay/m37-cd35-reaudit.json` | Bundled RVs; writes new output, not raw extraction |
| Check synthetic coverage report | [Coverage replay commands](../docs/milestones/M38-SELECTION-COVERAGE-PILOT.md) | Retained response-level simulation evidence |
| Check Gaussian benchmark report | [Benchmark replay commands](../docs/milestones/M38-INTERVAL-BENCHMARK.md) | Retained exact-reference benchmark evidence |
| Check heterogeneous-interval ledger | [Stress-study replay commands](../docs/milestones/M38-HETEROGENEOUS-INTERVALS.md) | Response-level checks and selected trial replays |
| Run/check actual VIPER synthetic probe | [Bridge commands and prerequisites](../docs/milestones/M38-VIPER-SYNTHETIC-BRIDGE.md) | Generated spectra only; external source required for fitting, not report checking |
| Build manuscript preview | `python scripts/m16_build_paper.py` | Writes generated draft HTML |
| Build supporting note previews | `python scripts/m33_render_notes.py` | Writes generated note HTML |

The linked renderer commands require explicit `--result`, `--document`, and `--check`
arguments. Run from the repo root with the source package installed. A check against
retained JSON is not a fresh simulation or extraction.
Refer to [Getting started](../docs/getting-started.md) for dependencies and replay details.

## Historical campaigns versus current development

- [cr2res/](cr2res/): instrument build, download, staging, and reduction scripts, including
  target-specific campaigns. Not a generic safe batch to launch unchanged.
- [injection/](injection/): historical VIPER runs, template-stage work, fitter-stage injection
  tests, and target/published-RV comparisons. The name does **not** mean every file implements
  an independent or pre-template injection. M36's runner intentionally remains dry-run only.
- `m*_*.py` and `m*_*.sh`: milestone-specific drivers and renderers. Numbers identify research
  history, not an execution sequence. Consult [milestones](../docs/milestones/README.md).
- `m38_*.py`: generic synthetic development and reporting. Read the individual experiment
  plan and [M38 boundaries](../docs/validation.md); do not treat a simulation as authority to
  run a target or select production settings.

Existing paths are retained for imports, run provenance, and manuscript builders. New reusable
logic belongs in `src/exosat_rv/`; new drivers belong here with tests and an explicit evidence
record. Do not run cleanup/restore scripts merely because they exist in this archive.
