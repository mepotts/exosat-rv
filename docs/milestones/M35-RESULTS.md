# M35 — The two pre-submission cross-checks: no photometric period, and clean astrometry

> **Superseded analysis (M37, 2026-08-31):** the photometric null survives a corrected
> camera- and night-aware reanalysis, but the exposure-level permutation and sparse phase
> experiment below overstated sensitivity. The authoritative artifact is
> `data/m35-photometry-v2.json`. Gaia RUWE and the absence of an NSS solution provide
> catalogue context; they do not prove that the host has no astrometric perturbation.

`NEXT-DIRECTIONS.md` ranks **B1** and **B2** first, ahead of any new science, because they
belong in Paper I before it goes out and a referee will ask for both. Neither needs new
observations and neither needs an account. Both are done here.

**Result in one line.** The host of CD-35 2722 B shows *no* photometric periodicity at the
satellite's period down to **5 mmag**, on a search that demonstrably recovers the star's
own known rotation; and Gaia DR3 fits CD-35 2722 with an ordinary single-star astrometric
solution (**RUWE 1.023**, no non-single-star solution). Both cut the same way: the signal is
not the star.

---

## 1. B1 — Is the 171.454 d period visible in the host's photometry?

**Why it matters.** The RV period is measured on the *companion*, but the host sits 2.8"
away and this project has already measured slit contamination from it (M28). A rotating
spotted star imprints its rotation period on any contaminated spectrum, so a host that
varies at ~171 d would give the satellite an activity explanation and put the central
claim in trouble. A host that does not is an independent systematics defence.

**Data.** ASAS-SN, which covers this declination, needs no account, and carries
1609/2439 d of coverage — the g era alone is 14 cycles of the period under test. The V and g eras
are analysed **separately**: ASAS-SN changed filter in 2018 and the zero-point step between
eras is exactly the kind of thing that manufactures power at long periods.

Three ASAS-SN ids fall in the cone. Two (`609885843909`, `661427779128`) sit ~1" from the target and are the
same star catalogued twice; the third (`575526675969`) is a different star 40" away and is carried
as a contrast.

| series | n | baseline | grid cap | best period | perm *p* | power at 171.454 d | perm *p* there | injection limit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `575526675969/V` | 608 | 1609 d | 805 d | 4.024 d | 0.424 | 0.0003 | **0.920** | 50 mmag |
| `575526675969/g` | 1704 | 2439 d | 1219 d | 29.528 d | 0.000 | 0.0009 | **0.542** | 30 mmag |
| `609885843909/V` | 647 | 1609 d | 805 d | 2.378 d | 0.000 | 0.0014 | **0.554** | 5 mmag |
| `609885843909/g` | 1526 | 2439 d | 1219 d | 1219.273 d | 0.000 | 0.0007 | **0.400** | 5 mmag |
| `661427779128/V` | 647 | 1609 d | 805 d | 2.379 d | 0.000 | 0.0017 | **0.494** | 7 mmag |
| `661427779128/g` | 1526 | 2439 d | 1219 d | 1219.273 d | 0.000 | 0.0008 | **0.350** | 5 mmag |

**No detection, in either filter era, on either id.** Lomb-Scargle power at 171.454 d is
0.0007–0.0017, and against a 500-draw permutation null — the same argument `m28_nullcal.py`
makes for the RV search, that an analytic false-alarm probability charges for parameters
rather than for searching — that sits at ***p* = 0.35–0.55**. It is indistinguishable from
noise.

### 1.1 The null has demonstrated sensitivity, which is what A1 lacked

A null with no amplitude attached says nothing, and this project already has one milestone
(`NEXT-DIRECTIONS.md` A1) that failed exactly there: its control could only resolve a known
signal at 1.4σ, so every null it produced was a power failure rather than a result. Two
things stop that happening here.

**Injection recovery.** A sinusoid at 171.454 d, at random phase, injected into the real time
sampling and recovered against the 99th percentile of the permutation null in ≥90%% of
draws: the limit is **5 mmag** on the target ids and 30–50 mmag on the fainter 40"-away
star. So modulation above 5 mmag at that period would have been seen.

**A real signal, recovered.** AAVSO VSX carries this star as **ASAS J060919-3549.5**, type
**TTS/ROT**, period **1.717 d**, amplitude 0.057 mag. The V-era search returns a best period
of **2.379 d at permutation *p* = 0.000** — which is that rotation seen through the daily
sampling: |1 − f_rot| = 0.41759 c/d against the measured 0.42043 c/d, a mismatch of
0.0028 c/d, where every other low-order alias misses by more than 1 c/d. The search finds
the variability the star is *known* to have, and does not find any at 171.454 d.

