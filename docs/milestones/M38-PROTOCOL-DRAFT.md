# M38 — DRAFT successor protocol for a paper-blind extraction test

> # DRAFT / NOT PREREGISTERED / DO NOT RUN
>
> **This file is design work, not a protocol registration. It was written after the M14 and
> M36 outcomes were known. No target reduction, injection, configuration selection, or period
> search is authorised by this document.** The experiment must not start until every item in
> §12 is resolved independently of CD-35 2722 B's RV outcome, the implementation and inputs
> are frozen and hashed, and a new immutable preregistration supersedes this draft.

Generic control-only infrastructure developed under §11 is recorded in
[`M38-CONTROL-DEVELOPMENT.md`](M38-CONTROL-DEVELOPMENT.md). That checkpoint resolves no
scientific threshold, control choice, role-separation requirement, or authority to mount the
target.

## 1. Why M38 would be a new experiment

[M34](M34-RESULTS.md) showed that the candidate period survives across some extraction
configurations that match the published velocities poorly. It did not establish an
independent boundary for the configuration family. [M36's preregistration](M36-PREREGISTRATION.md)
attempted that stronger test, but [the result](M36-RESULTS.md) is inconclusive and cannot be
repaired retrospectively:

- iteration 1 was fixed even though a self-template may not yet be usable;
- eligibility constrained a recovery point estimate without requiring it to be precise;
- the runner omitted settings said to be held fixed, so upstream defaults supplied different
  effective values;
- injected and reference epoch means could use different valid-order sets;
- rounded console values were parsed for selection; and
- an existing RVO file was accepted by tag alone, without proving which inputs and settings
  produced it.

Two further channels make a corrected M36 run unsuitable as a genuinely paper-blind successor.
[`inject_plan_big.json`](../../scripts/injection/inject_plan_big.json) is a K = 1530 m/s
Keplerian evaluated at the published 171.454-day period, so the selector did not load the RV
table but did respond to a paper-derived phase/time/BERV pattern. The historical
[`blind_search.py`](../../scripts/injection/blind_search.py) also imports `published()`, reports
a paper-matched subset, and hardcodes 171.45 days. Those values may not enter its least-squares
fit, but their presence defeats the stronger paper-blind claim.

The audited M36 code corrects the last four implementation defects for inspection, but all
non-dry execution is disabled before external work or artifact creation. Its dormant paths
use a separate **post-audit replay** namespace. This does not make
`data/m36-selection.json` a valid preregistered result, and it does not solve the scientific
limitation that the current injection shifts an already-built template. That injection
validates fitter-stage transmission, not signal survival while a self-template is constructed.

M38 would ask the still-open question:

> **Can a configuration and a converged template be selected without access to the published
> RV series or to any CD-35 period-search result, while demonstrating end-to-end signal
> transmission through template construction, and does the resulting held-out RV series then
> contain a globally significant periodic signal?**

This is a test of outcome-isolated pipeline selection. It cannot erase the protocol authors'
knowledge of the published claim or of M14/M36. A claim of a genuinely observer-blind
replication additionally requires an executor who has not seen those outcomes (§2.1).

## 2. Blindness and role separation

### 2.1 Required roles

The following roles must be named before preregistration and must not be collapsed silently:

1. **Development team.** Works only on simulations and declared control targets. It may tune
   engineering choices and resolve §12, but it may not run any M38 code on CD-35 spectra.
2. **Hold-out custodian.** Verifies hashes, mounts the frozen CD-35 inputs only after the
   freeze, and releases only the outputs allowed at each barrier below.
3. **Blind executor.** Runs the signed workflow without access to Hoy et al.'s RV table,
   existing `M13_*`, `M14_*`, `M34_*`, `M36_*`, or M37 target-result artifacts. To call the
   experiment observer-blind, this person must also not know the reported period or amplitude.
4. **Unblinding reviewer.** Receives the sealed search artifact and only then compares it with
   the published claim.

If no genuinely blind executor is available, the experiment may still test a paper-excluded,
outcome-isolated selection algorithm, but it must not be described as an observer-blind or
fully independent replication.

### 2.2 Information firewall

Before the target is mounted, an automated deny-list test must prove that the runnable image
contains none of the published RV values, the published period or amplitude, the paper-derived
eleven-order set, prior CD-35 RVO/PAR files, target periodograms, or target-specific selection
results. The target workflow must have no network access.

The barriers are one-way:

1. **Development controls → freeze.** Control results may change the draft. They may not be
   changed after the target mount without cancelling the run and issuing a new protocol.
2. **Target extraction/selection → winner lock.** This stage may emit convergence and
   injection diagnostics, eligibility decisions, the winner ID, and hashes. It must not emit
   combined target RVs, a periodogram, or any comparison to published values.
3. **Winner validation → search lock.** A separately committed validation injection plan is
   opened once. Failure stops the experiment; no runner-up may replace the winner.
4. **Generic period search → sealed artifact.** The full landscape and global null calibration
   are written and hashed before any published period window is supplied.
5. **Unblinding.** Only the unblinding reviewer may add the comparison with Hoy et al.

Merely promising not to look at a file is insufficient. The runnable container, file-access
log, stage-specific output schema, and hash commitments must enforce these barriers.

## 3. Inputs and development controls

### 3.1 Development data

The control suite must be fixed before any M38 target run and must include:

- fully synthetic CRIRES+ H-band spectra with known stellar shifts, unchanged tellurics,
  realistic sampling, noise, and line-spread functions;
- at least one same-setting stable or null target; and
- at least one same-setting positive RV control whose expected variability was established
  independently of this project.

The exact controls, epochs, truth definitions, and exclusion rules are unresolved (§12).
GJ 229 B is informative about self-template absorption, but its unresolved double-lined
nature makes its absolute amplitude model-dependent; it cannot be the only positive control.
No development choice may be scored on a CD-35 RV, CD-35 periodogram, or agreement with Hoy.

### 3.2 Held-out target inputs

The existing 18 CD-35 epochs have already been reduced, searched, and used to develop M14,
M34, M36, and this successor design. They cannot become a prospective statistical holdout by
changing analysts or hiding files now. The final preregistration must choose exactly one honest
claim and data regime:

- **clean-room computational rediscovery:** a genuinely paper-blind external executor runs a
  control-developed frozen pipeline on the old spectra. This tests whether that executor and
  computation can rediscover a signal, but the dataset and protocol lineage are not fresh; or
- **prospective confirmation:** only CD-35 epochs unavailable to the development team at the
  freeze are used for the claim-bearing test. This is statistically fresh confirmation of a
  known hypothesis, not blind discovery.

If neither an uncontaminated executor nor future untouched epochs are available, M38 can test
procedural outcome isolation only. It cannot support a genuinely blind or prospective claim.
The chosen regime and target sample are unresolved blocking decisions (§12).

Whichever regime is chosen, the primary route should begin with raw nodding frames and a frozen
CRIRES+ calibration set, not an existing VIPER product. The exact ESO identifiers, calibration
associations, expected frame counts, and SHA-256 digests must appear in the final
preregistration. `cr2res` version, recipe parameters, environment, and per-nod conversion must
also be frozen. Archive-combined products may be a later robustness analysis, never a route
used to choose the primary configuration.

Every successfully reduced public epoch enters the workflow. A deterministic spectral-quality
rule may exclude an epoch only if its statistic, threshold, and treatment of missing values
were calibrated on the development controls and frozen before target access. The rule may not
use combined RV, time-series fit, BERV correlation, published matching, or periodogram power.
The all-epoch result must be reported alongside any predeclared quality-screened result.

## 4. Candidate extraction family and its unresolved lineage

Carrying forward the factorial grid specified before M36 would avoid tuning it to the M36
outcomes. It would **not** make the family target-independent: the M36 preregistration says
these axes and values were motivated by what mattered in M14 on CD-35 itself. The table below
is therefore only a candidate implementation inventory, not a frozen paper-blind family.

| axis | fixed values |
|---|---|
| `-oset` | `2:20`, `2:11`, `11:20` |
| `-oversampling` | `1`, `2`, `4` |
| `-kapsig` | `3.0`, `4.5` |
| `-telluric` | `sig`, `mask` |

This is a candidate set of 36 configurations in the lexicographic order already encoded by the
hardened runner. Before registration, the family must either be re-derived/justified using the
declared controls or be paired with outcome language that admits its CD-35-informed lineage.
Once that decision is frozen, no arm may be added, deleted, or reordered after target access.

For every RV fit, the following must be passed explicitly rather than inherited from VIPER
defaults:

- instrument `CRIRES` and the frozen H-band FTS file;
- `-nocell`, `-chunks 1`, `-deg_norm 3`, `-deg_wave 3`, and `-iset 380:1700`;
- the arm's four grid values; and
- target coordinates from one content-checked, frozen target file.

The draft has not yet resolved whether template construction is common across arms or varies
with an arm's order set. A common all-segment template would use `-oset 0:21`, `-createtpl`,
and `-tpl_wave tell`, with the arm-specific `-oset` entering only the RV fit; an arm-specific
template would instead carry that arm's `-oset` through its complete template chain. The final
protocol must choose and control-validate one of those mutually exclusive designs. The exact
seed template and primary across-order combination estimator also remain unresolved. None may
be inherited from `M13tpl_tpl.fits`, the paper-derived order set, or whichever choice performed
best in M14/M36. They must be resolved on the controls and frozen (§12).

The final preregistration must name an exact VIPER commit plus any dirty patch, the full
`config_viper.ini`, Python/dependency lock, CRIRES reduction environment, and every command
argument. A moving branch or an implicit default is not an admissible implementation.

## 5. Outcome-isolated template convergence

Iteration count must be selected by adjacent-template convergence, never by RV scatter,
periodogram behaviour, agreement with Hoy, or the iteration count that worked in M14.
For each configuration, begin from the same frozen paper-independent seed and repeat:

1. fit every accepted epoch against template `T_k` using that arm's complete fixed settings;
2. construct `T_(k+1)` from those fits with the same settings;
3. align `T_(k+1)` and `T_k` by one global wavelength offset, without using epoch times or
   target RV structure;
4. compute, on common finite pixels, a robust noise-normalised spectral-change statistic per
   order and its predeclared cross-order aggregate `D_T(k)`; and
5. subtract each iteration's arbitrary RV zero point and compute a robust adjacent-iteration
   change statistic `D_RV(k)` on the same epochs and valid orders.

Stop at the first iteration for which both `D_T(k)` and `D_RV(k)` satisfy their frozen
equivalence limits for `q_conv` consecutive updates. If either statistic becomes non-finite,
an epoch/order set changes in a forbidden way, or convergence has not occurred by `K_max`, the
arm fails. It may not fall back to the iteration with the lowest scatter.

The definitions of `D_T`, `D_RV`, their equivalence margins, `q_conv`, and `K_max` must be
calibrated on the controls and are unresolved. M36's observed slopes and M14's preferred second
iteration are forbidden calibration data.

No claim-bearing epoch may be measured against a target-built template that contains that same
epoch. The final protocol must choose and control-validate either (a) a template built only from
a disjoint, predeclared training set or (b) leave-one-epoch-out cross-fitting, in which epoch
`e` is measured only against a template converged without epoch `e`. Every injection must repeat
the same training split or fold-specific template chain. An all-epoch self-template used to
measure its own contributing epochs is not an M38-valid shortcut.

Convergence is necessary but not sufficient. M11 demonstrates that a self-template can become
stable while suppressing a real signal. Therefore every arm must repeat its complete template
chain for each end-to-end injection in §6; a converged template made once and shifted afterward
cannot validate this stage.

## 6. End-to-end injections and uncertainty-aware selection

### 6.1 Injection operator

The injection must enter the stellar component before iteration zero and then traverse raw
extraction (or the earliest scientifically defensible spectral representation), every template
iteration, and the final RV fit. It must preserve the observed telluric wavelengths, LSF,
sampling, and noise. Shifting the whole observation is invalid because it also shifts
tellurics. Shifting only the final template, as `mktpl.py` currently does, remains useful as a
fitter-stage diagnostic but does not qualify as M38 end-to-end validation.

A generic synthetic one-dimensional component operator now exists in the control-development
checkpoint, but it is neither an earliest-representation detector/extraction operator nor
validated on the required control suite. A qualifying full-chain operator and demonstrated
recovery on synthetic truth remain blocking prerequisites, not implementation details to
improvise during the target run.

Two disjoint, hash-committed target injection plans are required:

- a **selection plan**, visible during configuration selection; and
- a **winner-validation plan**, hidden until the winner and its complete template chain are
  locked.

Injected velocities must be generated from frozen seeds by a symmetric, well-conditioned
design that is independent of the published period, phase, amplitude, target RVs, BERV, and
M36 outcomes. The bank must span multiple amplitudes, including the intended science operating
range, and multiple temporal patterns rather than one candidate-like sinusoid. Their range,
number, seed-generation method, and conditioning criteria are unresolved and must be justified
on the controls. A runner that fails validation may not be replaced with the next-ranked arm.

### 6.2 Common-valid-order score

For injection `j` at epoch `e`, define `O_ej` as the intersection of orders having finite RV
and positive uncertainty in both the injected and uninjected fits. The epoch response is

`d_ej = mean over o in O_ej of (RV_injected,ejo - RV_reference,eo)`.

The injected and reference means must never be formed from separate order masks. The selected
scorer must emit full-precision machine-readable values, the order intersection for every
epoch, all skipped-data reasons, and per-order slopes. All planned epochs and injections must
complete; silently fitting a smaller successful subset is forbidden.

The intersection rule is necessary but not sufficient: if an injection makes a difficult
reference-valid order fail, simply removing that order from `O_ej` can make recovery look
better on the surviving orders. Before target access, the final protocol must therefore freeze
an injection-induced attrition policy that cannot benefit from the injected fit's outcome. It
must either use a reference-defined per-epoch order mask and treat every injection-only loss as
a predeclared failure/penalty, or specify another control-justified attrition statistic,
threshold, and penalty with equivalent protection. Missing/non-finite injected fits must be
recorded, never converted into a smaller favourable mask. Simulations must vary order S/N,
velocity shift, amplitude, and failure probability and demonstrate that the complete scoring
and eligibility rule has the declared false-pass behaviour and interval coverage.

The hardened `inject_score2.py` implements this common-mask rule and exact JSON output. It may
be reused only after the full-chain injection operator supplies its inputs; by itself it does
not validate template construction.

### 6.3 Eligibility and winner

Recovery is an equivalence problem, not a point-estimate gate. The final protocol must specify
an uncertainty estimator suitable for 18 heteroscedastic epochs and a confidence level before
target access. For an estimated recovery slope `s` with interval `[L, U]`, an arm is eligible
only if all of the following hold:

1. every reference, selection-injection, and template-convergence run is complete and
   provenance-valid;
2. every epoch meets a predeclared minimum common-order requirement;
3. injection-induced order attrition satisfies the frozen reference-mask/penalty rule;
4. the full confidence interval `[L, U]` lies inside the independently justified equivalence
   region `[1 - delta, 1 + delta]`; and
5. predeclared per-order stability and catastrophic-fit checks pass.

The uncertainty method, confidence level, `delta`, common-order minimum, order-attrition
policy, and order-stability limits are unresolved. In particular, `slope_err <= 0.10` was
proposed only after M36's outcomes were seen and may not be imported as M38's justification.

The night, not the number of orders or reruns, is the independent sampling unit. The uncertainty
method must preserve that clustering (for example through a control-validated night-clustered
bootstrap or robust covariance). Eligibility must also include a separately justified
within-epoch fit-quality/completeness criterion so a configuration with unusable reference RVs
cannot pass only because injected and reference pathologies cancel. That criterion may not
reward low time-series RV scatter, which can be produced by signal suppression.

Among eligible arms, choose the one minimising the worst confidence-bound error
`max(abs(L - 1), abs(U - 1))`. Break an exact numerical tie by the frozen configuration index,
not by a new target diagnostic. The winner must then pass the hidden validation plan under the
same equivalence rule. Zero eligible arms, or a failed winner validation, ends the experiment
without a period search.

## 7. Held-out period search

The period-search program used in the sealed stage must be a generic, importable implementation
whose runnable source contains no published RV loader, no literal published period/window, and
no "matched to paper" branch. The present historical `blind_search.py` does not meet this
requirement and must not be the M38 executable.

Before target access, the final protocol must freeze:

- one primary order-combination estimator and one primary epoch-quality mask;
- the null and periodic models, including the BERV nuisance treatment;
- the treatment of epoch uncertainties;
- a logarithmic search grid whose upper bound is a deterministic function of the observed
  baseline rather than an extrapolation far beyond it;
- a global, look-elsewhere-corrected null calibration and its random seeds; and
- the evidential thresholds and outcome language.

The search stage receives only the winner's locked reference RVO and the frozen quality mask.
It writes the complete period/evidence/amplitude landscape, top peaks, all-epoch sensitivity
search result, any separately labelled predeclared screened result, globally calibrated null
statistic, software/input hashes, and no paper comparison.
No configuration, mask, combine, nuisance model, or threshold may change after this output is
seen. The artifact is hashed and sealed before the unblinding reviewer supplies the published
comparison window.

The historical 5-day lower bound and 4000-point logarithmic density predate the M36 outcomes,
so retaining them would not be a response to those outcomes; prior existence is not, however,
a scientific justification. Their adequacy and the exact null-calibration method remain
decisions for the control phase, while the upper bound must not exceed the usable baseline.
Multiple variants may be reported as labelled sensitivity analyses, but only one frozen
primary analysis may determine the outcome.

A null calibration applied only to the already selected winner is conditional on the
configuration and mask; it is not automatically a familywise false-positive calibration for
an adaptive 36-arm workflow. Unless independent work justifies the selection and QC statistics
as ancillary to the search statistic, the primary false-positive experiment must replay the
**entire frozen pipeline** on null simulations/controls: epoch QC, all arms, eligibility,
winner selection, hidden validation, and the winner's period search. The final protocol must
freeze that ensemble and its pass/fail accounting before target access.

### 7.1 Claim-bearing detection completeness and sensitivity

Selection/validation recovery slopes establish extraction transmission; they do not by
themselves define the probability that the final adaptive search would detect an orbital
signal. A “valid, sensitive pipeline” or material null in §10 therefore requires a separate,
predefined full-pipeline detection-completeness experiment. Its design is unresolved and must
be frozen before target access. At minimum the replacement preregistration must specify:

- the claim-bearing orbital family and period domain, including whether or how eccentricity,
  argument/epoch, trends, and other nuisance parameters vary;
- a fixed semiamplitude grid and either a deterministic phase/argument grid or a seeded draw
  design, together with the number of noise realisations and all seeds;
- a paper-independent recovery rule coupling the frozen global evidence threshold to a
  predeclared period/orbit association tolerance, without introducing a published-period
  window after results are visible;
- the completeness target and sensitivity-bound definition, plus the interval or coverage
  method, confidence level, grid interpolation rule, and treatment of failed pipeline runs;
  and
- the complete signal-injection ensemble and pass/fail accounting used to validate those
  operating characteristics on simulations and declared controls.

Every signal trial used for the claim-bearing bound must inject the stellar shift before
template iteration zero and replay the **entire adaptive pipeline**: epoch QC, every candidate
arm, convergence, injection eligibility, winner selection, hidden winner validation, and the
winner's globally calibrated period search. Reusing the target's selected winner, mask, or
template would estimate only conditional search sensitivity and cannot support the primary
bound. The final artifact must report completeness over the full frozen orbital/amplitude grid
with its uncertainty and all failed trials; it may not report only the first successful
amplitude or a candidate-matched slice.

## 8. Provenance, cache validity, and audit trail

Every stage must write an append-only manifest containing at least:

- protocol and source commit hashes, plus a patch hash if the tree is dirty;
- raw science and calibration identifiers, sizes, SHA-256 digests, and acquisition metadata;
- reduction recipe/version/configuration and hashes of every reduced product;
- exact VIPER/Python/dependency identities and complete argv for every invocation;
- seed-template, generated-template, FTS, target-coordinate, injection-plan, scorer, and
  period-search hashes;
- RVO/PAR/template output hashes and row/order counts;
- random seeds, stage start/end times, exit status, and failure reason; and
- the prior stage's signed manifest hash, forming a chain.

The hardened cache rule is the minimum: an RVO without a matching sidecar is a cache miss, and
the sidecar must bind exact argv/settings and content fingerprints for inputs, templates,
target coordinates, FTS, VIPER code/config, plans, scorer, and output. Generated template
bundles likewise require a plan/source/generator/output manifest. A mismatch forces a run in a
new namespace; it never licenses relabelling or overwriting a historical artifact.

M38 tags and outputs must be new. Existing M13/M14/M36 products are forbidden caches. The
historical `data/m36-selection.json` remains historical. The disabled M36 runner's dormant
`data/m36-post-audit-replays/m36-post-audit-replay-<run-id>.json` path is not an M38 result.

## 9. Stopping and failure rules

The workflow stops, records the reason, and performs no period search if any of these occurs:

- an item in §12 is unresolved or a freeze/signature is missing;
- the deny-list or file-access audit finds a forbidden paper/target-result artifact;
- an input, code, dependency, command, or prior-stage hash differs from its manifest;
- reduction yields an unexpected frame/epoch count or requires a manual scientific choice;
- a template chain fails the frozen convergence rule by `K_max`;
- an injection changes tellurics, fails to traverse template construction, is missing, or
  produces too few common valid orders;
- no arm passes the uncertainty-aware selection gate;
- the locked winner fails the hidden validation plan;
- a combined target RV or period diagnostic is revealed before the appropriate barrier;
- the generic search cannot complete its frozen global calibration; or
- the full-pipeline detection-completeness ensemble or its frozen uncertainty rule cannot
  complete; or
- any operator proposes a threshold, mask, runner-up, extra arm, or code fix after seeing a
  target selection or search result.

An infrastructure-only failure may be retried from the last content-identical signed stage.
Any scientific-code, input, or rule change cancels the run. The failed attempt remains in the
audit trail, and a revised protocol must be registered before starting over.

## 10. Interpretation fixed before unblinding

The final preregistration must attach outcome language to its independently justified global
evidence thresholds. At minimum the logic is:

| valid outcome | permitted interpretation |
|---|---|
| no eligible configuration or failed winner validation | the tested outcome-isolated family is not demonstrably sensitive; no statement about the target period |
| valid, sensitive pipeline; no globally supported peak | the candidate is not recovered by this frozen family; report as a material null, with the predefined sensitivity bound |
| valid, sensitive pipeline; globally supported peak before unblinding | a periodic signal is present under outcome-isolated extraction; compare with the published period only after sealing |
| any blindness, provenance, convergence, injection, or calibration failure | invalid/inconclusive experiment, regardless of an interesting-looking periodogram |

Even a positive result would establish independence of the frozen computational selection from
published RV values. It would establish observer blindness only if §2.1's independent-executor
condition was genuinely met.

## 11. What may be developed now

Before preregistration, work is limited to generic code and declared controls:

- implement and test the stellar-only, pre-template injection operator;
- implement convergence metrics without time-series or paper inputs;
- refactor a paper-free generic period-search library and global null calibration;
- implement a generic full-adaptive-pipeline detection-completeness harness on simulations and
  declared controls;
- extend manifests and deny-list/file-access tests;
- choose and document the control suite; and
- use only those controls to resolve §12.

No component may be smoke-tested on CD-35, even if its output is not plotted. A dry run that
opens target spectra is a target run.

## 12. Blocking decision register

All entries below must be resolved, justified from simulations/controls or external method
literature, and frozen in the replacement preregistration. None may be filled from M14/M36
target outcomes.

| unresolved decision | required independent basis |
|---|---|
| blind executor, custodian, and enforcement mechanism | named people/process plus a tested deny-list and stage-output firewall |
| claim and target-data regime | clean-room rediscovery on consumed data or prospective confirmation on genuinely untouched epochs, with matching outcome language |
| exact control targets and truth definitions | same-setting suitability and truth independent of this project's CD-35 result |
| extraction-family axes/values and whether template creation is common or arm-specific | control-only performance and a design with unambiguous `-oset` propagation |
| raw/calibration target manifest and reduction version/config | archive provenance and reproducible reduction validation |
| paper-independent seed template | control-tested spectral match; never an M13/M14 selected template |
| primary across-order estimator and epoch QC statistic/threshold | control performance fixed without target RV/period diagnostics |
| definitions and limits for `D_T`, `D_RV`, `q_conv`, and `K_max` | convergence and signal-retention performance on simulations/controls |
| disjoint-template or leave-one-epoch-out construction | control-validated prevention of fitting an epoch against a self-template containing itself |
| stellar-only end-to-end injection operator | synthetic proof that stellar shifts change while tellurics/LSF/noise remain invariant |
| selection/validation injection designs, ranges, counts, and seeds | control-based precision and conditioning, independent of the published orbit |
| slope uncertainty estimator, confidence level, equivalence margin `delta` | coverage simulation plus a scientifically justified tolerated amplitude bias |
| minimum common orders, per-order failure limits, and reference fit-quality rule | predeclared control completeness, false-pass behaviour, and protection against cancellation of unusable RVs |
| injection-induced order-attrition/reference-mask policy, statistic, threshold, and penalty | simulations with shift/amplitude/S/N-dependent order failures demonstrating false-pass control and interval coverage |
| primary period model, weights, grid, global null method, seeds, and evidence thresholds | control false-positive/coverage study and a declared scientific error budget |
| end-to-end familywise null calibration for QC and 36-arm adaptive selection | null simulations/controls replaying the complete frozen pipeline, or an independently justified ancillarity argument |
| claim-bearing orbital family, amplitude/phase grid, completeness target, uncertainty rule, and recovery tolerance | signal simulations/controls replaying the complete frozen adaptive pipeline and demonstrating coverage of the reported sensitivity bound |
| exact frozen commits, dependency lock, manifests, output schemas, and signing method | reproducible build and an independent audit before target mount |

Until this table is closed in a new document, **M38 remains DRAFT / NOT PREREGISTERED / DO
NOT RUN**.
