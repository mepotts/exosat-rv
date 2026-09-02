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

**Parent control-infrastructure checkpoint:** `cb1f4cd`
(`M38: add control-only blind-analysis infrastructure`).

## What this checkpoint implements

The Python library code is under `src/exosat_rv/m38/`; the minimal executable bootstrap,
Dockerfile, and launch contract are isolated under `containers/m38/`. Synthetic unit fixtures
are generated inside `tests/test_m38_*.py`; the separately recorded Docker observation is linked
from the runtime row below.

| component | primary API | what it establishes | what it does not establish |
|---|---|---|---|
| stellar-only component injection | `DecomposedSpectralExposure`, `inject_stellar_velocity`, `check_injection_invariants` | on an increasing, uniformly sampled synthetic 1-D grid, only the stellar component receives the relativistic shift; telluric transmission, wavelength sampling, LSF and the realised noise are preserved and every diagnostic is independently recomputed | injection into detector images, CRIRES extraction, or any target/template chain |
| adjacent-template convergence | `template_change_metric`, `rv_change_metric`, `ConvergencePolicy`, `evaluate_convergence` | candidate noise-normalised per-order spectral-change and zero-point-invariant RV-change formulas, consecutive-update logic, maximum-iteration stopping, and fail-closed mask/order-count checks | final adoption/calibration of those candidate formulas, margins, `q_conv`, `K_max`, wavelength alignment, or proof that external order identities were preserved |
| synthetic pre-template full chain | `TemplateChainRoster`, `CrossInjectionMaskContract`, `run_template_chain_ensemble` | immutable source/injection lineage, disjoint folds, explicit arm/order propagation, full adjacent-template iteration, cross-injection mask invariance, global session-use accounting, and rejection of duplicate physical applications | detector extraction, a real CRIRES+/VIPER adapter, process isolation, or proof that a Python adapter did not hide a cache |
| deterministic toy controls | `ToyControlSpecification`, `generate_toy_control`, `ToyTemplateAdapterFactory` | replayable multi-epoch/order stellar/telluric/noise fixtures and a deliberately simple end-to-end adapter for wiring/failure tests | an adopted synthetic population, instrumental realism, or an observational control truth record |
| generic period search | `weighted_sinusoid_search`, `calibrate_global_max_statistic` | strict weighted null/periodic designs, an immutable replay-validated landscape, rank checks, and complete fixed-design Gaussian max-statistic calibration with plus-one probability | a frozen scientific grid/model/threshold or familywise calibration of an adaptive extractor |
| full-pipeline simulation accounting | `run_adaptive_pipeline_calibration`, `run_adaptive_pipeline_grid_calibration` | plan-hashed trial identities, domain-separated seeds, complete null/multi-axis signal accounting, recovery-rule coupling, failed-run retention, and interval reporting | proof that a caller really rebuilt external templates or replayed every adaptive production stage; callback contents remain independently auditable |
| exhaustive calibration grid | `CalibrationCandidate`, `CalibrationCase`, `CalibrationReport`, `evaluate_*_grid` | exact candidate/case/trial accounting, retained failures, content-bound metrics, and verified execution-attestation hooks for successful outcomes | authentic executor keys, scientific adequacy, calibrated coverage, or permission to promote a winning design |
| control and decision freeze schemas | `ControlSuite`, `TruthRecord`, `DecisionRegister`, `validate_*` | complete exact-schema rosters, evidence/review/signature lineage, nested chronology, independent-review and role/key ownership checks, and fail-closed draft/frozen states | selection of a control, truth of an assertion, authentication of a person/key, or human approval |
| reference-mask recovery and arm selection | `score_injection_responses`, `estimate_recovery_slope`, `SelectionContract`, `select_winner` | epoch-aligned disjoint velocity banks, paired-difference uncertainties, strict failure on any injection-only order loss, epoch-clustered recovery intervals, unity-centred equivalence, an exact content-identified arm roster, a committed hidden-plan/seed identity, and deterministic eligible-arm ranking | control validation of the uncertainty/weighting model, bootstrap coverage, cluster minimum, equivalence margin, external gates, or proof that the roster/configuration/hidden-plan digests and statistical contract were signed and timestamped before access and map to the intended real configurations |
| provenance chain | `ImmutableFileRecord`, `build_stage_manifest`, `append_stage_manifest`, `verify_manifest_chain` | strict canonical JSON, content-bound files, sequence-zero linked manifests, exclusive creation, optional detached signature callbacks, and rehash-before-append verification | immutable storage, a selected signing scheme, or protection against a hostile filesystem without external confinement |
| application firewall | `InformationFirewall`, `enforce_output_fields` | resolved-path allowlists, path/content/hash denials, recursive preflight, checked reads, access logs, and detached strict-JSON output-field barriers | an OS security boundary, network isolation, interception of other I/O APIs, or observer blindness by itself |
| signed stage workflow | `WorkflowLedger`, `WorkflowStage` | signature-independent run identity, one-way exact output schemas, stable frozen arm/config roster, stage-authorized distinct role keys, failure/head/sequence replay protection, winner/plan continuity, and external compare-and-append hooks | authentic signatures/people, a globally atomic durable store, trusted timestamps, or authority to create a target genesis record |
| dedicated runtime probe | `audit_runtime_context`, `RuntimeLaunchContract` | exact five-file content pins, a pinned base image/non-root entrypoint, Docker `RUN` network mode set to none, non-pull-always build semantics, and inspected no-network/read-only/capability/tmpfs launch settings | disabled registry egress during build, a scientific image, a cryptographic audit-to-build transaction, host-admin resistance, or a target mount; see [runtime evidence](M38-CONTROL-RUNTIME-EVIDENCE.md) |

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
  contracts;
