# M38 heterogeneous interval stress — development only

> **NO TARGET DATA / NO METHOD ADOPTION / NOT PREREGISTERED**

This response-level experiment extends the
[homogeneous Gaussian benchmark](M38-INTERVAL-BENCHMARK.md). It deliberately breaks
equal block sizes, homogeneous errors, symmetric injection velocities, and Gaussian noise.
It does not inject spectra, rebuild templates, validate a real extraction, choose a production
uncertainty estimator, or establish an independent confirmation.

## Fixed development design

The [plan](../evidence/m38-heterogeneous-intervals-plan-2026-09-12.json) was written before
the ensemble ran, following the earlier benchmark. This is a local development record, not an
immutable preregistration or independent observer-blind design. The complete declared design
ran without interim stopping, dropping cases, or selecting a favorable method.

Each of three cases has 500 fresh independent noise trials. Each trial supplies the **same
responses** to all three interval methods; 4,500 intervals are not 4,500 independent trials.
Data and bootstrap streams have separate content-derived seeds, recorded for every trial.
All cases have six correctly identified independent blocks, 24 epochs, four orders, true
response slope one, and five injections per epoch. There is no order attrition.

| Case | Independent block sizes | Block scales | Velocities (m/s) | Noise |
|---|---|---|---|---|
| equal-gaussian | 4, 4, 4, 4, 4, 4 | all 1 | -800, -400, 0, 400, 800 | Gaussian |
| unequal-heterogeneous-asymmetric-gaussian | 1, 2, 3, 4, 6, 8 | 0.4, 0.6, 0.9, 1.3, 1.8, 2.5 | -800, -250, 0, 400, 1100 | Gaussian |
| unequal-heterogeneous-asymmetric-t5 | same unequal sizes | same heterogeneous scales | same asymmetric bank | independent Student-t(5), scaled to variance one |

This is a **compound stress comparison**, not a factorial attribution study: a change from the
baseline cannot be assigned uniquely to unequal sizes, heterogeneity, or injection asymmetry.
Gaussian and t5 cases have the same true covariance but independent noise realizations; only
methods **within** a trial are paired. Larger/noisier blocks are intentionally coupled in the
stress geometry. Other couplings may perform differently.

## Generator and exact covariance calculation

For epoch `e` in independent block `g`, injection `j`, order `o`, and block scale `s[g]`:

```text
y[e,j,o] = (beta + tau[e]*z[g])*x[j] + omega[e]*u[g] + sigma[e]*epsilon[e,j,o]
tau[e]   = 0.25 * s[g]
omega[e] = 80 m/s
sigma[e] = 40 m/s * sqrt(s[g])
```

