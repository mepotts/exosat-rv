# exosat-rv

[![CI](https://github.com/mepotts/exosat-rv/actions/workflows/ci.yml/badge.svg)](https://github.com/mepotts/exosat-rv/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Research software for radial-velocity searches for satellites around directly imaged
planets and brown dwarfs, using public ESO observations.

The main case study is **CD-35 2722 B**. This repository contains a separately implemented
CRIRES+/VIPER extraction workflow, downstream period and orbital analyses, companion-survey
tools, and an auditable record of what those analyses establish—and what they do not.

[Results and limitations](#results-and-limitations) · [Quickstart](#quickstart) ·
[Reproducibility](#reproducibility) · [Documentation](docs/README.md) · [Citation](#citation-and-license)

## Results and limitations

**Current status: a paper-calibrated, conditional reanalysis; not independent confirmation.**
The RVs were measured from spectra, not copied from the publication. However, extraction
choices were calibrated against the published RV series, and the historical search was
target- and paper-aware.

- **CD-35 2722 B:** the reported approximately 171-day signal is recovered on the 17 nights
  retained by an internal quality screen. With all 18 nights, the BERV-adjusted global
  searches are compatible with noise under the audit's nominal permutation calibration.
  Those probabilities assume exchangeable residuals and do not account for choosing the
  screen. This is neither an independent detection nor a refutation of the original paper.
- **η Tel B:** a same-setting nodding transfer case with no detected signal in this analysis.
  Its circular-orbit sensitivity is pointwise and conditional on fitter-stage transmission,
  not an unconditional confidence upper limit or proof of an RV-stable control.
- **Validation remains open:** historical injections start after template construction.
  They do not establish that signals survive template building. Broad observing-mode
  transfer is also unproven: the former “staring” sample was HiRISE fibre data processed
  with a slit recipe.

Read the [M37 audit and corrected numerical tables](docs/milestones/M37-RESULTS.md) for the
controlling evidence and qualifications. Older milestone headlines are historical and may
be superseded. No discovery or submission-ready independent reproduction is claimed.

## What is included

- ESO archive inventories and companion-target feasibility calculations.
- Historical CR2RES reduction and VIPER extraction drivers, with documented limitations.
- Period searches, orbital comparisons, and retained RV/per-order evidence for downstream replay.
- Synthetic validation infrastructure for testing signal retention, uncertainty calibration,
  provenance, and separation of development from future target evaluation.

## Quickstart

Use a **source checkout** for the research scripts and bundled evidence. Python 3.11 or newer
is required; CI tests Python 3.11 and 3.12. From Linux, macOS, or WSL:

```bash
git clone https://github.com/mepotts/exosat-rv.git
cd exosat-rv
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
exosat-rv --help
```

On Windows PowerShell, use `.venv\Scripts\Activate.ps1` for activation. Historical raw
reductions require the separate Linux/WSL CR2RES/VIPER environment; installing this package
does not install those tools. See [Getting started](docs/getting-started.md) for optional
dependencies, CLI examples, and data-directory behavior.

## Reproducibility

These checks run offline after installation, from the repository root:

```bash
python scripts/m37_package_evidence.py --verify
python scripts/m37_render_results.py --check
python -m pytest -m "not network"
```

The first verifies the frozen evidence bytes; the second checks that the audit's generated
tables match the retained results. Neither recomputes the RV extraction. To recompute the
downstream statistical audit into a **new output**, see the
[replay instructions](docs/getting-started.md#replay-the-downstream-audit).

| Available from a clone | Still external or unresolved |
|---|---|
| Adopted RV/per-order/fit-parameter tables and hash manifest in [data/repro](data/repro/README.md) | Raw exposures, reduced spectra, and fitted stellar templates |
| Downstream analysis code, cached results, tests, and audit records | Complete historical raw-to-RV environment and effective run configuration |
| Generic synthetic validation experiments | Observational control validation and a reviewed, frozen target protocol |

The Python **wheel contains the package only**, not these research scripts or data. Current
dependency declarations and `uv.lock` do not reconstruct the uncaptured historical environment.

## Repository guide

| Location | Purpose |
|---|---|
| [src/exosat_rv](src/exosat_rv/) | Reusable Python package: archive, analysis, targets, and experimental M38 modules |
| [scripts](scripts/README.md) | Research drivers and report builders; historical campaigns are identified separately |
| [tests](tests/) | Automated regression and synthetic tests |
| [data](data/README.md) | Published comparison RVs, retained outputs, figures, and frozen downstream evidence |
| [docs](docs/README.md) | Results, reproducibility guidance, validation plans, and contributor reference |
| [papers](papers/README.md) | Third-party literature reference archive, not this project's manuscripts |
| [containers](containers/README.md) | Target-free runtime prototype and its scope limits |

## Ongoing validation

The [M38 validation overview](docs/validation.md) separates completed infrastructure from
open scientific requirements. Current work tests synthetic spectra through VIPER's actual
template builder and RV fitter and broadens uncertainty calibration. Suitable observational
controls and protocol review/freeze must precede any target test. Synthetic engineering
success alone cannot establish independent confirmation.

## Citation and license

If you use this work, cite the software using [CITATION.cff](CITATION.cff) and record the
exact Git commit used. Also cite the original study and underlying methods relevant to your
analysis; their references are included in the citation file. This repository is not the
original authors' supplementary material. No release DOI is assigned here.

Project code is [MIT licensed](LICENSE). Third-party papers and archive products retain their
own rights; see the [literature archive notice](papers/README.md).

Questions, corrections, and reproducibility reports are welcome through
[GitHub issues](https://github.com/mepotts/exosat-rv/issues). See
[Contributing](CONTRIBUTING.md) for verification and scientific-claim requirements, and
[AI involvement](docs/AI-CHECKLIST.md) for the project's disclosure record.
