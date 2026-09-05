# M34 — Historical configuration-sensitivity check of the CD-35 RV extraction

> **Interpretation corrected for the v0.1.0 release preparation.** The historical numerical
> results below are preserved, but the earlier verdict that the method was "not overfitted"
> is withdrawn. A period appearing in several configurations from a family explored using
> the published RVs cannot rule out tuning artifacts. This is a development-data sensitivity
> check, not independent validation. [`M37-RESULTS.md`](M37-RESULTS.md) controls the scientific
> interpretation: the near-171-day result is conditional on the internal 17-of-18-night screen;
> all 18 nights are compatible with noise in the BERV-adjusted global searches.
>
> The earlier nine-companion, three-setting, both-mode transfer claim is also withdrawn.
> M37 identifies eta Tel B as the strongest clean same-setting nodding control; the HiRISE
> slit-recipe and host-dominated beta Pic results do not establish the claimed transfer.
> Historical 99–101% injection recovery measured fitter-stage transmission using already-built
> templates. It cannot validate signal survival during template construction or exclude
> extraction tuning effects.

Matthew asked whether the raw-to-RV pipeline was overfitted on Hoy et al.'s published RVs.
The historical manuscript described rms against the published series as the scoring metric
for extraction choices, including order set, template iteration, clipping, and oversampling.
The candidate RVs were extracted from spectra, but their agreement with published RV values
was used to guide configuration selection.

Published velocity values do not enter the downstream least-squares period fit. That narrower
fact does not make the workflow blind or independent: its input series was selected using
those values, and its historical search uses published epochs and a hard-coded window around
the published period. The internal epoch screen is computed from our measurements, but its
use also conditions the reported result. M37 documents these distinct dependencies.

## 1. The test

A configuration sweep already existed on disk: `M13_A`…`M13_J` and the `M14_*` variants,
twenty-one RV series from the same spectra under different configurations. For each,
`scripts/injection/m34_overfit_test.py` applies the internal spread screen and computes:

- **rms against the published series** — the metric that *selected* the adopted configuration
- **ΔBIC near 171 d** — the result that configuration was used to obtain

and asks whether near-171-day support appears only in the configurations that best match Hoy.

This comparison describes sensitivity within the retained configuration family. Neither
concentration in the best-matching configurations nor persistence outside them identifies
the cause of a peak. The configurations share data and development history, and their
retained epoch counts differ. The test has no calibration that would turn its correlation
or counts into a probability of overfitting.

The historical calculation re-scored existing runs; it did not re-reduce the spectra. No
new target calculation was performed for this interpretation correction.

## 2. Result

```
config         n  rms_pub   best P    dBIC   P@171    dBIC   rank
M13_A         18      279      6.3     8.3   166.6    -3.3   1253
M13_B         17      211    115.9    18.2   175.7   +17.1     32
M13_C         18      222    165.0    10.2   165.0   +10.2      1
M13_D         17      161      6.4    12.3   171.6    +9.5     16
M13_E         17      209    114.9    17.6   175.1   +11.8     83
M13_F         17      197    114.2    15.0   173.6   +14.9      7
M13_G         17      147    365.2     7.9   171.4    +2.8     31
M13_H         17      240      7.7     7.9   171.6    -0.3    354
M13_I         17      196    115.7    13.8   175.5    +9.4     85
M13_J         18      202      8.1     8.0   182.0    -1.6    894
M14_IPag      16      241      6.4     8.8   178.7    +3.1    111
M14_IPg       17      147    365.2     7.9   171.4    +2.8     31
M14_IPmcg     17      163      9.7    10.0   175.5    +2.4    144
M14_IPsg      17      226    116.8    13.5   178.5   +13.2     18
M14_NODALL    34      163     15.0     8.1   171.2    +4.4    126
M14_NODT2     34      141    171.2    43.8   171.2   +43.8      1
M14_T2        17      144    167.8    23.8   167.8   +23.8      1
M14_O2        17      133      8.5    10.5   171.4    +3.0     34
M14_O4        17      163    365.7     7.1   172.0    +4.9     10
M14_O8        18      180      8.0     5.5   182.0    -3.6   1348
M14_nod       10      200     77.2     1.1   182.0    +0.2   1554
```

