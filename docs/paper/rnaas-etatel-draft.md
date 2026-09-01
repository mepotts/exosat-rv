# DRAFT — Research Note of the AAS, for Matthew's decision. NOT SUBMITTED.

> **Status: audit-corrected but not submission-ready; not submitted.** Submission is outward-facing and irreversible, this
> project's own rules (`LESSONS.md` §6) gate it to Matthew, and the agent that prepared this
> holds no journal credentials. Nothing here has been sent anywhere.
>
> Every number below is printed by [`scripts/m32_etatel_numbers.py`](../../scripts/m32_etatel_numbers.py)
> from `data/m15-limit.json` — none is hand-transcribed, because the repo's own audit found
> 34 conflicting values that entered exactly that way. Re-run it before submitting and diff.
>
> **Blockers are listed at the bottom.** Read those first.

---

**Title:** Radial-Velocity Limits on Satellites of the Brown Dwarf Companion η Telescopii B

**Authors:** Matthew Potts (affiliation TBD; ORCID TBD)

---

## Abstract

*(Required by RNAAS since May 2020.)*

We present radial-velocity constraints on η Telescopii B, an M7–M8 brown dwarf
companion at 4.2″ from the A0V star η Tel, derived entirely from public CRIRES+ archival
data: 20 epochs in the H1567 setting spanning 18 nights and 815 days, reduced by two
extraction routes that agree at 127–130 m s⁻¹ per-epoch scatter. No periodic signal is
detected. Injection after template construction returns 99–101 ± 1% of the injected
amplitude through the RV fitter, and a detection criterion whose pointwise false-alarm
probability is measured at ≤ 0.85% by permutation yields circular-orbit, grid-pointwise
90%-completeness limits of m sin i ≈ 0.51–1.27 M_Jup for satellites with
P = 20–300 d. Because η Tel B's own orbit is near edge-on (i ≈ 79–82°), these are true-mass
limits to within 2% for any satellite orbiting near the companion's orbital plane. The
constrained periods correspond to 0.05–0.31 au, a region inaccessible to the high-contrast
imaging surveys that constrain satellites only beyond ~1–5 au.

---

## Body

η Telescopii B is an M7–M8 brown dwarf companion at 4.199 ± 0.015″ projected separation
(Chai et al. 2024) from the A0V star η Tel, a member of the β Pictoris moving group. It is
well studied photometrically, spectroscopically and astrometrically — a 25-year astrometric
baseline and, recently, an 11–21 μm JWST/MIRI spectrum — but to our knowledge **no
radial-velocity measurement of it has been published**. We report one, derived entirely
from public archival data. The system inverts the usual arrangement: HARPS velocities exist for
the *primary* but are unusable, scattering at 12.8 km s⁻¹ because η Tel A is a young, rapidly
rotating A0V star, and the most recent orbital analysis omits them for that reason (Chai et al.
2024). The faint companion, not the bright host, is the viable radial-velocity target here.

Radial-velocity monitoring of a directly imaged companion's own spectrum is an established
route to constraining massive satellites. Searches have been reported for the HR 8799 planets
(Vanderburg & Rodriguez 2021), HR 7672 B (Ruffio et al. 2023), GQ Lup B (Horstman et al. 2024)
and β Pictoris b (Kenworthy et al. 2026), all null, alongside astrometric limits from
interferometry (Macias et al. 2026; Kral et al. 2026). Against that run, Hoy et al. (2026)
reported a detection around CD-35 2722 B — which sharpens rather than settles how common
the configuration is, and makes each further constrained system worth having.

η Tel B supplies the clean same-setting archival control for CD-35 2722 B: it was observed in
the **identical H1567 setting** over a baseline long enough to constrain an orbit, allowing the
same H1567 nodding recipe to be applied. At ~47 M_Jup it also extends the sample into the
brown-dwarf host regime, with HR 7672 B.

**Data.** We use 20 public CRIRES+ H1567 epochs of η Tel B spanning 18 nights and 815 days
(ESO programmes 111.24M0, 113.268Y, 115.287U). We reduce them by two routes:
from the archive's reduced products, and from raw frames through the full `cr2res` cascade
with per-nodding extraction. Radial velocities come from `viper` (Köhler et al. 2025) in its
cell-free configuration, using telluric lines as the wavelength reference, over an
eleven-order set selected for telluric density. Both routes give **127–130 m s⁻¹** per-epoch
scatter, on an object of K_s = 11.6 ± 0.1 (Neuhäuser et al. 2011).

