# M38 response-level recovery-interval pilot

> **DEVELOPMENT SIMULATION / NOT PREREGISTERED / NOT TARGET VALIDATION**

This experiment addresses one open M38 question: the repeated-noise coverage of the
implemented percentile cluster-bootstrap recovery-slope interval. It does not inject spectra,
rebuild templates, select extraction arms, perform hidden validation, or search for periods.
It cannot validate the complete adaptive pipeline or close the M38 decision register.

## Design fixed for this pilot

The [explicit plan](../evidence/m38-selection-coverage-plan-2026-09-06.json) was written before
the production pilot was run. This is a local exploratory design, not a signed preregistration.
The author already knows historical project outcomes. All response arrays are generated from
declared mathematical distributions; no observational RVs, timestamps, spectra, or templates
are loaded. No scientific threshold is adopted by this experiment.

The [driver](../../scripts/m38_selection_coverage.py) calls the existing
`score_injection_responses` and `estimate_recovery_slope` APIs. It does not replace their
numerical calculations with a faster approximation. Every cell has 200 independent noise
realisations and every interval has 199 bootstrap draws. This deliberately modest pilot can
expose substantial defects, not establish precise tail-error guarantees.

The seven scenarios are independent nights at counts 12, 24, and 48; heterogeneous noise
at 24 nights; shared four-night season errors with incorrectly independent night labels;
the same generative model with correct season labels; and velocity-dependent injected-order
loss. Each is crossed with true slopes 0.7, 0.8, 1.0, 1.2, and 1.3. The illustrative
equivalence interval is [0.8, 1.2], not an adopted scientific tolerance. Boundary truths
belong to the non-equivalence null. All source, plan, cell, trial, and RNG-domain identities
are recorded; simulation and bootstrap streams are separate. The two season scenarios use
independent draws, not paired trials.

For injection `j`, night `e`, and order `o`, the generator is

`response[j,e,o] = (true_slope + slope_error[e]) * velocity[j] + offset[e] + noise[j,e,o]`.

Slope error and offset are Gaussian with standard deviations 0.25 and 80 m/s; independent
order noise has standard deviation 40 m/s. In the heterogeneous scenario the first two
standard deviations have fixed geometric multipliers from 0.4 to 2.5. In the seasonal
scenario the same slope error and offset are shared by each four-night block. The supplied
paired-response uncertainty is the exact marginal standard deviation under this generator;
the production scorer still uses its correlation-agnostic across-order mean bound.

### Deliberate limitations

- This tests coverage for a population-mean linear response slope under the specified noise
  laws. It does not prove recovery of every epoch's shift or an orbital amplitude.
- Symmetric injection velocities and even-in-velocity weights cause the shared offsets to
  cancel from the slope. They do not stress general offset/velocity coupling.
- The response errors are additive and the supplied marginal uncertainties are known exactly.
  Estimated, misspecified, or RV-dependent uncertainties need separate experiments.
- The independent-night bootstrap assumption is deliberately violated in one season scenario.
  Its failure would diagnose that assumption, not a coding error in bootstrap resampling.
- The attrition scenario has many opportunities for failure: with the zero-loss policy,
  almost all trials are expected to stop. Low false-pass frequency there is a fail-closed
  engineering property, not evidence of useful sensitivity or interval calibration.
- All-planned coverage counts an absent interval as not covering; coverage conditional on a
  complete interval is reported separately. Failed trials never disappear from the ledger.
