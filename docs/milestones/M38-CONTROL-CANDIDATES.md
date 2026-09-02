# M38 control-candidate evidence dossier — no selection

> **RESEARCH DOSSIER ONLY / NO CONTROL IS FROZEN / NOT AUTHORITY TO RUN M38**
>
> This document screens candidate development controls from existing documentation and
> literature. It does not open, download, hash, or analyse any spectrum. It does not establish
> scientific suitability or independent truth, and it does not close the
> `control_targets_and_truth` decision in the M38 register.

## Required control classes

[The M38 draft](M38-PROTOCOL-DRAFT.md#31-development-data) requires all three of the following
before a target run:

1. fully synthetic CRIRES+ H-band exposures with exact known component shifts;
2. at least one same-setting stable/null control; and
3. at least one same-setting positive-RV control with truth established independently of this
   project.

The exact epochs, content hashes, truth assertions, exclusion rules, reviewers, and freeze
chronology remain blocking inputs. A useful engineering example is not automatically an
admissible scientific control.

## Candidate screen

| candidate | same-setting evidence | useful role | blocking limitation | dossier status |
|---|---|---|---|---|
| caller-generated synthetic H-band ensemble | generated rather than observed; the setting/sampling/LSF/noise contract must be declared explicitly | known stellar shifts, invariant tellurics/LSF/noise, fold leakage tests, failure and coverage experiments | exact parameter axes, distributions, counts, seeds, generator artifact hash, and realism evidence are unresolved | **required class; design not selected** |
| eta Tel B | [M15](M15-RESULTS.md) records 20 public H1567 epochs in the same setting | stable/null and transfer candidate | the project has no independent published RV truth for stability; M15 used historically target-informed choices and fitter-stage rather than pre-template injection. Exact products must be re-manifested and an independent reviewer must justify the truth assertion | **retain as a candidate; not frozen** |
| GJ 229 B | [M3](M3-RESULTS.md) records six H1567 nights and an independently known short-period binary | high-amplitude signal-retention and self-template-absorption stress control | the unresolved double-lined spectrum makes the single-template centroid amplitude model-dependent. M38 already forbids using it as the only positive control | **retain as a stress control; not sufficient alone** |
| V340 Ara | archive screening found 14 public H1567 conventional-slit frames on 2022-04-19 and 2022-08-10; the slit was 0.4 arcsec, not the desired 0.2 arcsec | conditional high-amplitude night-level positive candidate; independent optical Cepheid series establish roughly 48--59 km/s peak-to-peak variability | the optical-to-H-band centroid transfer is not rigid, the two-night phase prediction is extrapolated, and the slit/spectral type differ; exact archive products and calibrations have not been frozen | **preferred conditional positive candidate; not sufficient or frozen** |
| HD 209458 | four public H1567 0.2-arcsec transit sequences and independently established planetary reflex motion | exact-slit, low-amplitude physical check if sub-night epochs are admissible | all visits repeat transit phase and the within-sequence orbital swing is only about 30--36 m/s, so it does not supply a robust night-level positive | **complementary engineering check; reject as primary night-level positive** |
| HD 73256 | Hahlin et al. observed four CRIRES+ H1567 epochs (2021-10-08, 2021-10-30, 2022-02-07, and 2022-03-30; reported median S/N 149–250) | initially appeared to offer a bright, multi-epoch same-setting positive control | the claimed 2.55-day, 269 m/s signal was not recovered by Ment et al.; the NASA Exoplanet Archive classifies HD 73256 b as a false positive. It is therefore not a defensible positive-RV truth source | **reject as the primary positive control** |

Primary sources for the HD 73256 screen are
[Hahlin et al. 2023](https://doi.org/10.1051/0004-6361/202346314),
[Ment et al. 2018](https://arxiv.org/abs/1809.01228), and the
[NASA Exoplanet Archive system record](https://exoplanetarchive.ipac.caltech.edu/overview/HD%2073256%20b).

The V340 Ara screen is supported by three independent optical RV analyses:
[Pedicelli et al. 2010](https://doi.org/10.1051/0004-6361/201014262),
[da Silva et al. 2022](https://doi.org/10.1051/0004-6361/202142957), and
[Hocde et al. 2024](https://doi.org/10.1051/0004-6361/202347798). The da Silva series gives
32 FEROS/UVES epochs and a 20.811386-day period; a screening-only phase projection places the
two public H1567 nights near phases 0.552 and 0.972 and suggests an inter-night change of order
10--13 km/s. That projection is not an H-band truth record. Published optical/infrared Cepheid
comparisons show wavelength-dependent line profiles and asymmetries, so a future review must
define a conservative directional/minimum-shift truth rather than assume unity recovery of the
optical curve ([Nardetto et al. 2018](https://doi.org/10.1051/0004-6361/201833210)).

HD 209458's independent orbital truth is approximately 85.1 m/s semi-amplitude at a 3.5246-day
period ([Naef et al. 2004](https://doi.org/10.1051/0004-6361:20034091)); the public CRIRES+
sequences are described by [Blain et al. 2024](https://doi.org/10.1051/0004-6361/202450767).
These references establish useful candidate physics, not M38 control admissibility.

## Current decision

No complete observational suite is selected. Archive and literature screening now identifies
V340 Ara as a conditional second positive candidate, but not a sufficient same-configuration
truth: its 0.4-arcsec slit and optical-to-H-band transfer remain material mismatches. If M38
strictly requires a 0.2-arcsec same-setting control with an independently established
night-level H1567 amplitude, no sufficient public candidate has been found. That absence is a
hard scientific gate, not a reason to weaken the requirement or promote a convenient candidate
automatically.

Before any candidate can enter a frozen suite, an independent reviewer must verify and bind:

- the exact instrument setting, epoch roster, exclusions, and immutable product hashes;
- a truth statement and uncertainty model that predate and do not depend on this project's
  target result;
- independence between the truth source, development scoring, and final control review;
- suitability across spectral type, S/N, sampling, line density, and expected RV scale;
- the role each control is allowed to satisfy, including an explicit prohibition on one object
  silently satisfying incompatible null and positive roles; and
- the complete pre-template execution route used for the synthetic and observational controls.

Until those records are reviewed, signed, and frozen, this dossier supports only further
target-free development and candidate research.