**The measurement is of the companion.** At 4.2″ against a delivered spatial PSF of 0.37″,
measured from the extraction's own slit function, the pair is separated by 11.3 resolution
elements. The check is not incidental: companions inside one resolution element yield a
spectrum that is the host's, while every downstream diagnostic — precision, order-to-order
dispersion, injection recovery — nonetheless improves. η Tel B is unambiguously resolved.

**Fitter-stage validation.** Because no published RV exists for this target, there is no
external velocity series to check. We inject a Keplerian by shifting the *already-built
template*, never the observation, and re-run the RV fit per
epoch. Recovery is **99–101% ± 1%** of the injected amplitude with 12–23 m s⁻¹ residual
scatter, and every individual order transmits at 95–108%; the per-nodding route separately
returns 100% ± 3%. An injected series assembled from those runs is recovered by the same
period search that returns the null, at rank 1 and the correct period. The fitter
detects what it is given after template construction. This does not test whether building a
self-template from data containing a real orbit would absorb part of that orbit; that failure
mode is externally bounded only for CD-35 2722 B, not for η Tel B.

**Result: no detection.** Across the 150–300 day window — where a CD-35 2722 B analogue would
lie — every ΔBIC is negative on both extraction routes. The strongest features are
short-period (5–12 d) and inconsistent between routes and between combination methods,
characteristic of sampling aliases rather than signal; Hoy et al. discard periods this short
on the same grounds. The null is not a sampling artefact: on this cadence only 11% of the
5–460 d period grid is degenerate with the barycentric velocity, and the 150–300 d decade is
completely clean.

**Sensitivity.** We add a circular-orbit signal to the real series; the original 12-phase
grid was rechecked over 36 phases, and we require ΔBIC ≥ 10 *and* rank 1 at the injected
period. That pointwise criterion's
false-alarm probability is ≤ 0.85% at every period tested — the rank-1 clause, not the ΔBIC
bar, carries the protection.

| Period (d) | K₉₀ (m s⁻¹) | m sin i limit (M_Jup) |
|---:|---:|---:|
| 20 | 300 | 0.51 |
| 60 | 250 | 0.61 |
| 120 | 250 | 0.77 |
| 200 | 300 | 1.11 |
| 300 | 300 | 1.27 |

*Grid-pointwise 90% detection completeness for circular orbits, conditional on the measured
fitter-stage transmission; companion mass 47 M_Jup (Lazzoni et al. 2020). K₉₀ is read off
the measured detection grid — the smallest injected amplitude reaching 90% — not interpolated
or fitted.*

**At the tested grid points, the circular-orbit 90%-completeness thresholds are sub-Jupiter
to Jupiter mass across most of the 20–300 day range.** We are not aware of previous radial-velocity measurements of this
companion, but claim no priority: the value of a limit does not depend on being first. They
sit comfortably alongside the published sample: Kenworthy et al. (2026) reach 1 M_Jup at
P = 200 d on β Pic b from a dedicated campaign at 160 m s⁻¹ mean precision, against
1.11 M_Jup at the same period here from archival data at 127–130 m s⁻¹.

These limits also probe a region no imaging survey reaches. For a 47 M_Jup host, P = 20–300 d
corresponds to **0.05–0.31 au**, whereas the dedicated SPHERE star-hopping survey of twelve
directly imaged companions constrains satellites only beyond ~1–5 au (Lazzoni et al. 2026).
The two techniques do not overlap, and the reason is generic: astrometric amplitude scales as
the satellite's semi-major axis while radial-velocity amplitude scales as a^(−1/2), so
imaging and astrometry own the wide orbits and RV owns the close ones (Macias et al. 2026).

The limits are on m sin i, but in this system that costs almost nothing. η Tel B's own orbit
about η Tel A is near edge-on — i = 79 (+5/−6)° (Chai et al. 2024, stable across five
alternative fit configurations) and 81.9° from a separate analysis (Nogueira et al. 2024). A satellite formed in a circum-companion disc would be expected to orbit near that
plane, and if it does, sin i ≈ 0.98 and **the tabulated limits are true-mass limits to within
2%**. This is an assumption, not a measurement, and a strongly misaligned satellite would
evade the constraint — but it is the same near-edge-on geometry that motivates β Pic b as an
RV target (Kenworthy et al. 2026), and the same coplanarity expectation under which the
CD-35 2722 B satellite is interpreted.

