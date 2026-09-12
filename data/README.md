# Data and retained analysis products

This directory contains several **different kinds of evidence**, not a single interchangeable
RV dataset. Read the [M37 audit](../docs/milestones/M37-RESULTS.md) before interpreting results.

| Location | Meaning |
|---|---|
| [published/](published/) | RV comparison tables from versions of the original study; not RVs extracted by this project |
| [repro/](repro/README.md) | Frozen adopted M14/M15 RV, per-order, fit-parameter, and metadata inputs with a hash manifest |
| [viper/](viper/) | Historical extraction-development outputs; some settings and conclusions were superseded |
| `m*.json`, `m*.csv`, `m*.npz`, `m*.txt` | Retained inventories, downstream calculations, and intermediate milestone artifacts |
| [export/](export/) | Exported series, analysis tables, and manuscript figures |

Published and independently extracted RVs have distinct paths, but that does **not** imply
independent historical selection: extraction choices were calibrated against the published
series. For example, M36's retained selection result records an invalid preregistration
execution, not a validated result; the original M35 photometry is superseded by its v2 audit.

Raw/reduced FITS products, fitted templates, and calibration resources are largely external
or Git-ignored. The [evidence-bundle guide](repro/README.md) states exactly which bytes a clone
provides and which it only fingerprints. Do not regenerate frozen inputs in place. Use a
new output path for replay, as in [Getting started](../docs/getting-started.md).

Synthetic validation ledgers and environment/verification records live in
[docs/evidence/](../docs/evidence/README.md), alongside their explanatory milestone documents.
This directory and its existing filenames remain stable because historical scripts and
manifests depend on them. The project's MIT license does not relicense external archive data.
