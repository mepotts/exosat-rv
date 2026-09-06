# M38 control evidence follow-up — 2026-09-06

> **CANDIDATE RESEARCH ONLY. No control selected, no protocol frozen, no target run.**
>
> This follow-up used primary-source literature, public archive metadata, and public
> FITS-header text for candidate controls only. No spectral arrays, local/external target
> spectra, target templates, or target RV analysis were opened or executed. Header text is
> not a spectrum. The [existing dossier](M38-CONTROL-CANDIDATES.md) and
> [draft protocol](M38-PROTOCOL-DRAFT.md) remain controlling; this memo changes no gate.

## Outcome

There is a concrete route to improve the validation, but this search did **not** find a
ready-made single-star positive control with independently established night-level RV truth
and a verified H1567/0.2-arcsec nodding series. Absence from this bounded search is not proof
that none exists in the archive.

The most useful progress is:

- V340 Ara genuinely has H1567 nodding data, but also K2166 data in the same visits, all
  with the wider 0.4-arcsec slit in the inspected records. Its earlier tentative H-band
  lead is partly confirmed, not promoted to an admissible primary control.
- Independently characterized RV-standard M dwarfs provide a better null-truth starting
  point than declaring eta Tel B stable from this project's own non-detection. However,
  their published CRIRES+ validation is in K band; H1567 coverage is not established here.
- GJ 229 Ba/Bb has an author-deposited numerical RV/orbit resource, useful for a
  component-resolved stress test. It does not supply the truth amplitude of our
  single-template blended centroid.

## 1. V340 Ara: header-confirmed H setting, unresolved scientific transfer

