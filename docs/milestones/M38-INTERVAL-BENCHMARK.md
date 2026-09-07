# M38 paired interval benchmark — development only

> **NO TARGET DATA / NO SCIENTIFIC METHOD ADOPTION / NOT PREREGISTERED**

The previous [coverage pilot](M38-SELECTION-COVERAGE-PILOT.md) found that the candidate
percentile-bootstrap recovery interval undercovers for season-correlated errors, even when
the six true independent blocks are correctly labeled. This follow-up distinguishes finite
bootstrap precision from a small-number-of-independent-blocks problem. It does not validate
spectra, templates, estimated measurement uncertainties, an adaptive selector, or a satellite.

## Design recorded before execution

The [plan](../evidence/m38-interval-benchmark-plan-2026-09-07.json) specifies two homogeneous
Gaussian cases: 24 independent nights and 24 nights sharing errors within six four-night
seasons. Each has 1,000 fresh independent noise trials. This is a local development plan
written after the earlier pilot, not an immutable human-reviewed science preregistration.

Every trial reuses the same generated responses across methods. The production scorer and
bootstrap estimator run at 199 and 1,999 repetitions with a common per-label seed; the code
requires exact equality of the shorter run's draws and statistics to the longer run's prefix.
The season case also compares incorrect night labels with correct season labels. Those two
labelings share data, but their physical resamples are not paired. Every interval is retained,
including failures, with coverage denominators based on all planned trials.

Two diagnostic benchmarks use the **true** independent blocks: a known-variance Gaussian
interval and a Student-t interval on equal-size block slopes. Their exactness is limited to
this known Gaussian model, symmetric injection design, fixed marginal weights, equal block
sizes, and no attrition. Neither is proposed here as a production replacement.

Only true slope one is simulated. In this design, translating the true slope translates all
fitted and bootstrap slopes while leaving widths unchanged. This coverage equivalence does
not hold automatically with nonlinear extraction, estimated weights, missing orders, or
general time-dependent signals. No equivalence-gate or false-positive claim is made here.

## Exact benchmark derivation

The generator is unchanged from the pilot:
`y[j,e,o] = (beta + b[e])*x[j] + a[e] + epsilon[j,e,o]`.
The standard deviations of `b`, `a`, and `epsilon` are `tau`, `omega`, and `sigma` in the
plan. Slope and offset errors are shared within each true independent block and across
injections/orders. Order noise is independent. The supplied marginal uncertainty is known.

This reduction is a project-specific derivation, not a claim copied from a reference:

- `w[j] = 1 / (tau^2*x[j]^2 + omega^2 + sigma^2)`;
- `S = sum_j w[j]*x[j]^2`, and `c[j] = w[j]*x[j] / S`;
- symmetry gives `sum_j w[j]*x[j] = 0`, so shared offsets cancel;
- each night's WLS slope is `beta + b[e] + sum_j c[j]*mean_order_noise[j,e]`;
- the production global WLS slope is the mean of those night slopes;
- with `n` nights, `O` orders, and `G` equal-sized independent blocks, its known variance is
  `tau^2/G + (sigma^2/O) * sum_j c[j]^2/n`.

The Gaussian interval uses this variance. Independent equal-sized block slopes are iid
Gaussian, so their mean has the usual Student-t interval with `G-1` degrees of freedom and
sample standard deviation divided by `sqrt(G)`. The benchmark imports the production WLS
fit for block slopes and verifies that their mean matches the production global point fit.
An independent full covariance-matrix projection tests the reduced variance formula.

