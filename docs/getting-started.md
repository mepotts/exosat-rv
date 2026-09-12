# Getting started

## Install from source

Follow the [README quickstart](../README.md#quickstart). The base package requires Python
3.11 or newer. The `dev` extra adds tests and linting; optional scientific scripts need:

```bash
python -m pip install -e ".[dev,science]"
```

The `photometry` extra is needed only for live ASAS-SN refetching; the retained photometry
audit uses cached inputs. CR2RES, VIPER, and their calibration resources are external to
this package. The [historical runbook](viper-runbook.md) is not a one-command reproducible
environment and does not authorize new target processing.

## Verify retained evidence

Run from the repository root after installing the source checkout:

```bash
exosat-rv --help
python scripts/m37_package_evidence.py --verify
python scripts/m37_render_results.py --check
python -m pytest -m "not network"
```

`--help` is an installation smoke test. The two script checks verify evidence integrity and
the generated M37 report against committed artifacts, respectively. They do not rerun the
extraction or the Monte Carlo audit. Tests create temporary/cache files but do not require
live archive access when the `network` marker is excluded. Some offline numerical tests take
longer than a CLI smoke test.

## Replay the downstream audit

Recompute the M37 complete-versus-screened period search from the bundled extracted RVs:

```bash
python scripts/m37_reaudit.py --output build/replay/m37-cd35-reaudit.json
```

This uses the full default permutation count and grid, so allow time for the calculation.
It creates `build/replay/` and writes a new result there rather than replacing the committed
audit artifact. Compare its `variants`, `internal_screen`, and `method` fields with
`data/m37-cd35-reaudit.json`; execution-version metadata and floating-point results may differ
across numerical environments. Lowering `--nperm` or `--grid` is useful for engineering tests
but does **not** reproduce the reported audit.

This calculation starts from measured RV/per-order tables. It does not re-extract raw spectra,
hold published information out of historical development, or repair the statistical cost of
choosing the internal screen. Read [M37](milestones/M37-RESULTS.md) alongside its output.

## Package and data paths

An editable source install uses the checkout's `data/`. An installed wheel defaults to
`data/` below the caller's working directory and does not include research tables or scripts.
Set `EXOSAT_DATA_DIR` **before launching the CLI** to choose another directory. It controls
both inputs and generated CLI reports, not a read-only resource location. Historical scripts
can have their own input/output rules; inspect each driver rather than assuming the CLI
override applies to all scripts.

## Other CLI commands

These are research operations, not installation tests. Archive commands contact external
services, may download products, and may write reports. Inspect each command's `--help` and
the corresponding milestone first.

| Command | Research role |
|---|---|
| `exosat-rv inventory`, `probe` | Archive holdings and reduced-product inspection |
| `exosat-rv targets`, `survey`, `closein` | Companion selection and feasibility calculations |
| `exosat-rv alias`, `orbits` | Historical analyses of the **published comparison RVs**, not a new spectral extraction |
| `exosat-rv orders` | Historical per-order diagnostics |
| `exosat-rv gravity` | VLTI/GRAVITY archive inventory |

See the [script guide](../scripts/README.md) for work beyond this early CLI layer. New M38
development has separate [validation boundaries](validation.md); the historical replay above
is not an M38 target experiment.
