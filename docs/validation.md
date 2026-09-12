# Ongoing validation: M38

**Development only. The protocol is draft, and the target stage is not authorized.**
The [M37 audit](milestones/M37-RESULTS.md) remains the source for current research claims.
M38 aims to test a future outcome-isolated extraction and evaluation procedure; code and
synthetic experiments do not retroactively make the original analysis independent.

## Development evidence

| Work | Read next | Boundary |
|---|---|---|
| Generic injection, template-chain contracts, selection, calibration, and provenance | [Control-development checkpoint](milestones/M38-CONTROL-DEVELOPMENT.md) | Infrastructure and toy simulations, not validated observational analysis |
| Target-free runtime prototype | [Runtime evidence](milestones/M38-CONTROL-RUNTIME-EVIDENCE.md) | Restricted identity probe, not a science-ready image |
| Recovery-interval coverage pilot | [Selection coverage](milestones/M38-SELECTION-COVERAGE-PILOT.md) | Response-level simulations show undercoverage; no adopted replacement |
| Exact homogeneous Gaussian reference cases | [Interval benchmark](milestones/M38-INTERVAL-BENCHMARK.md) | More bootstrap draws alone do not repair the observed undercoverage |
| Unequal blocks, heterogeneous errors, and heavier-tailed noise | [Heterogeneous interval stress](milestones/M38-HETEROGENEOUS-INTERVALS.md) | Response-level undercoverage persists; no production estimator adopted |
| Actual VIPER synthetic template-builder/fitter bridge | [Engineering results](milestones/M38-VIPER-SYNTHETIC-BRIDGE.md) and [initial plan](milestones/M38-REAL-ADAPTER-NEXT-STEP.md) | Fixed-step, one-chunk reduced-1D probe; not a converged production adapter or raw-detector validation |
| Observational control suitability | [Candidates](milestones/M38-CONTROL-CANDIDATES.md) and [evidence follow-up](milestones/M38-CONTROL-EVIDENCE-FOLLOWUP.md) | Metadata and possible resources do not establish suitable RV truth |

## Remaining sequence

1. Extend the completed minimal VIPER probe: diagnose its near-zero covariance failure, add
   synthetic tellurics and model mismatch, and integrate native templates into the chain
   contracts with a reviewed convergence criterion. The first disjoint-split test passes
   engineering signal-transmission and isolation checks, not those broader requirements.
2. Broaden uncertainty calibration beyond matched homogeneous Gaussian simulations, with
   realistic dependence, model mismatch, failed-order handling, and full adaptive selection.
3. Establish suitable observational controls and independently justified truth, not just
   archive availability or a quiet-looking series.
4. Resolve and review the [protocol decision register](milestones/M38-PROTOCOL-DRAFT.md#12-blocking-decision-register),
   freeze the scientific choices and runtime, and establish the required independent roles.
5. Only then evaluate the target under the approved regime and outcome language.

No component may be smoke-tested on CD-35 raw/reduced spectra or fitted templates before
those gates. A coding-agent audit is software review, not the principal-disjoint scientific
governance required by the protocol. See the [evidence index](evidence/README.md) for retained
development records and the [milestone index](milestones/README.md) for the longer history.