A twin of the CD-35 2722 B satellite (m sin i = 0.918 M_Jup) would produce K ≈ 540 m s⁻¹ at 20 d falling to
≈ 217 m s⁻¹ at 300 d. It is recovered in ~100% of the tested circular-orbit trials at short
periods but only 42–83% at 200–300 d. The short-period null is therefore supported by high
measured fitter-stage completeness, whereas the cadence has inadequate completeness near the
period of the reported example.

**Caveats.** The 90% contour is a detection-completeness statement at tested grid points,
not an unconditional confidence limit or a continuous exclusion curve, and it assumes
circular orbits. It is conditional on an injection test performed after the self-template
was built, so possible signal absorption during template construction is unmeasured on this
target. The mass of η Tel B is itself disputed, and m sin i scales as
M^(2/3): evolutionary-model fits give 47 (+5/−6) M_Jup (Lazzoni et al. 2020) while the
JWST/MIRI atmospheric fit gives 29 (+16/−13) M_Jup (Chai et al. 2024). The two dynamical
posteriors that sit between them, 42 ± 14 and 48 ± 15, both use priors traceable to the
former and are described by their own authors as prior-driven, so they are not independent
evidence. We adopt 47 M_Jup, the conservative choice — the atmospheric mass would deepen
every threshold in the table by 27%. The grid-pointwise thresholds remain sub-Jupiter to
Jupiter mass across the full range, so the disagreement changes the numbers but not that scale.

Eight archival epochs from 2009 on the original CRIRES, and embargoed 2025–26 K-band epochs,
remain unexploited and would extend the baseline substantially.

