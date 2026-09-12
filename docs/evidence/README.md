# Validation and verification evidence

Machine-readable records here support the narrative in [milestones/](../milestones/README.md).
They are distinct from [adopted observational analysis inputs](../../data/repro/README.md).

| File family | Interpretation |
|---|---|
| `m38-*-plan-*.json` | Declared synthetic experiment settings and seeds; not a target preregistration |
| `m38-*-result-*.json` | Retained simulation outcomes, including trial-level accounting |
| `m38-*-verification-*.json`, `m38-verification-*.json` | Scope-specific test/audit records; not all future commits |
| `m38-*-runtime-observation-*.json`, `m38-runtime-observation-*.json`, `m38-sealed-buildkit-metadata-*.json` | Observed runtime/build metadata, with limits explained in the runtime report |
| `m38-null-standard-metadata-*.json` | Archive metadata screen; not independently established RV stability |
| `m38-viper-synthetic-bridge-*.json` | Generated-spectrum VIPER engineering outputs and audits; no observational target results |
| `release-v0.1.0-verification-*.json` | Prepared development snapshot checks, not proof of formal publication |
| [research-navigation-verification-2026-09-12.json](research-navigation-verification-2026-09-12.json) | Public navigation, unchanged evidence/runtime paths, and combined synthetic-development verification |

For interpretation start with [the validation overview](../validation.md),
[coverage pilot](../milestones/M38-SELECTION-COVERAGE-PILOT.md),
[Gaussian benchmark](../milestones/M38-INTERVAL-BENCHMARK.md),
[heterogeneous interval stress](../milestones/M38-HETEROGENEOUS-INTERVALS.md),
[VIPER synthetic bridge](../milestones/M38-VIPER-SYNTHETIC-BRIDGE.md), and
[runtime evidence](../milestones/M38-CONTROL-RUNTIME-EVIDENCE.md).

Keep new runs in new dated files, bind plans/results to the actual sources and environment,
retain unsuccessful outcomes, and document what was verified versus merely asserted.
Hashes do not prove historical execution timing, scientific adequacy, or independent review
by a separate human principal. Do not overwrite an old ledger to make a new implementation
match it; create a new experiment record.