NIST gives the [known-variance normal mean interval](https://www.itl.nist.gov/div898/handbook/prc/section1/prc14.htm)
and the [Student-t mean interval](https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm).
Those references support the interval formulas, not the instrumental realism of our generator.

## Reporting rules

- Coverage rates carry pointwise exact binomial Monte Carlo intervals; none are simultaneous
  across methods. Benchmarks are not required to hit exactly their nominal coverage in a
  finite sample, and passing this simulation is not a certification rule.
- Paired comparisons retain all four joint coverage counts and the second-minus-first
  empirical coverage difference. Independent-binomial error bars are not subtracted.
- The variance diagnostic uses sample variance with `ddof=1`, not mean squared error about
  the true slope. Its ratio to oracle variance is compared with the declared pointwise
  chi-square reference envelope with `trials-1` degrees of freedom.
- The entire declared design is run without interim stopping or adding a favorable case.
  Technical exceptions abort rather than emit a nominally complete report. Source hashes
  are checked at import, before/after workers, and after the study. Local hash checks are not
  a secure immutable runtime or an independent observer-blind experiment.
- Production selection code, target access, control eligibility, and scientific thresholds
  remain unchanged regardless of results.

## Reproduce

```sh
PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 python -m scripts.m38_interval_benchmark \
  --plan docs/evidence/m38-interval-benchmark-plan-2026-09-07.json \
  --output /tmp/m38-interval-benchmark-replay.json --workers 2
```

One or two workers yield the same scientific ledger; the output path must be new. The
code reads only its explicit plan and source identities, plus generated synthetic arrays.

## Results

The complete [paired trial ledger](../evidence/m38-interval-benchmark-result-2026-09-07.json)
is retained. The block below is generated from validated trial records, not transcribed.

<!-- BEGIN GENERATED M38 INTERVAL BENCHMARK -->

Plan SHA-256: `f72006b821618f2d09363c4f61497492b1388cd7d8fa6a3742ba756f2151418f`.
Retained 2,000 independent noise trials. Methods within a trial are paired, not additional independent evidence.

All coverage intervals below are pointwise 95% exact binomial Monte Carlo intervals.

| Case | Method | Complete / planned | Coverage % [MC interval] | Mean width |
|---|---|---:|---:|---:|
| independent-24 | oracle-normal | 1000/1000 | 94.5 [92.9, 95.8] | 0.20030 |
| independent-24 | independent-block-t | 1000/1000 | 93.8 [92.1, 95.2] | 0.20678 |
| independent-24 | percentile-night-199 | 1000/1000 | 91.3 [89.4, 93.0] | 0.18622 |
| independent-24 | percentile-night-1999 | 1000/1000 | 92.0 [90.1, 93.6] | 0.19109 |
| six-seasons-24 | oracle-normal | 1000/1000 | 94.8 [93.2, 96.1] | 0.40021 |
| six-seasons-24 | independent-block-t | 1000/1000 | 93.9 [92.2, 95.3] | 0.49843 |
| six-seasons-24 | percentile-night-199 | 1000/1000 | 56.8 [53.7, 59.9] | 0.16922 |
| six-seasons-24 | percentile-night-1999 | 1000/1000 | 58.5 [55.4, 61.6] | 0.17282 |
| six-seasons-24 | percentile-season-199 | 1000/1000 | 84.3 [81.9, 86.5] | 0.33540 |
| six-seasons-24 | percentile-season-1999 | 1000/1000 | 85.8 [83.5, 87.9] | 0.34127 |

Paired coverage changes (second minus first; percentage points):

| Case | First -> second | Neither | Second only | First only | Both | Change |
|---|---|---:|---:|---:|---:|---:|
| independent-24 | percentile-night-199 -> percentile-night-1999 | 76 | 11 | 4 | 909 | +0.7 |
| six-seasons-24 | percentile-night-199 -> percentile-night-1999 | 407 | 25 | 8 | 560 | +1.7 |
| six-seasons-24 | percentile-season-199 -> percentile-season-1999 | 138 | 19 | 4 | 839 | +1.5 |
| six-seasons-24 | percentile-night-1999 -> percentile-season-1999 | 142 | 273 | 0 | 585 | +27.3 |

Known-variance diagnostic (sample variance uses `ddof=1`):

| Case | Mean slope | Sample variance | Oracle variance | Ratio | Reference envelope |
|---|---:|---:|---:|---:|---:|
| independent-24 | 1.00102 | 0.0026630 | 0.0026111 | 1.0199 | [0.9142, 1.0896] |
| six-seasons-24 | 1.00054 | 0.0106436 | 0.0104236 | 1.0211 | [0.9142, 1.0896] |

<!-- END GENERATED M38 INTERVAL BENCHMARK -->

## Interpretation and decision

**More bootstrap draws do not resolve the observed coverage failure.** The larger draw count
modestly increases coverage and mean width in each paired comparison, but every percentile
method's pointwise Monte Carlo interval remains below nominal coverage. This is not a claim
of zero finite-bootstrap error, nor an extrapolation to infinitely many draws. It shows that
the tenfold increase tested here is not an adequate remedy.

**Correct independent units are essential, but do not suffice for this percentile method.**
The wrong night labels in the season case severely underestimate uncertainty. Correct labels
make a much larger difference than the tested increase in draws, yet six independent blocks
still give substantial undercoverage. Even the independent-night case has detectable
undercoverage in this larger pilot.

**The restricted exact benchmarks behave consistently with the declared generator.** Their
pointwise Monte Carlo intervals include nominal coverage, and the empirical-to-oracle variance
ratios fall within the predeclared reference envelope. Neither benchmark is required to land
at exactly the nominal percentage in a finite ensemble. The block-t method estimates scale
from the simulated independent blocks, whereas the oracle-normal interval is deliberately
given otherwise unavailable true covariance. Their performance is not transferable proof for
estimated instrumental errors, non-Gaussian/systematic noise, uncertain block definitions,
unequal blocks, or adaptive selection.

A future frozen target protocol therefore still cannot adopt the current percentile method on the
strength of either pilot. A true-block Student-t approach is worth comparing in broader
control simulations; it is **not adopted into production here**. The next comparison should
explicitly break the convenient assumptions—unequal/uncertain blocks, asymmetric or varying
injection banks, estimated weights, and non-Gaussian errors—and retain separate diagnostics
for response transmission and reference-RV correctness.

For the next physical validation layer, the source-inspected
[reduced-1D VIPER adapter design](M38-REAL-ADAPTER-NEXT-STEP.md) identifies a wholly synthetic
path through the actual fitter and template builder. Its initial deliverable is not a raw
detector extraction test, a selected observational control, or permission to open the target.

## Verification

The independent pre-run agent audit checked the mathematical reduction, generator reuse,
same-data comparisons, exact bootstrap-prefix assertion, covariance projection, Student-t
degrees of freedom, variance denominator, and the complete declared method roster. All
**416** M38 tests pass on WSL with warnings treated as errors, including the **20** benchmark
tests that also pass on Windows. Worker-count equivalence is tested on synthetic fixtures.

The evidence renderer recomputes all summaries, known benchmark intervals, coverage/width
semantics, failure counts, and seed/identity rosters. Structure, integer counts, and booleans
match exactly; numerical summaries permit relative tolerance `1e-10` and absolute tolerance
`1e-12` for cross-version solver roundoff. It checks source hashes against the executing
checkout. This is reproducibility/accounting verification, not a cryptographic proof of
external execution or an external RV specialist's scientific approval.

The final independent audit validated every method's retained coverage counts, summaries,
source identities, and interval semantics; checked the oracle against the full WLS
covariance matrix; and replayed trials 0, 499, and 999 in both cases. The final interpretation
was checked against the ledger. See the
[verification record](../evidence/m38-interval-benchmark-verification-2026-09-07.json).

Regenerate or check the complete numerical block with:

```sh
PYTHONPATH=src:. python -m scripts.m38_render_interval_benchmark \
  --result docs/evidence/m38-interval-benchmark-result-2026-09-07.json \
  --document docs/milestones/M38-INTERVAL-BENCHMARK.md --check
```