*Software:* `cr2res`, `viper` (Köhler et al. 2025), `astropy`, `numpy`, `scipy`. The
reduction and analysis code, injection harness, sensitivity grid, and compact exports are public at
[github.com/mepotts/exosat-rv](https://github.com/mepotts/exosat-rv).
The adopted η Tel RV, per-order/BERV, parameter and target tables, the VIPER configuration
and tracked source patch observed in the audited checkout, and a hash manifest are frozen in
`data/repro/`. That configuration records checkout state only; it does not prove which
configuration governed the historical extraction runs. Raw/reduced ESO spectra and fitted
templates remain external; the templates and FTS atlas are hash-bound in the manifest. The
bundle therefore supports downstream replay, not reconstruction from raw exposures through
template building.
This work is based on observations collected at the European Southern Observatory under
ESO programmes 111.24M0, 113.268Y and 115.287U.

---

## References

- Chai, Y. et al. 2024, *ApJ*, "A JWST MIRI MRS View of the η Tel Debris Disk and its Brown
  Dwarf Companion", arXiv:2408.11692
- Dorn, R. J. et al. 2023, *A&A*, **671**, A24 (CRIRES+)
- Horstman, K. et al. 2024, GQ Lup B RV exosatellite search
- Kenworthy, M. A. et al. 2026, *MNRAS*, "Upper limits on exosatellites around β Pictoris b",
  arXiv:2606.04685
- Kral, Q. et al. 2026, *A&A*, exomoon search around HD 206893 B with VLTI/GRAVITY
- Lazzoni, C., Zurlo, A., Desidera, S. et al. 2026, *A&A* (SaNDi-SHoP I), arXiv:2603.24796
- Macias, I., Jenkins, S. A. & Vanderburg, A. 2026, *AJ*, **171**, 197
- Hoy, K. et al. 2026, *Nature*, "Satellite Detected Around a Star's Substellar Companion",
  doi:10.1038/s41586-026-10751-w
- Köhler, J. et al. 2025, *A&A*, **698**, A44 (viper), doi:10.1051/0004-6361/202553919
- Lazzoni, C. et al. 2020, *A&A*, **641**, A131
- Neuhäuser, R., Ginski, C., Schmidt, T. O. B., & Mugrauer, M. 2011, *MNRAS*, **416**, 1430
- Nogueira, P. H., Lazzoni, C., Zurlo, A. et al. 2024, *A&A*, "Astrometric and photometric characterization of η Tel B combining two decades of observations", arXiv:2405.04723
- Ruffio, J.-B. et al. 2023, *AJ*, **165**, 113
- Vanderburg, A. & Rodriguez, J. E. 2021, *ApJ*, **922**, L2

*(Verification status per `../audits/REFERENCE-AUDIT.md`. Hoy, Köhler and Chai are checked against
full copies archived in `papers/`. Dorn is corroborated via Hoy et al.'s reference [11];
Neuhäuser against the MNRAS record. Lazzoni et al. 2020 is archived as
`papers/text/lazzoni2020_disks_satellites.txt`; its Table 2 gives the adopted
47 (+5/−6) M_Jup AMES-COND mass directly.)*

---

## BLOCKERS before this can be submitted

**Scientific and reproducibility blockers:**

1. `data/repro/` now freezes the adopted RV/per-order/BERV/parameter/configuration evidence
   and the relevant software identities. Verify this table from that bundle and decide how
   raw/reduced ESO spectra and fitted templates, currently external and hash-bound, will be
   made available or disclosed.
2. Retain the fitter-stage/template-construction and grid-pointwise-completeness qualifications
   above. A pre-template injection would strengthen the result but is not represented by the
   current 99–101% figure.

**Matthew's calls — nothing below can be resolved by an agent:**

3. **Do you want to publish this at all?** It is a null result with a limit, and it is small.
   It may be worth more as a section
   of the full method paper (`docs/paper/draft.template.html`) than as a standalone note.
   Publishing separately does not preclude the paper, but does mean self-citing.
4. **Author list, affiliation, ORCID.** RNAAS accepts independent affiliations.

**resolved in M32 — recorded here so the work is not repeated:**

5. ~~The 47 M_Jup mass is single-source and unarchived~~ — **run down.** The repo attributed
   it to "Lazzoni T1 → Langlois et al. 2021b"; Chai et al. 2024 attributes it instead to
   **Lazzoni et al. 2020, A&A 641, A131**, AMES-COND models, **47 (+5/−6) M_Jup**. Chai's own
   MIRI atmospheric fit gives **29 (+16/−13)**, and their orbital posterior 42 ± 14 is
   explicitly "largely prior-driven" and so not independent. The note now quotes the
   disagreement and its 27% effect rather than a bare number. The source was subsequently
   obtained directly; see item 8.
6. ~~K = 13.2 conflicts with SIMBAD H = 11.93~~ — **resolved against 13.2.** Neuhäuser et al.
   2011 measures J = 12.06 ± 0.19, H = 11.75 ± 0.10, **K_s = 11.6 ± 0.1**, L = 11.1 ± 0.2.
   SIMBAD's H agrees; Lazzoni's Kp = 13.2 is wrong by 1.6 mag. The note now quotes K_s = 11.6
   with its source, and the "beats the forecast" claim has been **deleted** — that forecast
   was computed from the wrong magnitude, and at the true brightness the achieved precision
   probably does not beat a corrected one. See M30 for the repo-wide consequences.
7. ~~Confirm no prior RV exists~~ — **as close to settled as it can get without ADS.** The
   decisive evidence is Chai et al. (2024), the dedicated η Tel B characterization paper: it
   performs a full orbital fit and states that the only RV data in the system is HARPS
   velocities of η Tel **A**, unusable at 12.8 km s⁻¹ rms, which it therefore omits. That is
   precisely the paper that would cite a companion RV if one existed. Lazzoni et al. (2020),
   SaNDi-SHoP (2026) and Kenworthy et al. (2026) likewise cite none.
8. ~~Obtain Lazzoni et al. 2020 directly~~ — **done.** Archived
   (`papers/text/lazzoni2020_disks_satellites.txt`); its Table 2 gives η Tel B **47 (+5/−6)
   M_Jup**, age 24 ± 5 Myr, sep 4.21″ first-hand.
9. ~~AAS fee/membership~~ — **not a gate.** RNAAS carries **no publication charge** and AAS
   membership is **not required** to submit. A free submission account is all that is needed.

**Still to do — all of it yours:**

10. **Register an ORCID** (orcid.org, free, ~2 min) and fix the affiliation line.
11. **Re-run `scripts/m32_etatel_numbers.py` against the existing evidence bundle and diff against the table above** — a 60-second
    check that the manuscript matches the data before it leaves the building.
12. **Only after the blockers are closed, decide whether to submit.** No submission has been
    made: outward-facing action is irreversible, gated to Matthew by `LESSONS.md` §6, and no
    agent in this repository holds or may use journal credentials.

**Word count:** body is ~1,000 words against RNAAS's 1,500 limit, with one table and no
figure — within limits, with room for a sensitivity-curve figure if preferred.