The slope and offset variates are independent of each other and of all order noise.
They are shared within a block and across injections/orders. Gaussian variates have unit
variance. The t5 case uses `t5 * sqrt(3/5)` for **all** variates, also giving unit variance.
[SciPy's Student-t documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html)
defines the distribution and its scale/quantile API; this instrument-free generator is ours.

The production scorer receives exact marginal per-order response standard deviations
`sqrt((tau*x)^2 + omega^2 + sigma^2)`. It uses its existing across-order mean uncertainty
bound, not a newly substituted independence-aware error bar. The actual order-mean independent
noise variance in the oracle is `sigma^2 / 4`. Shared block errors do not average down over
orders. These supplied weights are known, fixed, and not fitted from a noisy spectrum.

The diagnostic obtains the global WLS slope coefficients `c[e,j]` from the full two-column
intercept/slope design, and checks their projection against the production point estimate in
every trial. Its covariance formula is:

```text
A[g] = sum_(e in g,j) c[e,j] * x[j] * tau[e]
B[g] = sum_(e in g,j) c[e,j] * omega[e]
Var(beta_hat) = sum_g (A[g]^2 + B[g]^2)
               + sum_(e,j) c[e,j]^2 * sigma[e]^2 / number_of_orders
```

This is a direct linear-model derivation. Unit tests independently construct the full
observation covariance matrix and check `c' Sigma c` against the reduced expression in all
three cases. Unlike the symmetric homogeneous benchmark, blockwise offset contributions
do not vanish in the asymmetric, nonproportionally heterogeneous design; this is explicitly
tested. The formula remains a correct **variance** in the t5 case, but a normal quantile is
not thereby an exact finite-sample confidence procedure.

## Methods and distinct centers

- `production-block-percentile`: the actual production scorer and cluster-bootstrap
  estimator, with 199 repetitions and the true six independent block labels. It retains the
  weighted global point estimate and unchanged production computation. No replacement fast
  approximation is used.
- `known-covariance-normal`: the same global WLS point estimate plus/minus the normal
  quantile times the **known true** standard deviation. This is exact under the declared
  Gaussian model, not in general for t5 errors and not for unknown instrumental covariance.
- `unweighted-block-t`: compute each block's WLS slope using the production line fit, then
  use their unweighted mean plus/minus a Student-t quantile with five degrees of freedom
  times their sample standard deviation divided by `sqrt(6)`. It is exact only for the
  baseline's iid Gaussian block slopes. It is a heuristic diagnostic in both stress cases.

All centers estimate the same population slope `beta` under these mean-zero models, but
**the unweighted block mean is not the production weighted slope under stress**. Its wider
intervals cannot be described as merely correcting the production estimator's uncertainty.
The ledger retains both centers and every individual block slope. Neither the block-t method
nor the oracle is installed into production or adopted for selection.

## Results

The [complete ledger](../evidence/m38-heterogeneous-intervals-result-2026-09-12.json) retains
all 1,500 trials. Every planned interval completed; there were no unrun or failed bootstrap
repetitions. Absent intervals would count as non-covering in the all-planned denominator;
mean width is explicitly conditional on completion. Technical exceptions abort the run.

The table below is generated by the driver's `--check` command. Brackets are pointwise 95%
Clopper-Pearson Monte Carlo intervals, using
[SciPy's exact binomial interval](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).
They are not simultaneous across methods/cases and do not represent uncertainty about the
scientific realism of the generator.

<!-- BEGIN GENERATED M38 HETEROGENEOUS INTERVALS -->

| Case | Method | Complete/planned | Coverage % [pointwise MC interval] | Mean width |
|---|---|---:|---:|---:|
| equal-gaussian | known-covariance-normal | 500/500 | 94.8 [92.5, 96.6] | 0.40033 |
| equal-gaussian | unweighted-block-t | 500/500 | 96.0 [93.9, 97.5] | 0.49372 |
| equal-gaussian | production-block-percentile | 500/500 | 85.4 [82.0, 88.4] | 0.33133 |
| unequal-heterogeneous-asymmetric-gaussian | known-covariance-normal | 500/500 | 94.0 [91.5, 95.9] | 0.45010 |
| unequal-heterogeneous-asymmetric-gaussian | unweighted-block-t | 500/500 | 96.8 [94.9, 98.2] | 0.72032 |
| unequal-heterogeneous-asymmetric-gaussian | production-block-percentile | 500/500 | 83.8 [80.3, 86.9] | 0.41872 |
| unequal-heterogeneous-asymmetric-t5 | known-covariance-normal | 500/500 | 94.6 [92.2, 96.4] | 0.45010 |
| unequal-heterogeneous-asymmetric-t5 | unweighted-block-t | 500/500 | 97.2 [95.3, 98.5] | 0.67234 |
| unequal-heterogeneous-asymmetric-t5 | production-block-percentile | 500/500 | 84.2 [80.7, 87.3] | 0.38619 |

<!-- END GENERATED M38 HETEROGENEOUS INTERVALS -->

The production percentile interval still undercovers substantially with the true blocks:
each displayed Monte Carlo interval lies below nominal 95% coverage. The tested additional
complexity does not repair the known failure. These data do not establish which stressor
causes a coverage difference from baseline, or estimate performance on actual spectra.

The known-covariance diagnostic is consistent with nominal coverage in these finite
ensembles. In the t5 case this is an empirical result at one noise law/design, **not a new
exactness claim**. The unweighted block-t method is much wider and is conservative in this
realization of the t5 experiment (its pointwise Monte Carlo interval is above 95%). That is
not uniform coverage assurance or evidence that it will provide useful equivalence-gate
sensitivity. A generator change can invalidate that behavior.

**Decision: no estimator, equivalence margin, minimum-block threshold, or production rule is
adopted.** The current percentile method remains unqualified for a frozen target protocol.

## Reproduce and verify

From a source checkout with the scientific dependencies available:

```sh
PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 python -m scripts.m38_heterogeneous_intervals \
  --plan docs/evidence/m38-heterogeneous-intervals-plan-2026-09-12.json \
  --output /tmp/m38-heterogeneous-intervals-replay.json

PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 python -m scripts.m38_heterogeneous_intervals \
  --check docs/evidence/m38-heterogeneous-intervals-result-2026-09-12.json
```

The output must be a new path. The driver reads only its explicit development plan/source
identities and generated synthetic responses. `--check` verifies source/plan identities,
case/trial/seed rosters, all interval event semantics, Gaussian and block-t constructions,
and all table summaries, and replays trials 0, 250, and 499 in each case. This is accounting
and reproducibility checking, not independent scientific approval or a secure file-access
sandbox. Source hashes are bound at import and checked before/after the ensemble.

The 22 new tests pass on both Windows Python 3.13 and WSL Python 3.12 with warnings treated
as errors. Ledger checks and nine full production-bootstrap replays also pass in both
environments. Counts/booleans/identities are exact; floating calculations allow `rtol=1e-10`
and `atol=1e-12` for cross-version solver roundoff. The retained run used NumPy 2.4.3 and
SciPy 1.17.1; the environment is recorded in the ledger.

A [separate coordinating-agent audit](../evidence/research-navigation-verification-2026-09-12.json)
checks all retained interval/accounting summaries, Monte Carlo limits through an independent
beta-quantile calculation, and full covariance/WLS projections. Its regression tests are
`tests/test_m38_heterogeneous_intervals_audit.py`. This is additional engineering review,
not independent human protocol approval.

## Remaining calibration and observational prerequisites

Next experiments need independently estimated/misspecified weights, uncertain block labels,
varying injection banks, structured non-Gaussian errors, useful attrition, and both interval
coverage and equivalence-gate sensitivity. These three compound response cases are not an
exhaustive calibration grid. The next real-template bridge must validate physical signal
transmission separately from reference-RV correctness; neither task is solved by a linear
response simulation. Full adaptive pipeline false-positive and detection-completeness
ensembles remain separate requirements.

The [control evidence follow-up](M38-CONTROL-EVIDENCE-FOLLOWUP.md) still establishes no ready
same-setting observed positive control and no verified H1567 null-standard series. Eta Tel B
is a transfer candidate, not independently proven stable truth. GJ 229 component velocities
are not the expected single-template blended centroid. The required control truths, protocol
decisions, independent roles, freeze, and review in the
[draft protocol](M38-PROTOCOL-DRAFT.md) remain unresolved. No observational spectra, templates,
target files, or target-stage runner were accessed by this experiment.