An exact-name query to [ESO's raw-observation TAP service](https://archive.eso.org/tap_obs)
returned 28 OBJECT records on two UTC dates. The query was:

```sql
SELECT dp_id, date_obs, slit_path, filter_path, ins_mode, dp_tech,
       prog_id, release_date
FROM dbo.raw
WHERE instrument = 'CRIRES'
  AND date_obs >= '2021-06-01' AND date_obs < '2026-09-07'
  AND object = 'V V340 ARA' AND dp_type = 'OBJECT'
ORDER BY date_obs
```

The HTTP request used `REQUEST=doQuery`, `LANG=ADQL`, `FORMAT=json`, `MAXREC=10000` at
`https://archive.eso.org/tap_obs/sync`. It is a name-limited screen, not a coordinate-complete
census. The result has 16 records dated 2022-04-19 and 12 dated 2022-08-10, programmes
109.23G3.002 and 109.23G3.001 respectively. All returned records list `W_0.4`,
`Spectroscopy`, `SPECTRUM,NODDING,JITTER`, and **`filter_path=K,HK`**. Their listed release
dates are in 2023. These are metadata facts, not proof that every exposure is usable.

The public header-display service independently resolves why the filter column cannot be
used to discard this candidate:

| Header inspected | `ESO INS WLEN ID` | `ESO INS SLIT1 WID` |
|---|---|---|
| [CRIRE.2022-04-19T09:18:12.334](https://archive.eso.org/hdr?DpId=CRIRE.2022-04-19T09:18:12.334) | K2166 | 0.400 arcsec |
| [CRIRE.2022-04-19T09:31:47.556](https://archive.eso.org/hdr?DpId=CRIRE.2022-04-19T09:31:47.556) | H1567 | 0.400 arcsec |
| [CRIRE.2022-08-10T04:27:34.454](https://archive.eso.org/hdr?DpId=CRIRE.2022-08-10T04:27:34.454) | K2166 | 0.400 arcsec |
| [CRIRE.2022-08-10T04:38:26.419](https://archive.eso.org/hdr?DpId=CRIRE.2022-08-10T04:38:26.419) | H1567 | 0.400 arcsec |

All four inspected headers also identify conventional spectroscopy and nodding/jitter.
Only these four headers were checked: **do not assign settings to the other 24 exposures by
their position in the returned list.** The first K2166 header initially looked like evidence
against the historical H-band lead; checking the later sequence starts prevented that
over-correction. Both visits are mixed-setting.

Scientific interpretation remains the one in the existing dossier: a pulsating Cepheid's
optical RV curve is not an exact H-band rigid-shift truth. A wider slit also changes the
resolution and illumination problem. This is a possible supplemental test of gross signal
retention, not a substitute for the required same-configuration positive control. Before
using it, verify every selected header and calibration association, calculate predicted
changes at the actual epochs from an independent ephemeris with uncertainties, and justify
which direction/amplitude bounds survive wavelength-dependent line formation. Do not tune
those bounds using this pipeline's measured V340 Ara RVs.

## 2. Null controls: start from independent stability evidence, then verify H coverage

[Koehler et al. 2025, sections 4.2–4.4 and Table 1](https://arxiv.org/html/2505.08315v1)
selected GJ 447, GJ 588, GJ 229A, and GJ 784 using low scatter in the independent HARPS-RVBANK
data. This is relevant external stability evidence. Their demonstrated CRIRES+ results and
observing configuration are **K-band**, not an H1567 validation; section 6 explicitly leaves
other bands for investigation. A star can be a useful approximate null over a specified
amplitude range without being physically motionless. The truth statement must include known
signals, trends, activity, sampling, and uncertainty rather than simply say “RV standard.”

[ESO's CRIRES+ reduced-data release](https://doi.eso.org/10.18727/archive/96) includes
observatory RV, telluric, and flux standards as science-grade spectra. It is an evolving
data stream, not a fixed calibration corpus. Its advertised inclusion of standards makes
an archive cross-match worthwhile, but neither a standard label nor a reduced product
establishes independent astrophysical stability or same-setting suitability.

The small name-based screen in this pass does **not** close H1567 coverage. Two illustrative
header checks reinforce the need for exact settings:

- [HD 191849 / GJ 784, CRIRE.2021-10-08T23:20:56.429](https://archive.eso.org/hdr?DpId=CRIRE.2021-10-08T23:20:56.429)
  is J1232, with a 0.2-arcsec slit, despite the archive filter text beginning `HX1E-3`.
- [GJ 588, CRIRE.2025-05-04T06:36:13.497](https://archive.eso.org/hdr?DpId=CRIRE.2025-05-04T06:36:13.497)
  is K2192, with a 0.2-arcsec slit, despite filter text `HX5E-2,HK`.

The [VIPER author manual, section 6.1](https://mzechmeister.github.io/viper_RV_pipeline/doc/VIPER-pipeline-manual.pdf)
also explicitly labels its GJ 588 demonstration data K2192. These data can help verify
software behavior in their own band, but importing their demonstrated precision as H1567
performance would repeat the transfer error.

**Recommended next observational screen:** resolve aliases/proper motions for the independently
characterized standards, make a candidate-only coordinate query including calibration
observations, and inspect mode/setting/slit/cell/pointing headers before any reduction. Verify
which component was actually observed in a multiple system; an object name such as HD 42581
does not by itself distinguish GJ 229A from a companion-pointed exposure. The present
name-limited query cannot certify a missing H-band series. Independent stability at the
relevant epochs and operating RV scale must be reviewed even if such a series is found.

## 3. Positive control: component truth exists for GJ 229, not centroid truth

[Xuan et al. 2024](https://www.nature.com/articles/s41586-024-08064-x) establish the close
binary with both interferometry and spectroscopy. The authors' [Zenodo record](https://zenodo.org/records/13851639)
states that its Julia notebook contains the CRIRES+ RVs and its archive contains five epochs
of GRAVITY data. The record describes a 5.0 MB orbit-model archive; the notebook/archive was
not downloaded or executed in this pass. Thus there is a concrete route to obtain
author-provided control RVs, not merely a statement that published numbers exist.

**Inference:** the appropriate comparison is a two-component spectral model against the
component RVs (or a carefully defined relative-velocity observable), carrying their
uncertainties. The published binary orbit does not imply that a single-template fit to the
blended light should recover either component's semiamplitude. The expected blended response
depends on line shapes, wavelength-dependent flux ratio, separation, and estimator. Comparing
our centroid to a component curve would misdiagnose physical blending as extraction failure.

This makes GJ 229 valuable for revealing template absorption and component confusion, but
does not overturn the draft's rule against using it as the sole positive control. A
component-resolved extension is a distinct, reviewable measurement model, not a switch that
automatically validates the single-component science pipeline.

## Practical recommendation and remaining barrier

Prioritize a **real extraction/template-chain adapter tested on synthetic stellar-only
shifts**, followed by the candidate-only RV-standard archive cross-match above. These produce
direct evidence about signal transmission and spurious RVs without looking again at the
science target. Retain eta Tel B as a spectral-type/observing-mode transfer candidate, not
independently proven zero-RV truth. Retain GJ 229 as a component-aware stress test and V340 Ara
as a wider-slit pulsation stress test, with each limitation explicit.

If that search still yields no suitable observed positive control, say so. Full synthetic
and semi-synthetic validation can strengthen a locked reanalysis but cannot silently satisfy
the draft's independent observed-positive requirement. A new H1567 control observation or
external collaborator with an independently characterized matching series may then be the
scientific resource needed. No observing request, author contact, or protocol relaxation is
authorized or performed by this memo.

The control suite is still incomplete. This is progress toward a stronger test, not evidence
for or against the reported satellite.

## 4. Bounded coordinate follow-up: no H1567 match in sampled standard headers

The recommended candidate-only coordinate screen was subsequently performed for **GJ 447,
GJ 588, and GJ 784**, excluding the GJ 229 vicinity. Its exact SIMBAD/TAP queries, full
aggregate TAP response, representative frame identifiers, parsed header cards, and header
text hashes are retained in
[`m38-null-standard-metadata-2026-09-06.json`](../evidence/m38-null-standard-metadata-2026-09-06.json).
This is a metadata evidence artifact, not a selected-control or spectral-product manifest.

SIMBAD resolves these candidates to Ross 128, CD-40 9712, and HD 191849, respectively, with
Gaia EDR3-referenced J2000 coordinates and proper motions. A 90-arcsec cone around each J2000
position covers its linear proper-motion displacement through 2026.7 with margin; this is
not a full astrometric propagation or a guarantee of complete archive pointing metadata.
The ESO query uses its documented `s_region` spatial field, dates from 2021-06-01 through
the exclusive upper bound 2026-09-07, spectroscopic techniques, and both `OBJECT` and
`STD,RV` types. It does **not** restrict the observation-category field to `SCIENCE`.

The query returns **23 aggregate groups containing 687 records**, including the observatory
standard records missed by a simple OBJECT-name search. One representative header—the
earliest identifier—was read from each of the 21 non-polarimetric groups. The verified
settings of those 21 headers are:

| Setting | Representative headers |
|---|---:|
| K2192 | 18 |
| Y1029 | 2 |
| J1232 | 1 |
| H1567 | 0 |

All inspected headers specify a 0.2-arcsec slit. The JSON retains each frame ID and its
direct ESO header URL. No matching H1567 night or frame was established by this bounded
screen. **This does not establish that all 687 records lack H1567**: a metadata group can
contain mixed settings, as the V340 Ara check demonstrates. In particular, the sample is
one header per metadata group, not one per observing block or every exposure. The two
polarimetric groups were not sampled and are not admitted as conventional-slit controls.

The next exhaustive step, if warranted, is to inspect all candidate observing blocks and
then every candidate H1567 exposure, preserving explicit setting/cell/mode/slit checks and
independent stability assessment. The present result constrains the lead: it finds extensive
standard-star material and confirms representative K-band data, but does not yet supply the
same-setting H-band null control. No spectra were read and no scientific suitability gate
was changed.
