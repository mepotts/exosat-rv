# M38 control-development checkpoint — generic infrastructure only

> **NOT A PREREGISTRATION / NOT AUTHORITY TO RUN THE TARGET / NOT A SCIENCE RESULT**
>
> This checkpoint implements only the work allowed by
> [the M38 draft](M38-PROTOCOL-DRAFT.md#11-what-may-be-developed-now). It was developed after
> the M14, M36, and M37 outcomes were known, so it does not create observer blindness. No
> M38 code or synthetic test loads a target spectrum, historical target RVO/PAR product,
> published RV table, candidate-period window, or target-specific order set. The repository
> still contains historical artifacts elsewhere; a separately built and audited runtime
> allowlist is required before any future role-separated target mount.

**Parent audit checkpoint:** `8cba282` (`M37: correct audit claims and freeze evidence`).

## What this checkpoint implements

All code is under `src/exosat_rv/m38/`; all verification data are generated inside the
corresponding `tests/test_m38_*.py` files.

| component | primary API | what it establishes | what it does not establish |
|---|---|---|---|
| stellar-only component injection | `DecomposedSpectralExposure`, `inject_stellar_velocity`, `check_injection_invariants` | on an increasing, uniformly sampled synthetic 1-D grid, only the stellar component receives the relativistic shift; telluric transmission, wavelength sampling, LSF and the realised noise are preserved and every diagnostic is independently recomputed | injection into detector images, CRIRES extraction, or any target/template chain |
| adjacent-template convergence | `template_change_metric`, `rv_change_metric`, `ConvergencePolicy`, `evaluate_convergence` | candidate noise-normalised per-order spectral-change and zero-point-invariant RV-change formulas, consecutive-update logic, maximum-iteration stopping, and fail-closed mask/order-count checks | final adoption/calibration of those candidate formulas, margins, `q_conv`, `K_max`, wavelength alignment, or proof that external order identities were preserved |
| generic period search | `weighted_sinusoid_search`, `calibrate_global_max_statistic` | explicit weighted null/periodic designs, full caller-supplied landscape, rank checks, and a complete fixed-design Gaussian max-statistic calibration with plus-one probability | a frozen scientific grid/model/threshold or familywise calibration of an adaptive extractor |
| full-pipeline simulation accounting | `run_adaptive_pipeline_calibration` | plan-hashed trial identities, domain-separated seeds, complete null/signal trial accounting, recovery-rule coupling, failed-run retention, and interval reporting | proof that a caller really rebuilt templates or replayed every adaptive stage; callback contents remain independently auditable |
| reference-mask recovery and arm selection | `score_injection_responses`, `estimate_recovery_slope`, `SelectionContract`, `select_winner` | epoch-aligned disjoint velocity banks, paired-difference uncertainties, strict failure on any injection-only order loss, epoch-clustered recovery intervals, unity-centred equivalence, an exact content-identified arm roster, a committed hidden-plan/seed identity, and deterministic eligible-arm ranking | control validation of the uncertainty/weighting model, bootstrap coverage, cluster minimum, equivalence margin, external gates, or proof that the roster/configuration/hidden-plan digests and statistical contract were signed and timestamped before access and map to the intended real configurations |
| provenance chain | `ImmutableFileRecord`, `build_stage_manifest`, `append_stage_manifest`, `verify_manifest_chain` | strict canonical JSON, content-bound files, sequence-zero linked manifests, exclusive creation, optional detached signature callbacks, and rehash-before-append verification | immutable storage, a selected signing scheme, or protection against a hostile filesystem without external confinement |
| application firewall | `InformationFirewall`, `enforce_output_fields` | resolved-path allowlists, path/content/hash denials, recursive preflight, checked reads, access logs, and detached strict-JSON output-field barriers | an OS security boundary, network isolation, interception of other I/O APIs, or observer blindness by itself |

## Independent hardening cycle

The first implementations were cross-reviewed by agents that had not authored the reviewed
module. The reviews found and regression-tested failures that happy-path tests had missed:

- trial identifiers that did not bind the complete plan, and overlapping null/signal seed
  namespaces;
- manifest append before bound-file rehash, non-strict JSON typing, non-zero chain genesis,
  lexical sequence sorting, and tuple/mutable-output firewall bypasses;
- representation-dependent asymmetric LSF behaviour, unchecked numerical overflow,
  incomplete injection diagnostics, and convergence across mismatched order counts;
- scalar-only injection plans, favourable attrition through surviving orders, one-cluster
  zero-width intervals, arbitrary equivalence centres, and reuse of selection evidence as
  hidden validation;
- ambiguous signature-verifier return values, duplicate manifest keys, mutable callback
  details, and unhandled cyclic/deep strict-JSON values; and
- replaceable score/interval evidence, writable-again arrays, representation-sensitive or
  overlapping hidden plans, incomplete arm rosters, and unlocked selection/validation
  contracts.

Those defects were corrected before this checkpoint. They did not reach a target run or a
scientific artifact.

## Verification at this checkpoint

- The six M38 synthetic suites pass **149 tests** with warnings treated as errors.
- The complete offline repository suite passes **323 tests**, with the two network tests
  deliberately deselected and warnings treated as errors.
- Ruff lint and format checks pass for every M38 module/test and the one M36 cache helper
  whose unclosed read handle was exposed by the warning-strict full run.
- Independent post-fix review reports no remaining P0–P3 finding in the selection,
  provenance/firewall, spectral/convergence, or period-calibration scopes.
- A source/test scan finds no target name, published-period literal, historical milestone
  product loader, or target-specific execution path in `src/exosat_rv/m38/`.

## Decisions deliberately absent from code

The implementation supplies mechanisms, not hidden scientific defaults. It does **not**
choose any of the following:

- control targets, epochs, truth definitions, or exclusion rules;
- extraction-family axes, seed-template lineage, across-order estimator, or epoch QC;
- final adoption/calibration of the implemented candidate `D_T` and `D_RV` formulas, their
  margins, `q_conv`, or `K_max`;
- selection/validation injection designs, amplitudes, phases, counts, or seeds;
- minimum common/reference orders, final adoption of the conservative zero-loss attrition
  rule (or a separately justified alternative), paired-response uncertainty construction,
  recovery interval method, minimum independent clusters, confidence level, or equivalence
  region;
- the primary period/nuisance model, period grid, global evidence threshold, orbital family,
  association tolerance, completeness target, or sensitivity-bound rule; or
- executor, custodian, signing scheme, isolated runtime, dependency lock, or target manifest.

Every one remains a blocking decision in [M38 §12](M38-PROTOCOL-DRAFT.md#12-blocking-decision-register)
and must be justified on simulations or declared controls, independently reviewed, and frozen
in a new preregistration.

## Next permitted work

1. Choose the exact development-control suite and independently established truth records.
2. Exercise these APIs on simulations and only those controls to calibrate the unresolved
   metrics, thresholds, uncertainty/coverage behaviour, extraction family, and search design.
3. Build a minimal runnable image and test its deny list, file-access log, stage barriers,
   manifest signatures, dependency lock, and failure recovery.
4. Have an independent reviewer audit the frozen implementation and replacement
   preregistration before any target is mounted.

Until all four steps and the complete M38 decision register are closed, **do not open target
spectra, run a target reduction or injection, emit a target RV/period diagnostic, or describe
this checkpoint as a blind experiment.**