- injection-dependent cross-trial masks, stale/relabelled fold evidence, display-label and
  signed-zero duplicate applications, caller-asserted replicate independence, and call-local
  session freshness;
- forgeable or mutable period/calibration reports, threshold-inconsistent recovery summaries,
  permissive numeric coercion, exception renderers that could abort failure accounting, and
  enclosing reviews that predated their child evidence;
- signature-encoding-dependent workflow namespaces, replayable failure attestations,
  unrestricted eligible-arm labels, duplicate configuration identities, and one key silently
  signing every governance role; and
- arbitrary runtime-context replacements, mutable Docker frontend directives, unsafe identity
  or tmpfs settings, and unexpected directory/junction entries in the nominally flat context.

Those defects were corrected before this checkpoint. They did not reach a target run or a
scientific artifact.

## Verification at this checkpoint

- The executable/test/container snapshot is local commit
  `79170dfcf2097c3ce40cca52315a350ad457884d`.
- All 13 target-free M38 suites pass **331 tests** with warnings treated as errors. The exact
  file list, command, result, audit scopes, and exclusions are retained in the strict JSON
  [verification record](../evidence/m38-verification-2026-09-02.json), whose file SHA-256 is
  `5e8c37225380eeedf63d2cd7303f5993fdb8484dc7caebf9fab99edf5cc2e410`.
- Ruff lint and format checks pass for all **27** M38 source/test files. The offline `uv.lock`
  check resolves 44 packages. A direct Windows runtime-policy run passes 17 tests with one
  symlink-capability skip; the Linux M38 run executes all 18 runtime-policy tests.
- Independent adversarial review reports no remaining P0–P3 finding in the final
  period/calibration/control/decision scope and no remaining P0–P2 finding in the final
  template/synthetic scope. Workflow, provenance/firewall, runtime/container,
  spectral/convergence, and selection findings were corrected and regression-tested; their
  external verifier, storage, process-isolation, and audit-to-build limits remain explicit.
- A source/test scan finds no target name, published-period literal, historical milestone
  product loader, target-specific execution path, or network client in the M38 code/tests or
  dedicated container context.
- A current repository-wide pytest claim is deliberately absent: known historical tests open
  target-derived products and are outside this checkpoint's no-target boundary. No
  repository-wide lint result is claimed either; the exact M38-only scope is recorded instead,
  and no unrelated file was changed merely to make this checkpoint appear repository-wide
  clean.

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
- executor, custodian, signing scheme, isolated production runtime, production install lock
  bound to that image, or target manifest.

The new structural verifier callbacks and content hashes do not resolve those decisions by
themselves. Their production implementations must be external to the process whose evidence
they verify, and their principals, keys, durable stores, timestamps, and exact artifacts must be
named in the replacement preregistration.

Every one remains a blocking decision in [M38 §12](M38-PROTOCOL-DRAFT.md#12-blocking-decision-register)
and must be justified on simulations or declared controls, independently reviewed, and frozen
in a new preregistration.

## Next permitted work

1. Choose the exact development-control suite and independently established truth records.
   [The candidate dossier](M38-CONTROL-CANDIDATES.md) now records V340 Ara as a conditional
   positive candidate, but has not found a sufficient 0.2-arcsec same-setting positive control
   with an independently established night-level H1567 amplitude, so this remains a hard gate.
2. Exercise these APIs on simulations and only those controls to calibrate the unresolved
   metrics, thresholds, uncertainty/coverage behaviour, extraction family, and search design.
3. Promote the minimal runtime probe into a content-addressed scientific image and test its
   deny list, file-access log, stage barriers, manifest signatures, dependency lock, process
   isolation, durable compare-and-append store, and failure recovery.
4. Have an independent reviewer audit the frozen implementation and replacement
   preregistration before any target is mounted.

Until all four steps and the complete M38 decision register are closed, **do not open target
spectra, run a target reduction or injection, emit a target RV/period diagnostic, or describe
this checkpoint as a blind experiment.**
