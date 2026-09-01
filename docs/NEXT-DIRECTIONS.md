# Where this project goes next

The existing queue (`docs/target-queue.md`) answers "where else do we point the
pipeline". This file answers a different question: **what else does the work we have
already done make possible** — including things that are not exomoon searches at all.

Ordered by (novelty x feasibility x reach), not by difficulty.

---

## A. New science from data already on disk

These need no new observations, no new downloads, and in two cases no new reduction.
They are the highest-value-per-hour ideas in this file.

### A1. The RV jitter floor of directly imaged companions — **ATTEMPTED, NOT ACHIEVABLE YET**

> **Result (2026-08-13, `scripts/injection/m29_jitter.py`): the idea is sound and the
> data cannot support it. Documented here rather than quietly dropped.**
>
> The measurement needs the epoch-to-epoch scatter split into measurement noise and
> astrophysical variability. Two noise channels were tried and both fail:
>
> - **Within-night frame scatter.** Frames of one night are minutes apart, so a
>   satellite orbit cannot move between them — pure noise, in principle ideal. But the
>   campaigns take only **~2 frames per night**, giving too few degrees of freedom. The
>   built-in control is informative but qualified: H26 reports K = 306 m/s for CD-35 2722 B
>   and the screened extraction here fits 426–472 m/s, while the all-18-night search fails.
>   Even this signal-bearing screened case resolves its excess at only **1.4σ**. A method
>   with so little power on its control
>   cannot certify a null, so every other object's "no excess" is a power failure, not
>   a physical result.
> - **Across-order dispersion.** Far more degrees of freedom, and invariant to
>   common-mode signal by construction — but on CD-35 it reads **1333 m/s** against a
>   272 m/s epoch-to-epoch scatter of the median, even after per-order centering. The
>   per-epoch order distribution is heavy-tailed, so a Gaussian σ/√N conversion
>   overestimates the error on the combined RV several-fold and drives every
>   significance negative.
>
> The machinery is not broken: β Pic b's known starlight contamination is resolved at
> 2.1–2.2σ in both channels. The excesses being sought elsewhere are simply smaller
> than the available power.
>
> **What it turned into — an observing-strategy result worth stating.** The binding
> constraint on measuring companion RV jitter is **frames per night, not nights**.
> Current campaigns take ~2; a decomposition needs ~6–10. That is a concrete, cheap
> change to any future OB and belongs in the proposal case (D1) and the methods paper
> (C1). Also banked: **η Tel B's 116–130 m/s epoch scatter is fully accounted for by
> its own within-night measurement noise**, needing no astrophysical jitter — which is
> a clean supporting sentence for the limit in Paper I.
>
> **To revive it:** a robust (heavy-tail-aware) per-order error model, or one campaign
> with 6+ frames per night.

*Original statement of the idea, kept for the record:*

**The gap.** Every proposal in this genre — including this project's own — guesses the
astrophysical RV noise floor of a young self-luminous giant. This project has not measured it,
because its apparent multi-epoch sample did not survive mode and spatial-resolution audit as
a homogeneous companion-RV set; any broader novelty claim requires a fresh literature review.

**The original premise.** Per-epoch scatter appeared to be in hand for ~11 companions
spanning M7 → L → T. The later HiRISE and spatial-profile audits narrowed that set: the
fibre observations reduced with a slit recipe are invalid, and an unresolved, host-dominated
extraction is not a companion RV even when its fitter-stage injection gate passes. Any revival
must first rebuild the eligible sample from verified nodding or fibre-appropriate reductions.

| object | per-epoch scatter | note |
|---|---:|---|
| YSES 1 b | 34 m/s | best of the campaign |
| HD 19467 B | 45 m/s | benchmark T dwarf |
| 2M0103AB b | 53 m/s | within-night |
| CD-35 2722 B | 70–90 m/s | screened ~171 d recovery; all-18 search fails |
| HIP 81208 B | 124 m/s | |
| eta Tel B | 127–129 m/s | |
| PDS 70 (star) | 130 m/s | accreting transition-disk host |
| HIP 65426 b | 131 m/s | |
| AB Pic b | 120–190 m/s | |
| HD 1160 B | 725 m/s | quality-limited, the outlier |

**The result.** Decompose scatter into photon noise (measurable), instrumental floor
(measurable from the injections), and the residual — which *is* the astrophysical
jitter. Regress the residual against spectral type, T_eff, log g, age and v sin i.

**Why it matters.** This converts a pile of null results into the single number that
decides whether companion-side exomoon RV is feasible at all, for anyone, ever. It is
the reference table the next decade of proposals will cite. And every input already
exists — this is analysis, not observation.

### A2. Companion–host relative radial velocities → orbital dynamics