The rotation period and the RV period are not related: f_rot/f_RV = 99.9, and 171.454 d is
not a yearly alias either (1/171.454 = 0.005832 c/d against 2/365.25 = 0.005476).

### 1.2 One methodological correction, made mid-run

The first pass searched to 2000 d regardless of baseline and returned "best" periods of
1250–1580 d against baselines of 1609 and 2439 d. That is the defect this project's own
methods note documents in §5.3 — an unbounded grid on a 41 d series once manufactured a
ΔBIC = +9.3 entry at ~171 d — wearing a different hat. The grid is now capped at half the
baseline, guaranteeing two full cycles, and the first-pass long-period numbers are not used.
**The 171.454 d result is unchanged by this**: it is far inside both grids, and its power and
permutation *p* moved in only the last decimal.

Honest residual: the g-era "best" peak now sits **exactly at the grid cap** (1219 d), which
is a low-frequency systematic pressed against the boundary rather than a period. It is
reported rather than removed, and nothing here rests on it.

---

## 2. B2 — What Gaia says about the hosts

Gaia DR3 publishes three handles on an unseen companion perturbing a host: RUWE, the
astrometric excess noise `epsi` and its significance `sepsi`, plus `NSS`, a flag for whether
the source appears in the non-single-star tables at all. All 31 roster positions carrying
coordinates were queried in **one batched cone query** (356 Gaia rows).

**CD-35 2722 — the system the paper is about:**

| field | value |
|---|---|
| Gaia DR3 source_id | 2885863400349980288 |
| separation from the query position | 4.22 arcsec |
| G | 10.217176 |
| parallax (mas) | 44.7203 |
| RUWE | 1.023 |
| astrometric excess noise (mas) | 0.099 |
| its significance | 13.962406 |
| non-single-star solution | 0 — none |

The parallax agrees with the value `config.py` already carries from SIMBAD, which is how the
match is confirmed rather than assumed. **RUWE 1.023** means the single-star astrometric model
fits; the conventionally quoted threshold for suspicion is 1.4. The excess noise is
0.099 mas — formally significant at 14.0, as it is for most bright stars, but 99 μas is not
an astrometric perturbation of interest here.

**η Tel**, the system carrying the project's own published limit, is likewise clean:
RUWE 1.013, excess noise 0.608 mas, NSS 0.

**Across the whole roster: not one target has a Gaia non-single-star solution** (`NSS = 0`
everywhere). 3 of 31 positions returned no Gaia source carrying a parallax at all (`[EM98] DG Tau B cRN`, `SCR J0103-5515C`, `EPS-IND-B`).

### 2.1 The high-RUWE entries are a brightness artefact, not companions

5 positions exceed RUWE 1.4:

| host | G | RUWE | excess noise (mas) |
|---|---:|---:|---:|
| * bet Pic b | 3.82 | 3.072 | 1.386 |
| * b Cen | 3.99 | 2.600 | 1.609 |
| 2MASS J18362308-2356359 | 18.23 | 2.123 | 1.849 |
| * b Cap | 4.27 | 2.027 | 0.836 |
| DENIS J183610.1-234844 | 17.89 | 1.635 | 1.302 |

The largest values sit on the brightest stars, where Gaia's astrometric solution is known to
degrade, and none of them carries an NSS solution. **These are not read as detections of
unseen companions**, and no claim in this project depends on them. Anyone wanting to use
this table for a companion argument needs the bright-star RUWE literature first; it is not
cited here because no citation for it was verified while writing this.

---

## 3. What this establishes, and what it does not

**Establishes.** The satellite period is absent from the host's photometry at a level
(5 mmag) far below the star's own rotational amplitude (57 mmag), on a search proven to
recover that rotation. The host is not astrometrically perturbed in Gaia. Two independent
activity/companion explanations for the RV signal are therefore constrained, and neither
required new observations.

**Does not establish.** Photometric quiet at a period does not prove a spectroscopic signal
at that period is not stellar — a spot configuration can move a line centroid with little
broadband flux change, and the contamination path runs through the *companion's* slit rather
than the host's integrated light. This is a constraint on the most obvious activity
explanation, not a proof of the satellite. It is also a statement about the **host**; the
companion itself is far too faint for any of these surveys.

**Reproduce it:**

```bash
cd "$(wslpath -a .)"
~/viperenv/bin/python scripts/m35_asassn_photometry.py   # --refetch to re-pull ASAS-SN
~/viperenv/bin/python scripts/m35_gaia_astrometry.py
```

Outputs: `data/m35-photometry.json`, `data/m35-gaia.json`, and the cached light curve
`data/m35-asassn-cd35.csv` so the period search reruns without touching the network.

`skypatrol` (the ASAS-SN client) is the one new dependency, and it is needed only for
`--refetch`; the cached curve is committed.
