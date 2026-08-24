# M36 — Pre-registration: select the extraction configuration by injection recovery alone

**Status: PROTOCOL. Nothing has been run. Written and committed before any result exists,
which is the only thing that makes it a pre-registration.**

`M34-RESULTS.md` §3 names this as "the cleanest available strengthening of the reproduction",
and it is the last open experiment in the project that could change what Paper I is entitled to
claim. This document fixes the procedure. It must be committed before the first viper run.

---

## 1. The question

M34 established that the ~171 d period survives in configurations that agree *poorly* with the
published series, which rules out the crudest form of circularity. What it explicitly could not
establish is the boundary of the family:

> Every configuration in the sweep is drawn from a family that was itself explored with the
> published series available, so this bounds the effect of choosing *within* that family, not
> the effect of the family's boundaries.

The concrete contamination is visible in the adopted run's own output header. `M14_T2` uses
orders **4, 7, 8, 9, 10, 12, 13, 14, 17, 18, 19** — the eleven orders M13 identified *by
matching the published paper*. The order set, the single largest configuration choice, was read
off Hoy et al. So:

**Does the ~171 d period survive when every configuration choice, the order set included, is
made without the published series ever being consulted?**

## 2. What is forbidden

Until the blind search in §6 has run and its result is written down, the following may not be
computed, looked at, or used in any way:

- rms against the published radial velocities (`rms_pub`), by any route;
- the published period, K, or evidence values;
- the eleven-order set, or any order list derived from the paper;
- any of the existing `M13_*` / `M14_*` series, whose selection is already contaminated.

The reference series for each configuration is that configuration's own uninjected run. Nothing
external enters.

## 3. The configuration grid, fixed here

Four axes, chosen because viper exposes them and they plausibly change an extraction, with
values spanning good and bad so the selection rule has something to reject. Full factorial,
**36 configurations** (3 × 3 × 2 × 2).

> **Amendment, before execution.** This document first said 24, which is simply wrong
> arithmetic — 3 × 3 × 2 × 2 = 36. Corrected here, and committed before the first viper run,
> with no axis and no value changed. The dry run is what caught it.

| axis | values | why these |
|---|---|---|
| `-oset` | `2:20` (every order the product carries), `2:11`, `11:20` | the paper-blind replacement for the eleven orders: take them all, or take a half each way |
| `-oversampling` | 1, 2, 4 | M14 found this mattered; 1 and 4 are included so 2 has to earn it |
| `-kapsig` | 3.0, 4.5 | viper's default is 4.5; 3.0 clips harder |
| `-telluric` | `sig`, `mask` | downweight versus mask, the two treatments viper offers |

Held fixed at viper's defaults: `-chunks 1`, `-deg_norm 3`, `-deg_wave 3`, `-iset 380:1700`,
`-nocell` (M12: the cell is not there). The template is `M13tpl_tpl.fits` at iteration 1 for
every arm — iteration 2 is *not* used, because the decision to iterate twice was itself taken
against the published series (M14 §6).

## 4. The selection rule, fixed here

For each configuration:

1. Run viper on all 18 epochs, uninjected. Call this `REF_c`.
2. Build injected templates with `scripts/injection/mktpl.py` from `inject_plan_big.json`
   — the plan already in the repository, unchanged — and run viper per injected epoch.
   Injection is applied to the **template, never the observation** (M12).
3. Score with `scripts/injection/inject_score2.py`, which returns the **slope of
   (RV_injected − RV_reference) on the injected velocity**. Perfect recovery is slope 1.0.
   This number never touches a published value.

**Gate.** A configuration is eligible only if its recovery slope lies in **[0.80, 1.20]**.
**Winner.** Among eligible configurations, the one minimising **|slope − 1|**.
**Tie-break** (within 0.005): the smaller across-order dispersion of the per-order slope.
**If nothing is eligible**, that is the result and the experiment stops there; the winner is not
chosen from ineligible configurations.

These thresholds are set now, before any slope is known.

## 5. Why an amplitude gate and not a precision one

Because this project has already been burned twice by the alternative. M9 found that the
best-looking RV improvement worked by deleting the signal, and M11 found the published template
recipe halves recovered amplitude on a known binary. Any metric that rewards *quiet* rewards
signal destruction. Recovery slope is the one metric that cannot be gamed that way: a
configuration that suppresses the signal scores 0.5, not 1.0, and fails the gate.

## 6. The blind search

On the winning configuration's `REF` series only, run
`scripts/injection/blind_search.py` with the BERV covariate, unchanged. Record, before any
comparison with Hoy et al.:

- the top-ranked period and its ΔBIC;
- the rank of any peak in 160–185 d;
- the fitted K.

## 7. What the outcomes mean, decided in advance

| outcome | reading |
|---|---|
| a peak at 160–185 d, rank 1, ΔBIC > 10 with the covariate | the reproduction is independent end to end; the period is in the spectra, not in the tuning |
| such a peak present but rank > 1, or ΔBIC 3–10 | survives, weakened — report as "present but not dominant", the M34 §3 language |
| no peak in that band above ΔBIC 3 | the detection depends on configuration choices made with the paper in view. **This would be a material result and must be published as one**, not quietly filed |
| no configuration passes the gate | the paper-blind family cannot extract usable velocities at all; states nothing about the period |

## 8. The honest limit of this design

Whoever runs this **already knows what M14 found**. A pre-registration written by someone who
knows the answer is weaker than a true blind, and no amount of procedure fixes that. What this
design does establish, and all it establishes, is narrower and still worth having: **the
selection metric never saw the published series, and the order set was not inherited from the
paper.** The grid in §3 was chosen before any of it was run, and this file is committed before
the first run so that the claim is checkable in the git history rather than asserted.

A genuinely blind version of this experiment needs someone who has not read Hoy et al. That is
not available here, and saying so is part of the result.

## 9. Cost

A single viper run on one epoch takes **3 s** (measured, H band, five orders). Each
configuration is 18 uninjected epochs plus 18 injected ones, so ~2 min; the 36-configuration
grid is **about 35 minutes**, and viper's outputs are kilobytes — the disk pressure recorded in M30
constrains cr2res re-reductions, not this.