Direct imaging gives sky-plane position; it cannot give the line-of-sight velocity that
breaks the orbit-orientation degeneracy. A single precise companion RV does (this is
how Ruffio et al. constrained HR 8799). The repository contains extracted systemic values
for multiple targets, but **they are not yet a catalogue of companion RVs**: HiRISE/slit
misclassifications and unresolved host-dominated spectra must be removed first. The viable
subset has not yet been audited for absolute zero-point accuracy.

Deliverable: a table of companion-minus-host radial velocities with uncertainties, and
per system what it does to the orbit posterior when combined with published astrometry.
Different science case, different audience (dynamics, not exomoons), same data.

### A3. A homogeneous v sin i catalog

The same H- and K-band spectra carry rotational broadening, and viper already forward-
models line profiles. Companion spin is an active formation diagnostic (spin–mass and
spin–age relations test accretion history). The sources reviewed here are predominantly
one-object-per-paper and use inconsistent methods; whether a homogeneous multi-object set
already exists needs a dedicated literature check before any novelty claim. Moderate
new work (a broadening fit alongside the RV fit), high citation surface.

### A4. CT Cha B's accretion variability

A 3.3σ deviant epoch on an accreting ~2 Myr companion, undecidable at n=3. Accreting
companions are rare and variable-accretion RV signatures are almost unstudied. Two more
epochs decide it — this is the one item here that needs telescope time, and it is a
cheap ask.

## B. Cheap external checks that strengthen the paper now

### B1. Photometric cross-check of the 171 d period — **DONE (M35)**

If CD-35 2722 shows a ~171 d **photometric** periodicity, the satellite has an activity
alternative and the paper's central claim is in trouble. A sufficiently sensitive null would
be supporting context, not proof of a nonstellar origin. ASAS-SN, ATLAS and TESS are public
and account-free, and the primary is bright.

> **Re-audited result (2026-08-31, `scripts/m35_asassn_photometry.py`,
> `data/m35-photometry-v2.json`): no 171.454 d photometric detection.** After per-camera
> centering and reduction to one effective datum per observing night, nominal night-permutation
> *p* = 0.13–0.16 across the host/filter rows, conditional on exchangeability of the final
> camera-corrected night bins. The two ASAS-SN source IDs are alternative
> aperture photometry of the same 2,173 timestamp/camera measurements, not independent
> replications. Injection recovery on nested deterministic grids of 720, 1440 and 2880 phases
> first reaches at least 90% phase recovery at K = 12/13/12/13 mmag across the four rows; the
> grid-resolved cross-series threshold is therefore **13 mmag semiamplitude (26 mmag
> peak-to-peak)**. At K = 5 mmag, only 43.2–44.2% of the finest-grid phases recover, and the
> maximum successive-grid fraction change over the curves is <0.0007. These are numerical
> uniform-phase fractions conditional on one observed-noise realization, the preprocessing and
> an estimated fixed-period permutation threshold—not binomial samples or confidence bounds.
> A photometric null does not prove that the RV signal is nonstellar.

### B2. Gaia astrometric cross-check -- **DONE (M35)**

RUWE, astrometric excess noise, and any non-single-star solution for CD-35 2722 A and
for every target carrying a limit. This is an inexpensive catalogue diagnostic for obvious
astrometric problems, not by itself an exclusion of unseen companions.

> **Result (2026-08-24, `scripts/m35_gaia_astrometry.py`, M35 §2).** CD-35 2722 has
> **RUWE 1.023** and no Gaia DR3 non-single-star solution; eta Tel likewise has RUWE 1.013.
> Not one of the 31 roster positions carries an NSS solution. This is catalogue context, not
> proof of no astrometric perturbation: CD-35 2722's excess noise is 0.099 mas and formally
> significant, and RUWE/NSS alone cannot exclude an unresolved companion. Six roster entries
> exceed RUWE 1.4; their brightness makes simple interpretation unsafe, so no claim rests on
> them.

## C. Method contributions with reach beyond this subfield

### C1. The methods paper — four ways this measurement goes wrong

Written entirely from milestones already banked, each with a worked example from real
data:

1. **A flat series is not a quiet series.** PDS 70's nine-night template returned −62%
   injection recovery: a template that lost its stellar lever produces beautiful,
   meaningless upper limits. Caught only by gating.
2. **A precision statistic invariant to its own signal.** The field's per-epoch
   dispersion (Eq. 1) is invariant to common-mode velocity by construction, and moved
   *against* this project's two largest real improvements.
3. **A search maximum is not a significance.** ΔBIC quoted as the peak of a 4000-period
   search, when a signal-free series with the same cadence reaches ΔBIC ≈ 19 five
   percent of the time. With the load-bearing BERV covariate included, the screened
   series has a nominal 5000-permutation global *p* of about 0.002–0.008; the plain-search
   range is about 0.0002–0.0006, not the BERV-adjusted result. Those values assume
   exchangeability of the fitted base-model residuals and are conditional on a post-hoc
   screen, so they are diagnostic rather than confirmatory false-alarm probabilities; the
   all-18-night BERV-adjusted values are 0.31–0.91.