- Monte Carlo rate intervals use SciPy's exact binomial method, separately from the recovery
  intervals being evaluated. They are pointwise, not simultaneous across cells. See
  [SciPy's API documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).
- No best-performing setting is promoted, and no method is silently changed after results.

## Reproduction

From an installed source checkout, or with `PYTHONPATH=src`:

```sh
python scripts/m38_selection_coverage.py \
  --plan docs/evidence/m38-selection-coverage-plan-2026-09-06.json \
  --output /tmp/m38-selection-coverage-replay.json
```

The output must not already exist. Unexpected exceptions abort rather than emitting an
apparently complete report. The driver records source hashes at import and checks them before
and after execution; this is local provenance, not an OS-level immutable runtime guarantee.

## Results

The [complete trial ledger](../evidence/m38-selection-coverage-result-2026-09-06.json) is
retained, including absent intervals and the separate counts of unrun versus numerically
failed bootstrap repetitions. False equivalence is not applicable inside the equivalence
margin; the JSON records null rather than an artificial zero-risk estimate there.

<!-- BEGIN GENERATED M38 COVERAGE -->

Plan SHA-256: `c41a36be49840bc5947fcc1ac2d6d913c8616e5a68efed4f117ceb6225866ae3`.
All 7,000 planned response trials are retained.
Coverage is all-planned; brackets are pointwise 95% exact Monte Carlo intervals.
An absent recovery interval is a non-covering trial, not silently excluded.
Gate passes at the equivalence boundaries or outside them are false-equivalence events.

| Scenario | True slope | Complete / planned | Coverage % [MC interval] | Interval gate passes / planned |
|---|---:|---:|---:|---:|
| independent-12 | 0.7 | 200/200 | 88.0 [82.7, 92.2] | 2/200 |
| independent-12 | 0.8 | 200/200 | 90.5 [85.6, 94.2] | 11/200 |
| independent-12 | 1 | 200/200 | 91.5 [86.7, 95.0] | 127/200 |
| independent-12 | 1.2 | 200/200 | 90.5 [85.6, 94.2] | 11/200 |
| independent-12 | 1.3 | 200/200 | 89.5 [84.4, 93.4] | 0/200 |
| independent-24 | 0.7 | 200/200 | 89.0 [83.8, 93.0] | 0/200 |
| independent-24 | 0.8 | 200/200 | 95.5 [91.6, 97.9] | 5/200 |
| independent-24 | 1 | 200/200 | 92.0 [87.3, 95.4] | 189/200 |
| independent-24 | 1.2 | 200/200 | 94.5 [90.4, 97.2] | 6/200 |
| independent-24 | 1.3 | 200/200 | 93.0 [88.5, 96.1] | 0/200 |
| independent-48 | 0.7 | 200/200 | 95.0 [91.0, 97.6] | 0/200 |
| independent-48 | 0.8 | 200/200 | 94.0 [89.8, 96.9] | 7/200 |
| independent-48 | 1 | 200/200 | 92.0 [87.3, 95.4] | 200/200 |
| independent-48 | 1.2 | 200/200 | 93.5 [89.1, 96.5] | 7/200 |
| independent-48 | 1.3 | 200/200 | 94.5 [90.4, 97.2] | 0/200 |
| heterogeneous-24 | 0.7 | 200/200 | 93.0 [88.5, 96.1] | 0/200 |
| heterogeneous-24 | 0.8 | 200/200 | 93.0 [88.5, 96.1] | 10/200 |
| heterogeneous-24 | 1 | 200/200 | 93.0 [88.5, 96.1] | 199/200 |
| heterogeneous-24 | 1.2 | 200/200 | 93.5 [89.1, 96.5] | 7/200 |
| heterogeneous-24 | 1.3 | 200/200 | 91.5 [86.7, 95.0] | 0/200 |
| season-correlated-night-clusters | 0.7 | 200/200 | 62.5 [55.4, 69.2] | 9/200 |
| season-correlated-night-clusters | 0.8 | 200/200 | 60.0 [52.9, 66.8] | 35/200 |
| season-correlated-night-clusters | 1 | 200/200 | 58.5 [51.3, 65.4] | 146/200 |
| season-correlated-night-clusters | 1.2 | 200/200 | 55.0 [47.8, 62.0] | 53/200 |
| season-correlated-night-clusters | 1.3 | 200/200 | 55.5 [48.3, 62.5] | 6/200 |
| season-correlated-season-clusters | 0.7 | 200/200 | 85.0 [79.3, 89.6] | 2/200 |
| season-correlated-season-clusters | 0.8 | 200/200 | 84.0 [78.2, 88.8] | 14/200 |
| season-correlated-season-clusters | 1 | 200/200 | 83.5 [77.6, 88.4] | 54/200 |
| season-correlated-season-clusters | 1.2 | 200/200 | 85.0 [79.3, 89.6] | 13/200 |
| season-correlated-season-clusters | 1.3 | 200/200 | 80.0 [73.8, 85.3] | 2/200 |
| injection-order-loss | 0.7 | 0/200 | 0.0 [0.0, 1.8] | 0/200 |
| injection-order-loss | 0.8 | 0/200 | 0.0 [0.0, 1.8] | 0/200 |
| injection-order-loss | 1 | 0/200 | 0.0 [0.0, 1.8] | 0/200 |
| injection-order-loss | 1.2 | 0/200 | 0.0 [0.0, 1.8] | 0/200 |
| injection-order-loss | 1.3 | 0/200 | 0.0 [0.0, 1.8] | 0/200 |

<!-- END GENERATED M38 COVERAGE -->

### Interpretation

The season-correlated examples expose substantial undercoverage. Treating every night as an
independent bootstrap unit fails severely; using the actual independent season blocks helps
but does not restore nominal coverage with so few blocks. At unity response, both of those
scenarios have pointwise Monte Carlo intervals entirely below nominal coverage. The correctly
grouped case shows why simply supplying honest cluster labels is necessary but not sufficient
for this small-sample percentile method.

Independent and heterogeneous scenarios are more favorable. Their finite pilot coverage
estimates must be read with the displayed Monte Carlo intervals, not treated as exact rates;
most individual intervals include the nominal level. This pilot neither certifies those
settings nor establishes a simultaneous undercoverage claim across the grid.

The order-loss scenario overwhelmingly rejects inputs before interval construction. Its
zero-loss behavior prevents favorable-subset fitting, but absence of an accepted bad arm is
not proof of useful sensitivity. Read the `coverage_given_complete` field separately; it is
null when there are no complete intervals. Zero observed false passes in a finite ensemble
does not imply zero false-pass probability.

**Decision:** do not promote the current percentile interval, its minimum-cluster rule, or
the illustrative equivalence margin to the frozen science protocol. These are simulation
results about one component, not evidence for or against any satellite. No target processing
or production extraction change was made.

### Next statistical experiment

Before a new run, fix a separate comparison plan with more independent noise trials and a
bootstrap-repetition sensitivity axis. For the homogeneous Gaussian scenarios, an interval
based on independent cluster slopes has an analytically tractable small-sample reference;
use it to distinguish finite-bootstrap effects from small-cluster percentile bias. Benchmark
against known generator covariance, not against target RVs. A diagnostic comparison is not
automatic adoption of a new estimator.

Then extend the generator to asymmetric/varying injection banks, estimated or misspecified
uncertainties, unequal season sizes, slope/offset dependence, and useful attrition rates.
Those experiments must precede calibration in a real extraction/template-chain adapter.
Single-arm interval coverage cannot replace the full adaptive pipeline's false-positive and
detection-completeness experiments.

## Verification and audit

The independent agent audit checked the generator's estimand, covariance, boundary-null
classification, seed separation, failure denominators, and production API calls. It caught
and prompted fixes for source identities captured only after execution, misleading
not-applicable false-equivalence counts, and conflated unrun/failed bootstrap repetitions.
The table renderer also rechecks interval event semantics, trial identities, seed bindings,
source hashes, and summaries against the ledger. Counts, rates, and nulls must match exactly;
binomial interval endpoints permit relative tolerance `1e-10` and absolute tolerance `1e-12`
for solver roundoff across SciPy versions. This is an agent methodological/code review,
not an external RV specialist's scientific approval.

Final verification passes all **396** M38 tests on WSL with warnings treated as errors and
the **20** new coverage tests on Windows using a task-local cache. The source/test lint,
Python compilation, generated-table check, five independently replayed trials, and full
ledger audit are recorded in the
[verification record](../evidence/m38-coverage-verification-2026-09-06.json).

An initial run with the same plan completed before the last two reporting fixes. Its ledger
and exact driver are retained locally under `dist/m38-selection-coverage-initial-2026-09-06.json`
and `dist/m38_selection_coverage_initial.py`; they are not the committed final evidence.
The final run repeats the unchanged numerical design and records the corrected report schema.

The numerical table is generated with:

```sh
PYTHONPATH=src:. python -m scripts.m38_render_selection_coverage \
  --result docs/evidence/m38-selection-coverage-result-2026-09-06.json \
  --document docs/milestones/M38-SELECTION-COVERAGE-PILOT.md
```

Add `--check` to verify the document without editing it. Source and dependency versions are
recorded in the ledger; replay should use that environment. Exact rates are for this declared
generator only and their Monte Carlo intervals are calculated with
[SciPy's exact binomial method](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).
