---
title: 'exosat-rv: A Python Workflow for Radial-Velocity Exosatellite Searches Around Directly Imaged Companions'
tags:
  - Python
  - astronomy
  - exoplanets
  - exomoons
  - radial velocity
  - spectroscopy
  - direct imaging
  - brown dwarfs
authors:
  - name: Matthew Potts
    affiliation: 1
affiliations:
  - name: Independent Researcher
    index: 1
date: 13 August 2026
bibliography: paper.bib
---

## Summary

`exosat-rv` is a Python toolkit for **companion-side radial-velocity searches for
exosatellites**: rather than watching a star for the reflex wobble of a planet, the
method points a high-resolution spectrograph at a directly imaged brown dwarf or giant
planet and looks for the reflex wobble of *its own* satellite. The technique was
proposed by @vanderburg2018 and returned three published non-detections
[@ruffio2023; @vanderburgrodriguez2021; @horstman2024] before @hoy2026 reported a
claimed detection — a roughly Jupiter-mass companion to the brown dwarf
CD-35 2722 B [@wahhaj2011] — from VLT/CRIRES+ spectra [@dorn2023]. `exosat-rv` grew out
of a separately implemented reanalysis of that result from the public ESO archive. Its
extraction configuration was calibrated against the published RV series, so the scientific
result is not an end-to-end independent reproduction. The software repository now provides
the reusable parts of that attempt: archive inventory and provenance auditing,
conversion of ESO pipeline products into the layout the `viper` radial-velocity code
[@kohler2025] consumes, a fitter-stage injection-recovery gate used to test velocity
transmission after a template has been built, a period search with
permutation-based nominal null calibration with explicit exchangeability assumptions,
nested-sampling model comparison [@speagle2020],
and a target-feasibility framework built on the detectability calculations of
@lazzoni2022 and extended to a public VLTI/GRAVITY astrometric alternative
[@kral2026].

## Statement of need

Radial-velocity exomoon searches on directly imaged companions are a young, small
field. The method was proposed by @vanderburg2018; three published searches returned
non-detections [@ruffio2023; @vanderburgrodriguez2021; @horstman2024]; and in 2026
@hoy2026 reported a claimed detection. These are target-specific analyses built around
general-purpose radial-velocity tools. The repository addresses reusable validation and
provenance checks that are not exposed uniformly across those workflows, without claiming
priority for doing so.

Those failure modes are concrete, not hypothetical. In the CD-35 2722 B reanalysis,
three separate pipeline changes that *looked* like
improvements to the science target were later shown, by a positive control on the known
binary brown dwarf GJ 229 B, to work by deleting signal rather than recovering it: an
empirical per-order weighting scheme, a telluric order screen, and an under-iterated
self-templating recipe. Each would have been silently adopted, and each would have made
every subsequent non-detection look stronger than it actually was, had the control not
caught it. This is the failure mode `exosat-rv` is built to prevent: its documented adoption
rule scores extraction-recipe changes only against externally fixed values — a paper's published
radial velocities, or a synthetic injected signal — and nothing is adopted on the
strength of an internal metric alone. That discipline, more than any single
measurement, is the project's most transferable contribution, and it is the part a
target-specific search is most likely to skip under time pressure. `exosat-rv` packages
it as runnable, version-controlled code rather than as a methods-section paragraph. A shared
core supplies the injection, control, and significance concepts, while campaign-specific
drivers remain in `scripts/`; the repository does not yet expose one uniform installed API
for every from-raw target workflow.

The package also lowers the barrier to attempting this kind of search at all. Locating
the right archive holdings for a given companion is itself nontrivial: target names are
inconsistent across ESO's archive, programme names do not identify the science target,
and reduced-product band metadata (`filter_path`) is documented, in this project, to be
wrong in specific and recurring ways. `exosat-rv inventory` and `exosat-rv targets`
encode those corrections once so a new user does not have to rediscover them from raw
archive queries.

## Functionality

The installable package (`exosat-rv`, MIT-licensed, Python >=3.11,
`pip install -e ".[dev]"`) exposes a `typer`-based command-line interface —
`inventory`, `probe`, `targets`, `alias`, `orbits`, `survey`, `closein`, `orders`,
`gravity` — covering: archive inventory and public/embargoed/reduced-product
bookkeeping against the ESO TAP service and the NASA Exoplanet Archive; lossless
conversion of ESO `calib_level=2` CRIRES+ products into the per-order, per-detector
layout `viper` requires; alias-period discrimination via injection-recovery on the
observing cadence; a BIC-based approximation to nested-sampling model comparison,
run directly against a paper's published radial-velocity table; a companion-feasibility
survey across the directly imaged companion population, calibrated on achieved rather
than forecast instrumental precision; and a query layer for public VLTI/GRAVITY
astrometry as a distinct, non-spectroscopic route to the same question. The offline unit
and integration suite passes, with live-archive checks separately network-marked. CI currently
runs those offline tests on Python 3.11 and 3.12; lint is not yet a CI job and should be
checked separately before release.

The from-raw extraction pipeline itself — driving `cr2res` and `viper`, the
injection-recovery gate, the permutation-based nominal period-search calibration, and the
`dynesty`-based nested-sampling comparison — is implemented as an accompanying suite of
analysis and reduction scripts (`scripts/`) rather than inside the installed package,
and is documented as a runbook (`docs/viper-runbook.md`) aimed at reconstructing the
author's own pipeline rather than as general-purpose end-user API documentation. Every
scientific conclusion the project has recorded, together with the traps that produced
a wrong one along the way, is indexed in `LESSONS.md` and the per-milestone
`M*-RESULTS.md` series that accompanies the code. The adopted M14/M15 RV/per-order/BERV,
parameter and target tables, the VIPER configuration and tracked source patch observed in the
audited checkout, and their hashes are frozen in `data/repro/`, enabling offline downstream
reanalysis. That configuration records checkout state only; it does not prove which
configuration governed the historical extraction runs. Raw/reduced ESO spectra and fitted
templates remain external (the latter hash-bound), so the research-script layer does not yet
replay raw exposures through template construction from Git alone.

## Acknowledgements

Development of this project — including its literature search, pipeline
implementation, statistical analysis, and this manuscript — was carried out by AI
agents (Claude, Anthropic, via Claude Code) directed and reviewed by the author, who
set the research questions, verified the agents' claims, and takes sole responsibility
for all content. This follows the disclosure practice already established for the
project's scientific manuscript: see the AI contribution and responsibility statement
in `docs/paper/draft.template.html` and the stage-by-stage checklist at the repository
`docs/AI-CHECKLIST.md`.

## References