4. **Sampler-internal evidence errors are not reproducibility.** In this dynesty analysis,
   seed-to-seed scatter is 1.1–8.1× the internal estimate on a real published RV table
   (§C2); that factor is not evidence about a different sampler.

### C2. Sampler reproducibility as a standalone note

Evidence ratios across the exoplanet literature are quoted with the sampler's internal
logZ uncertainty. Measured here on the published Nature table: empirical seed-to-seed
scatter is 1.1x, 3.3x and 8.1x the quoted error depending on model/prior configuration,
with paired comparisons spanning −1.7 to −8.9 in the broadest row while the internal
error is ~±0.27. The dataset comprises 82 paired model comparisons (164 nested-sampler
fits), not 82 individual sampler invocations. The result is specific to dynesty, this
likelihood and this dataset. Short, sharp, wide audience, code included. RNAAS-length.

### C3. A public "does your detection survive?" service

`m28_nullcal.py` generalized: upload an RV table, get back permutation-based nominal null
calibration with explicit exchangeability assumptions, a leave-one-out panel,
window-function/alias structure, and a
nuisance-covariate test. This is exactly the portfolio's stated thesis — the usability
layer between public archives and the people using them — and it turns the methods paper
from a lecture into a tool.

## D. Less adjacent

### D1. Isolated planetary-mass objects: where the contrast wall does not exist

This project established a hard spatial-resolution gate for slit extraction and measured a
few separation/contrast points; it did not measure a universal ~0.8″/2000× contrast wall.
**Free-floating planetary-mass objects have no host at all**, so they remove both starlight
contrast and slit-contamination terms while retaining young infrared spectra. That makes them
a promising companion-side-RV proposal class. The ESO archive sweep found no usable series;
the literature and novelty case still need to be checked before making a priority claim.

### D2. The contrast wall as an instrument-design curve

The audited separation/contrast/resolution points could seed an instrument-design surface,
but the contrast dependence between the resolved and unresolved regimes remains unmeasured.
Filling that gap could be actionable for HiRISE/KPIC/RISTRETTO and ELT instrument teams.

### D3. Systematic significance audit of published periodic detections

The machinery in C3 applied to a defined sample of published RV claims: how many quote a
search maximum as a significance? This is `IDEAS/reproduction-audit-fleet.md` with
working code and a demonstrated finding behind it. Provocative — needs care, and needs
the methods paper published first so it reads as method rather than accusation.

---

## Suggested execution order

1. **M38 control-only development and protocol freeze before new target science.**
   `data/repro/` now freezes the adopted M14/M15 RV/per-order/BERV/configuration products,
   VIPER source patch and hashes, and M37 regenerates the screened/all-18 CD-35 null from that
   bundle. Develop the pre-template injection operator, convergence metrics, paper-free period
   search and calibration, manifests, and information firewall only on simulations and the
   declared controls. Then resolve the M38 decision register, name the role-separated executor
   and custodian, independently review the protocol, and freeze it. Until those gates close,
   do not mount or inspect CD-35 raw/reduced spectra or templates and do not execute a
   claim-bearing target stage. Extending raw-to-template replay remains a separate
   reproducibility project and does not relax this barrier. The prose corrections do not by
   themselves make either science draft submission-ready.
2. ~~**B1, B2**~~ — **done, then re-audited.** The photometric null remains useful after
   nightly/camera-aware reanalysis; Gaia supplies catalogue context, not a proof of no
   perturbation. Use the qualified statements in §B, not the original M35 headlines.
3. **C1** — writes from banked milestones after the bundle audit.
4. **A2, A3** — new science, moderate new analysis.
5. Then the existing queue: YSES 1 b's blocked 2022 pair, beta Pic b's HiRISE nights,
   Keck/KOA (DH Tau B, HR 8799).

**Two items came off this ranking and are deliberately not in it.**

- **A1 is attempted and not achievable with the data in hand.** Its own section carries the
  result: ~2 frames per night is too few degrees of freedom, and even the screened,
  signal-bearing CD-35 control resolves its excess at only 1.4σ (the all-18-night search itself
  fails), so every other object's "no excess" is a power failure rather than a physical result. It stays written up because the
  negative is informative, but it was ranked third here as "the highest-value new result
  available without new observations" and that is no longer true.
- **C2 is blocked on a decision, not on work.** Its content is presently §5.1 of the
  manuscript, where `ONBOARDING.md` §6 records it as load-bearing and recommends **retiring**
  the standalone note for that reason. So the two documents want opposite things with the same
  material: publishing C2 separately means cutting §5.1 out of the manuscript and citing the
  note instead — one stronger paper traded for two thinner ones. **This is Matthew's call**,
  and until it is made neither document should be read as having settled it.
