# Agent instructions — exosat-rv

This file is operational guidance, not the public project overview. Keep `README.md` written
for research readers. These project-specific rules qualify older operational notes where
they conflict; explicit user instructions still govern the current task.

## Before work

1. Check `git status` and recent commits; preserve others' changes and stay in **exosat-rv**.
2. Read `docs/ONBOARDING.md`, `docs/LESSONS.md`, and the M37 audit before science changes.
   Read the relevant milestone and its superseding notices before changing a driver.
3. For M38, read `docs/validation.md`, the draft protocol, and the specific experiment plan.
   Coordinate file ownership when agents work in parallel. Never reuse a milestone filename
   without checking that it is free.

## Scientific boundaries

- Current research is paper-calibrated and screen-conditional, not independent confirmation.
  M37 controls claim wording. Historical published-RV scoring is not a rule for future
  independent selection; do not reuse target-aware settings as if independently chosen.
- Before the M38 protocol is reviewed/frozen and its independent roles and control gates
  exist, do not inspect or mount CD-35 raw/reduced spectra or fitted templates, even for a
  smoke test. Do not run a claim-bearing M38 target stage or re-enable M36's non-dry runner.
- Synthetic pre-template injections shift the **stellar component before** telluric
  multiplication and LSF convolution. The old “shift the template” lesson describes a
  fitter-stage test only, not the M38 operator. Never shift the observed composite spectrum.
- Execute synthetic VIPER experiments in a private minimal runtime, never in the shared
  historical installation. Do not copy target products, atlases, or templates into fixtures.
- Retain actual failures, input/config/source hashes, seeds, and explicit scope limits.
  Do not adopt an estimator or promote a protocol merely because a toy simulation passes.

## Files and verification

- Follow `docs/organization.md`. Preserve existing scientific paths and hash-bound artifacts.
  Edit sources, not generated report blocks/HTML; use the owning renderer and check mode.
- Run checks proportionate to the change; `CONTRIBUTING.md` lists the baseline. For target-free
  M38 work, select synthetic tests explicitly rather than executing historical target drivers.
- Use the interpreter that actually has the required dependencies; do not assume a particular
  machine path exists. Historical reduction environments are not supplied by a package install.
- Preserve LF line endings. **Do not use bulk deletion plus checkout to repair them**, despite
  the historical recipe in older notes. Inspect affected files, preserve changes, and perform
  a narrowly scoped non-destructive normalization when authorized.
- Do not delete raw data, caches, runtime directories, or evidence without exact scoped
  authorization. Historical storage-cleanup advice is not standing deletion permission.
- Read failure logs and fix causes. Never bypass verification or force a Git operation.

## External actions

Do not push or merge without user authorization. Submission, formal release/tag/DOI deposit,
email, publication, and destructive actions require their own explicit approval. Permission
to update GitHub code does not authorize those separate actions. No cross-project changes.