**Historical consistency check against M14:** `M14_T2` returns ΔBIC **+23.8 at P = 167.8,
rank 1**, matching M14 §6 for that configuration. This checks agreement between the two
calculations; it does not independently validate their statistical interpretation.

| quantity | value |
|---|---|
| configurations tested | 21 |
| rms against published | 133–279 m/s (factor 2.1) |
| ΔBIC near 171 d | −3.6 to +43.8 |
| **correlation(rms_pub, ΔBIC@171)** | **−0.31** |
| worst-matching half showing ΔBIC > 10 | **5 of 10** |

## 3. Reading it

Five of the ten configurations with worse-than-median agreement still have ΔBIC > 10 near
171 days. Only three configurations put that period at rank 1 (`M13_C`, `M14_T2`,
`M14_NODT2`). The observed correlation is −0.31. These are descriptive results within this
sweep; a ΔBIC threshold here is not a calibrated detection test.

Every configuration belongs to a family explored using the published RVs. Shared spectra,
template choices, epoch screens, and family selection can affect all of them. Persistence
of a peak in configurations with poorer published-RV agreement therefore cannot establish
that the peak is astrophysical or bound the contribution of tuning. The earlier claims
that a manufactured signal would disappear in these configurations, or that the observed
correlation is an established null expectation, were not demonstrated by this test.

M37 supplies the controlling complete-versus-screened comparison for the adopted series:
the screened 17-night near-171-day peak has nominal BERV-adjusted global permutation
probabilities below 0.01, while all three complete 18-night combinations have probabilities
above 0.05. Those probabilities assume exchangeable fitted residuals and do not account for
choosing the screen. The present sweep does not remove either limitation.

> **Historical M36 attempt, 2026-08-24:** [`M36-RESULTS.md`](M36-RESULTS.md) reported 36
> configurations and an inconclusive selection: the gate constrained slope without its
> uncertainty, and no slope uncertainty was better than ±0.48. M37 subsequently established
> that the run did not faithfully execute its preregistration: fixed settings were omitted,
> injection/reference scores used different order sets, scores were rounded, and cached
> artifacts were not bound to inputs and configuration. Its injection plan encoded the
> published orbit, so the configurations and search cannot be described as a completed
> paper-blind experiment. The proposed template explanation remains unestablished; the
> historical artifact cannot answer the independence question. M38 is successor development,
> not a completed independent validation of this target.

## 4. ⚠ The first version of this test said the opposite, and it was wrong

Round 1 announced *"the detection tracks the tuning metric… the reproduction cannot be claimed
as independent."* That diagnosis used a calculation inconsistent with M14: the adopted
configuration came out at ΔBIC ≈ 0 where M14 had measured +24.8. The discrepancy prompted a
check of the implementation. Correcting it restored a comparable calculation; it did not
establish independence or show that tuning effects are absent.

The cause was that the period search had been **reimplemented here instead of imported**, for a
reason given as "to avoid a dependency", when `blind_search.py` takes a filename. The
reimplementation changed the order combination and fitting/scoring convention:

| | this project | round 1 |
|---|---|---|
| order combine | **median across per-order RVs** | viper's own `RV` column |
| fit | **unweighted** | inverse-variance from `e_RV` |
| score | **BIC = n·log(RSS/n) + k·log(n)** | χ² + k·log(n) |

The historical comparison reported `e_RV` values of 400–1000 m/s versus an estimated epoch
precision of 70–90 m/s. The different error treatment changes the score; agreement with M14
does not itself establish that either uncertainty model is calibrated.

The fix was to stop duplicating and start importing. `blind_search.py` cannot be imported —
it reads `sys.argv[1]` at module level — so the function's **source is extracted and executed**,
giving one definition and one behaviour, with a loud failure if it ever moves.

The implementation lesson is to compare like calculations and check against a reference
case before interpreting a discrepancy. Reusing the reference function addresses numerical
consistency; scientific validity still requires the separate scope and calibration checks
documented by M37.

## 5. Publication scope

The historical milestone prompted disclosure of extraction tuning in the manuscript. For a
qualified software/reanalysis release, this table is retained as a record of configuration
sensitivity, with M37's corrections governing its interpretation. It provides neither an
independent reproduction of the satellite claim nor broad validation of the extraction
method. The raw-to-RV provenance gaps and the incomplete successor validation remain as
documented in M37 and M38.
