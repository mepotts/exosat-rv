# exosat-rv

> **New here, or handing this to an agent?** Start with [`ONBOARDING.md`](docs/ONBOARDING.md) — environment, operating rules, the traps that cost a day each, and where every draft stands.

**Release preparation:** [`v0.1.0`](docs/releases/v0.1.0.md) is scoped as a development
software/reanalysis snapshot. Its [verification record](docs/releases/v0.1.0-verification.md)
tracks the release checks. This does not declare a published release, a validated general
extraction pipeline, or an independent confirmation of the satellite claim.

An independently implemented, paper-calibrated raw-to-radial-velocity workflow for
**directly imaged companions**, and what it finds when pointed at the one system where a
satellite has been reported.

Rather than observing the star, the spectrograph is pointed at the *companion* and its own
reflex motion is measured. Hoy et al. (2026, [Nature](https://www.nature.com/articles/s41586-026-10751-w);
[arXiv:2607.05193](https://arxiv.org/abs/2607.05193)) used VLT/CRIRES+ this way on the brown
dwarf **CD-35 2722 B** and reported a planetary-mass satellite. This project rebuilds the
measurement from the public raw frames with a separate implementation whose extraction
configuration was calibrated against the published RV series. The downstream fits do not
ingest the published RV values, but the historical search/reporting code is target- and
paper-aware, so this is not a blind or independent confirmation. The project also explored other
archival companions, but the clean transfer evidence is narrower than first reported: the
supposed staring-mode tier was HiRISE fibre data processed with the wrong slit recipe.

**Results.**

- The primary ~171 d signal is recovered **conditionally on an internal quality screen**.
  On the 17 retained nights, a target- and paper-aware downstream search whose model fits do
  not ingest the published RV values finds ~169–171 d and survives a barycentric nuisance
  term. A 5000-permutation rerun gives a nominal global *p* of about 0.002–0.008,
  conditional on exchangeability of the fitted base-model residuals and on the post-hoc
  screen; it is not a confirmatory false-alarm probability. With all 18 archival nights,
  the search degrades to noise; the excluded night is therefore load-bearing even though its
  across-order spread is objectively extreme.
- The reported **second** companion **does not reproduce under the models and priors tested
  here**: 81 of 82 paired evidence comparisons favour one companion. The measured dynesty
  seed scatter cannot establish the reproducibility of H26's different sampler.
- **η Tel B**: no detected signal; circular-orbit, grid-pointwise 90%-completeness limits of
  m sin i ≈ 0.51–1.27 M_Jup over P = 20–300 d, conditional on fitter-stage transmission.
- The strongest clean transfer is η Tel B in the same H1567 nodding configuration, at
  99–101% fitter-stage injection recovery. Transfer across both observing modes has not been
  demonstrated; the apparent staring-mode results were withdrawn after the HiRISE audit.
- A nightly and per-camera ASAS-SN reanalysis finds no host-star signal at 171.454 d
  (nominal night-permutation *p* = 0.13–0.16, conditional on exchangeability of the final
  camera-corrected night bins). Across nested deterministic grids of 720, 1440 and 2880 phases, the
  first sampled semiamplitude reaching at least 90% phase recovery on every grid is 12–13 mmag;
  the cross-series threshold is 13 mmag (26 mmag peak-to-peak), not the previously quoted
  5 mmag. The two source IDs are alternative aperture photometry of the same 2,173
  timestamp/camera measurements, not independent replications. This sensitivity is conditional
  on one observed-noise realization and an estimated fixed-period permutation threshold, not
  a binomial confidence bound. Gaia RUWE/NSS provide catalogue context but do not prove the
  host is astrometrically unperturbed.

**Papers** are in [`docs/paper/`](docs/paper/) — each `.md`/`.template.html` is the source
and the matching `.html` is a rendered build product.

**Running it.** [`scripts/cr2res/`](scripts/cr2res/) drives the reduction from raw frames;
[`scripts/injection/`](scripts/injection/) holds the injection harness and the period
search; [`data/published/`](data/published/) carries the transcribed reference table with
provenance headers.

The adopted M14/M15 RV, per-order, BERV, parameter and target tables, the VIPER configuration
and tracked source patch observed in the audited checkout, and a hash manifest are frozen under
[`data/repro/`](data/repro/). That configuration records checkout state only; it does not prove
which configuration governed the historical extraction runs. Raw/reduced ESO spectra and the
fitted templates remain external; the templates and FTS atlas are hash-bound in the manifest.
The bundle supports offline downstream reanalysis, not a raw exposure-to-template replay.

Everything runs on a laptop against public archives. See [`SPEC.md`](docs/SPEC.md) for the thesis,
[`DATA-SOURCES.md`](docs/DATA-SOURCES.md) for endpoints and their known incompletenesses, and
[`BUILD-PLAN.md`](docs/BUILD-PLAN.md) for the milestone plan.

**Current state: results through M37, plus an unexecuted M38 successor-protocol draft.** Start at [`docs/LESSONS.md`](docs/LESSONS.md) — the consolidated
trap catalog and the map of which milestone document owns which conclusion — then
[`docs/HANDOFF.md`](docs/HANDOFF.md) and the roster ledger
[`docs/target-queue.md`](docs/target-queue.md). The milestone records are indexed
in [`docs/milestones/`](docs/milestones/README.md). The
load-bearing ones are [`M14`](docs/milestones/M14-RESULTS.md) — the drift floor closed and the
evidence flip confirmed — [`M15`](docs/milestones/M15-RESULTS.md), η Tel B's circular-orbit
RV sensitivity, and
[`M34`](docs/milestones/M34-RESULTS.md), which asks whether the detection is an artefact of
tuning the extraction on the published answer, [`M36`](docs/milestones/M36-RESULTS.md), whose
attempted injection-selected experiment was paper-derived and did not execute its
pre-registration faithfully, and [`M37`](docs/milestones/M37-RESULTS.md), which freezes the
screened/all-18 permutation re-audit.

## Where things are

```
docs/            the working record -- start at docs/README.md
  milestones/    one document per milestone, each owning a conclusion
  audits/        every citation, and every borrowed number, checked against its source
  paper/         manuscripts: .md / .template.html are source, .html are build products
src/exosat_rv/   the package -- archive readers, order maps, feasibility model, orbit fits
scripts/         drivers -- cr2res/ reduces raw frames, injection/ is the harness + period search
tests/           offline suite (plus live-network tests); exercised in CI on Python 3.11/3.12
data/            published reference tables, exported figures, per-milestone JSON
papers/          the literature this project cites (text committed, PDFs not redistributable)
```

## The verdict

**The screened archival series recovers the primary signal from raw data; the second
satellite does not survive this project's model comparisons on the paper's own table.**
Both statements carry the qualifications below.

**Recovered, with a load-bearing screen.** A separately implemented re-reduction (cr2res
from raw frames, viper forward modeling, the paper's eleven-order set and extraction choices
calibrated against its published series) reaches **70–90 m/s rms against the published
per-epoch RVs** — down from ~1850 m/s at M6 — and a **target- and paper-aware downstream
period search re-detects the ~171-day signal at rank 1 with a BERV nuisance covariate in the
model** (ΔBIC +26 to +28), on two reduction routes. The fits do not ingest the published RV
values, but the driver constructs a paper-matched subset and reports a hard-coded 171.45-day
window. The result holds for the 17 nights retained
by the internal across-order-spread screen; with all 18 nights the search degrades to noise,
so the exclusion is part of the result. Fitted amplitude
is estimator-dependent and high: K = 426–472 m/s by direct fit against the published 306,
or slopes 1.19–1.34 in regression. Every adopted pipeline change passed
fitter-stage injection-recovery gating; because those injections shift an already-built
template, they do not test absorption during template construction. The decisive levers were
a second template iteration, oversampling, and per-nodding-frame extraction (M14, M28 §6.2).

**Not reproduced under the tested models.** Nested sampling (dynesty) on the paper's *own
published RV table* gives a negative mean ΔlogZ(two satellites − one satellite) in all ten
tested model/prior/live-point configurations. Across 82 paired comparisons, 81 are negative;
the one exception is +0.90, against the paper's claimed **+2.62**. This establishes
non-reproduction under this project's stated likelihoods and priors, not a direct test of the
authors' different sampler or incompletely published prior configuration (M28 §7).

**Caveats, stated plainly.** The recovered amplitude runs 19–34% high by regression slope and
39–54% high by direct fit, while the published RVs correlate with BERV at r = −0.71, so the screened, paper-calibrated recovery is
confound- and selection-limited at current
sampling; the epochs that decide it are embargoed until Dec 2026 – May 2027
(the calendar is in [`docs/target-queue.md`](docs/target-queue.md)).

The fitter-stage validation is only trustworthy because of the **positive control** discipline from
M3 onward (GJ 229 B, a known 12.1-day binary — Δχ² = 63.8) and injection gates on every
change: three separate "improvements" that deleted signal were caught and rejected by
exactly that machinery (M9, M11, M23).

## After the core reanalysis: the survey (M15–M26) and what it found

The recipe was then pointed at **every archival CRIRES+ companion-spectroscopy
campaign** a coordinate-based census could find (names lie; a 50,000-frame sky-clustered
sweep does not). The M23 roster counts were later revised by the HiRISE mode audit and the
spatial-resolution audit; use the living ledger in `docs/target-queue.md`, not the historical
count, for current per-target verdicts. Highlights:

- **eta Tel B** — no detection, with **grid-pointwise circular-orbit 90%-completeness limits
  of m sin i ≈ 0.51–1.27 M_Jup across P = 20–300 d**, consistent across two reduction routes.
  The 99–101% injection result validates transmission through the fitter after the template
  has been built; possible self-template absorption is not tested on this target (M15, M28).
- **The K-band tier** — the β Pic b slit extraction reaches 162 m/s within-night fit scatter,
  but the spatial-profile audit shows that the planet and host are unresolved and the
  extracted spectrum is host-dominated; it is **not a β Pic b RV measurement**. AB Pic b
  remains resolved, while CT Cha B has a 3.3σ variability candidate undecidable at n = 3
  (M17, M23, M29).
- **The measured feasibility gate is spatial resolution** — define
  **R = separation / delivered PSF FWHM** from the slit profile. The audited reductions are
  host-dominated below R ≈ 1 and spatially eligible above it. This does not establish a
  universal contrast threshold for resolved pairs: the proposed S = contrast/θ² ordering is
  exploratory and method-dependent, and the transition remains unmeasured here. For unresolved
  pairs, fibre starlight suppression or interferometry is required (M29 §§3–9; M33).
- **YSES 1 b** — 34 m/s night-to-night, the best per-epoch quality of the whole campaign
  (~20–30 M⊕ satellite reach if its blocked 2022 pair is recovered) (M25–M26).
- **The machinery catches fakes** — PDS 70's nine-night template upgrade *looked* quieter
  and failed its injection gate at −62% recovery; rejected, and the validated six-night
  state restored bit-for-bit (M23).

**M27, open:** a header audit revealed that every dataset this project had classed as
"staring mode" is actually **HiRISE** — fiber-fed SPHERE→CRIRES+ starlight-suppressed
observations — which retracted three staring-tier verdicts (our slit-recipe reductions,
not the sky) and revealed **six public suppressed nights of beta Pic b** awaiting a
fiber-appropriate reduction. The correction log lives at the top of
[`docs/target-queue.md`](docs/target-queue.md).

A Hoy-style manuscript draft (CD-35 + eta Tel, figure-for-figure against the paper) is
generated in [`docs/paper/`](docs/paper/) — built from `draft.template.html`, never
hand-edited.

⚠️ **M1 retracted two claims M0 published.** M0 asserted that a value in the paper
(a "Hill radius" of 1.07 au) was impossible; it is a Domingos+2006 *stability limit*, the
companion's orbit is highly eccentric (e > 0.9, a ~ 222 au, not a circular 62.6 au), and
recomputed properly the paper's value is **correct**. M0 also misreported what the paper's
Δlog Z = 2.6 compares. Both retractions, with working, are in
[`M1-RESULTS.md`](docs/milestones/M1-RESULTS.md) §1 and indexed in [`HANDOFF.md`](docs/HANDOFF.md) §1.

---

> **The sections below are the M0–M11 record, kept as written.** Several of their verdicts
> were later superseded — most importantly, "the measurements do not reproduce" (M6's
> ~1850 m/s floor, M9/M11's 776 m/s) was closed by M13–M14, and M10's astrometric route
> was shelved once the RV route worked. They stay because the dead ends are the method:
> each one was closed by a control or an injection gate, and
> [`LESSONS.md`](docs/LESSONS.md) §7 maps every conclusion to the milestone that owns it.

## M0 in one table

CRIRES+ H-band nights on CD-35 2722 B, measured 2026-08-09 (`exosat-rv inventory`):

| Class | Nights |
|---|---:|
| **Usable now** — public *and* pipeline-reduced | **17** |
| **Reduction gap** — public raw, needs esorex | **3** |
| Embargoed until Dec 2026 – May 2027 | 8 |

**17 + 3 = 20, and the preprint claims exactly 20 usable epochs.** The paper's dataset is
the set of public H-band nights, with nothing held back — asserted as a live test so it
fails loudly when the embargo lifts. Usable baseline 2023-10-13 to 2025-01-21.

M1 then read the actual PDF (`pypdf`, 27 pages — no poppler or WSL needed) and sourced every
config value. The unverified `[SUMM]` tier is **eliminated**; two further values it held were
wrong (primary mass 0.4 not 0.5 M☉; mean RV error 31.44 not 30 m/s). The lesson M0 drew —
tag unverified values — was too weak: **an unverified value must not be an input to any
conclusion, not merely absent from tests.**

## Why this is reproducible at all

Two archive facts decide the whole project, both measured in M0 rather than assumed:

- The preprint's dataset — 20 H-band epochs, Oct 2023 to Jan 2025 — **has left its
  proprietary period.** The Dec-2025-onward frames that changed the accepted Nature
  numbers have not, and lift between Dec 2026 and May 2027.
- ESO publishes **pipeline-reduced 1-D spectra** (`calib_level=2`) for 17 of those nights,
  and M1 confirmed they are **per-order extractions with native wavelength solutions**:
  7 echelle orders x 3 detectors x 2048 native pixels, labelled by `ORDER`/`DETEC`/`XPOS`.
  That is exactly what a forward-modelling RV code consumes, so the raw-to-1D reduction —
  the expensive part — does not have to be redone. **The project's last kill-risk is
  retired.** Working from the combined product costs ~10% precision (34.49 vs 31.44 m/s),
  which is understood in advance rather than discovered in M3.

## What this reanalysis does and does not mean

This is not a rerun of the authors' pipeline on the authors' products. The inference stage
uses a *different* Keplerian fitter, which supplies a method-diverse cross-check but not
independent evidence because the extraction was calibrated against the published series.
Within the paper-calibrated, screened analysis, the sharpest remaining inference
question is the **period of the second signal**. The paper is explicit that 14, 70, 88 and 115 days
are aliases of one another, produced by two observing seasons almost exactly a year apart,
and that its favoured 88-day model beats the 115-day one by only Δlog Z = 2.6. That is a
*sampling* problem, and a reanalysis can attack it without new telescope time — via the
spectral window function and injection-recovery across the alias family.

(The obvious alternative — that the second signal is a harmonic of an eccentric 169-day
orbit — is one the paper already fits and rejects at Δlog Z = 6.9. M4 was re-scoped once
M1 read the source.)

## What else came out

**M4 — the second signal's period.** All four candidates (14, 70, 88, 115 d) lie on a
one-year alias comb built from the *primary* 169.45 d signal. Injection-recovery on the real
cadence shows a true 115-day signal is recovered as ~87 d **92%** of the time, so peak
position cannot discriminate. But a 115-day signal clears the 1% FAP only **6%** of the time
against **74%** for 87.46 d — so the *significance* of the observed peak does favour the
paper's choice, by an argument stronger than the Δlog Z = 2.6 it quotes.

**M1 — two of M0's published claims were wrong**, found by reading the actual PDF. M0 had
"disproved" a value in the paper that turned out to be correct. Both retractions are indexed
in [`HANDOFF.md`](docs/HANDOFF.md) §1.

**M2 — a converter that unlocks the archive.** ESO's products can drive `viper` after a
verified-lossless reshape into cr2res layout, plus four undocumented configuration facts
(K-band FTS default, Ångström-vs-nm templates, gnuplot at import, `termios`).

## The analogue targets (M5)

Searched **archive-first** — a catalogue-first list cannot contain CD-35 2722 B, since the
NASA Exoplanet Archive caps at 30 M_Jup. Rediscovering CD-35 2722 B is the control, and it
passes. Frame counts mislead badly (beta Pic b's 753 frames are 6 nights); what matters is
nights spread over time:

| Target | Usable H nights | Baseline | Why it matters |
|---|---:|---|---|
| **eta Tel B** | 16 | 800 d | Best analogue — more baseline than CD-35 2722 B's own campaign, and a wider 4.2″ separation |
| **GJ 229 B** | 11 | 361 d | 5.8 pc, and a **known binary brown dwarf** — a positive control where a signal is *expected* |

M5 also found that this is **not white space**: programme 110.23RW is a pilot survey by the
same group across AB Pic B, beta Pic B and CD-35 2722 B, and every later programme targets
CD-35 2722 B alone.

## Generalising the method (M7–M8)

The obvious next question — *where else does this work?* — turned out to have a published
answer the project had never read. Hoy et al. cite
[Lazzoni et al. 2022](https://arxiv.org/abs/2207.07569), by four of their own co-authors,
which simulates satellite populations around 38 imaged companions and computes RV detection
probabilities for each. The method itself was proposed by
[Vanderburg, Rappaport & Mayo 2018](https://arxiv.org/abs/1805.01903), and **three published
nulls preceded this detection**, not the one SPEC named (under the wrong author). There is
now a `papers/` archive and [`scripts/fetch_paper.py`](scripts/fetch_paper.py) to extend it.

**[`M7`](docs/milestones/M7-RESULTS.md) — the feasibility framework.** Four conditions, not two: wobble,
flux, dynamical allowance, and *survival*. Two results worth stating:

- **eta Tel B is the best analogue on two independent criteria.** M5 ranked it #1 on archive
  holdings alone; Lazzoni et al. rank it **4th of 38** on physics alone. Neither ranking
  shares an assumption with the other.
- **No imaged companion reaches planet-like (Galilean/Titan-class) satellites.** This method
  finds binary-like satellites or nothing — matching Lazzoni et al.'s central conclusion
  from a threshold recalibrated on the *achieved* 31.44 m/s rather than their forecast, which
  the real instrument beat by 1.6x.

**[`M8`](docs/milestones/M8-RESULTS.md) — young close-in giants.** Pushing the M_host^(-2/3) scaling to
hot Jupiters: an Earth-mass moon there gives K ~ 71 m/s, and a 10 M_Earth one ~708 m/s,
*larger* than the 246 m/s actually detected. The signal is easy; survival is the problem.

An old hot Jupiter is tidally locked to its star, which puts its corotation radius outside
the Hill-stability limit — so **every dynamically stable satellite is inside corotation and
spirals in**. A *young* planet has not been despun and the window is open. The catch is that
hot Jupiters cannot be spatially resolved, so the slit trick is replaced by cross-correlation
spectroscopy, which needs the planet's velocity to sweep >= 30 km/s in a night. Survival wants
a wide orbit; cross-correlation wants a narrow one, and the trade is
**tau_spin-down ~ M_star t^3 / dv^3** — a factor 2 in observability costs 8 in survival time.

**3 known planets clear both cuts at the pessimistic tidal Q, 8 at the optimistic one**
(`exosat-rv closein`). And planet mass is the cheapest lever: the planetary range runs to
13 M_Jup, spin-down goes as M_p while the satellite geometry is self-similar, so **from
~5 M_Jup upward the observability bar clears unaided.** No such planet is currently known
young *and* close enough — CoRoT-20 b (4.3 M_Jup, 0.090 au) misses by 1.25x — which makes
that a gap in the catalogue rather than in the physics.

The prize is not the moon. Massive satellites do not survive high-eccentricity migration
([Trani et al. 2020](https://arxiv.org/abs/2008.13778)) and preferentially do survive
disc migration, so **a limit at 10–30 M_Earth around a young hot Jupiter discriminates
between hot-Jupiter migration channels** — and RV is most sensitive to exactly the massive
satellites the theory says are the survivors.

## The control earned its keep (M9)

M9 tested whether per-order screening could close the extraction gap. It cannot — **6%**,
against the factor of 25 needed — and the individual nodding frames the plan had ranked first
turn out to be a **10%** lever, quantified in the paper's own Fig. 4. Both cheap levers are
now measured rather than assumed, and the conclusion is that the shortfall is **entirely
per-order**: median per-order rms is 2133 m/s over 10 orders, the √10 floor is 674, and viper
delivers 823. The combination stage was never the problem.

The more useful result is a near miss. **Weighting orders by their measured scatter gives the
best number the project has produced on CD-35 2722 B — 514 m/s, a 1.6× gain — and destroys
the GJ 229 B control**, dropping Δχ² from 63.8 to 5.8 and the recovered amplitude from 6165
to 1825 m/s on a binary nobody disputes. For a target with a real signal, an order's scatter
*is* the signal, so inverse-scatter weighting deletes exactly what it should keep. On a target
with no detection that is invisible.

HANDOFF has said since M3 that no result from this pipeline may be reported without re-running
the control. **M9 is the first time that rule actually caught something**, and without it the
screen would have been adopted and every later null made deeper and more wrong.

## The template, rebuilt the published way (M11)

M9 named the template as the leading suspect, so M11 ran it: viper under WSL, the recipe from
Köhler et al. 2025 §2.2 that Hoy et al. defer to, two template iterations, telluric-derived
wavelength solution. **CD-35 2722 B improved, 776 → 620 m/s. The control collapsed.**

| Template | Control Δχ² | Recovered K | vs. correct |
|---|---:|---:|---:|
| 0 iterations (baseline) | 76.5 | 5948 m/s | 100% |
| 1 iteration | 23.7 | 2452 m/s | **41%** |
| 2 iterations (the published recipe) | 21.1 | 2360 m/s | **40%** |

**Self-templating absorbs the signal.** The template is co-added from the target's own spectra
aligned by RVs measured against a template that already contains the signal, so the residual
is baked in and later velocities are partly the star measured against itself. The damage
arrives with the *first* iteration and does not recover. Köhler et al. flag the hazard for
targets with real Doppler shifts; their prescribed workaround is what viper implements, and
at our precision it was not enough.

CD-35 2722 B "improved" because that is what suppression looks like on a target with no
detected signal. **Three changes in a row have now improved the science target and been
rejected by the control** — M9's empirical weighting, M9's telluric screen, and this. On a
non-detection, anything that removes signal looks like success.

**Net movement toward the target precision: none.** Still 776 m/s against 31.44 needed. What it did
buy is elimination: the template, order screening and the nodding frames are all now measured
rather than assumed, and the leading suspect is what remains — the ADP→cr2res conversion,
verified *lossless* but never verified to put segments in the right order/detector slots.

## A second route, with better data (M10)

M9 closed the cheap options on the RV extraction gap, so M10 asked whether the project's
actual goal — bounding a *new* exosatellite — has another path. It does, and its public
dataset is better:

| Dataset | Nights | Baseline |
|---|---:|---:|
| CD-35 2722 B — the published RV detection | 18 | 466 d |
| eta Tel B — M5's best RV analogue | 16 | 800 d |
| **beta Pic b — VLTI/GRAVITY astrometry** | **28** | **2987 d** |

Astrometry also **outranks RV in Lazzoni et al.'s own table** (P = 0.999 vs 0.996) and reaches
*below* RV's ~0.4 M_Jup floor. And **HD 206893 B, where Kral et al. 2026 report a tentative
astrometric exomoon candidate, has 22 public reduced nights** — their result is reanalysable.

**beta Pic b was the historical crossover target in M10**: #2 in M7's forecast RV ranking
and one of the strongest public GRAVITY datasets considered there, offering a route to compare
RV and astrometric limits. The present-day qualification is decisive: this repository's slit
series is host-dominated, its public HiRISE nights require a fibre-appropriate reduction, and
Kenworthy et al. (2026) have since published dedicated β Pic b RV limits. The same target can
be unusable for one implementation and strong for another.

⚠️ **A kill-check is open.** This is the M0-equivalent, not the M1-equivalent: the data is
public and reduced, but whether those visibility products carry the dual-field differential
phase astrometry needs is unverified. M1's precedent applies — the first automated verdict on
ESO's CRIRES+ products was wrong. See [`M10-RESULTS.md`](docs/milestones/M10-RESULTS.md) §5.

## Continuing this work

Reading order: [`LESSONS.md`](docs/LESSONS.md) (every trap this project paid for, so you don't
pay twice) → [`HANDOFF.md`](docs/HANDOFF.md) (state and next actions) →
[`docs/target-queue.md`](docs/target-queue.md) (the per-system roster, embargo calendar,
and the M27/HiRISE front) → the latest `M*-RESULTS.md`.

To rebuild the RV extraction from scratch, [`docs/viper-runbook.md`](docs/viper-runbook.md)
has the full sequence: WSL setup, the two gnuplot patches, the ADP→cr2res conversion, the
Ångström-vs-nm template trap, the mandatory `-fts` H-band flag, and the positive control that
must pass before any null from the pipeline means anything. The M12+ machinery (reduction
cascade, injection harness, census, per-target runners) lives in
[`scripts/`](scripts/) — the CLI below covers the M0–M10 layer.

## Quickstart

Use a source checkout or unpacked source release for the research tables and milestone
scripts. On Linux/WSL (Python 3.11 or newer):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
exosat-rv --help
python scripts/m37_package_evidence.py --verify
python scripts/m37_render_results.py --check
python -m pytest -m "not network"
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead. Historical raw
reduction scripts require the separately installed WSL/cr2res/VIPER environment described
above. Figure and nested-sampling scripts additionally use `python -m pip install -e
".[science]"`.

The wheel contains the Python package, not the research data, scripts, or external spectral
products. An editable source install uses the checkout's `data/`; a wheel install defaults
to `data/` under the caller's working directory. Set `EXOSAT_DATA_DIR` **before starting the
CLI** to select another directory (for example, the unpacked source release's `data/`). That
directory holds both the CLI's inputs and its generated reports; it is not a read-only
resource path. Commands requiring tables or prior extraction outputs need those files to be
present. The library's array-based calculations and `--help` do not require the data bundle.

The following are research commands, not an installation test. Archive commands use the
network, and several commands create reports or download products:

```bash
exosat-rv inventory          # M0: what is public, reduced, and usable right now
exosat-rv probe              # M1: open a reduced product, check viper can use it
exosat-rv targets            # M5: analogue target list, archive-first
exosat-rv alias              # M4: is the second period set by the data or the sampling?
exosat-rv orbits             # M6: rerun the model comparison from the published RVs
exosat-rv survey             # M7: which imaged companions can the method work on?
exosat-rv closein            # M8: can it reach satellites of young close-in giants?
exosat-rv orders             # M9: per-order screening, and the ceiling on what it buys
exosat-rv gravity            # M10: public VLTI/GRAVITY data on the astrometric shortlist
```

## Honest scope

This project does not claim a discovery and will not submit one. Its output is a qualified
reanalysis verdict, a harmonic test, and — for the analogue survey — most likely
**upper limits** rather than detections. Upper limits are the expected result and are
reported as the result.
