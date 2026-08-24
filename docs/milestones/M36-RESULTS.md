# M36 — The paper-blind selection is inconclusive, and the gate that let it through was mine

**Pre-registration: [`M36-PREREGISTRATION.md`](M36-PREREGISTRATION.md), committed before the
first run.** This document reports what happened. The short version is that the experiment
did not answer its question, that the reason is a defect in the protocol rather than
anything about the data, and that the defect is one this project has catalogued before.

**It is not evidence against the M14 detection.** It is an experiment that failed to be
sensitive, which is a different thing and must not be read as the first.

---

## 1. What ran

All 36 pre-registered configurations, 2397 s of wall clock, exactly the grid in the protocol:
order set × oversampling × κσ × telluric treatment, iteration-1 template throughout, each
configuration scored only against its own uninjected run. No published value was read at any
point before the blind search, and the runner
([`m36_blind_selection.py`](../../scripts/injection/m36_blind_selection.py)) imports nothing
that could load one.

## 2. The selection metric did not measure anything

| quantity | value |
|---|---|
| recovery slope, range across the grid | **-12.30 to 1.99** |
| slope uncertainty, range | **±0.48 to ±6.12** (median ±1.64) |
| configurations passing the gate `slope ∈ [0.80, 1.20]` | 3 of 36 |

A recovery slope of 1.0 means an injected velocity is recovered at full amplitude. For
comparison, the injection gates M15 and M20 report on the adopted configuration run at
**99-101% +- 1%**. Here the median uncertainty is **+-1.64**, which is more than a hundred
times looser, and the three configurations that passed the gate passed it on point estimates
that their own error bars render meaningless:

| arm | slope | 2σ interval |
|---|---|---|
| `M36_c19` | 0.970 ± 2.280 | [-3.59, 5.53] |
| `M36_c26` | 1.130 ± 1.540 | [-1.95, 4.21] |
| `M36_c27` | 1.140 ± 0.920 | [-0.70, 2.98] |

Every one of those intervals contains **0** — total signal destruction — and two contain
negative slopes, meaning an injected positive velocity coming back negative. The gate
selected on the point estimate and said nothing about its uncertainty, so it could not
distinguish a configuration that recovers the signal from one that has no idea.

## 3. The blind search, run anyway because the protocol says so

A pre-registration is not something to abandon when the intermediate result is
disappointing, so §6 was executed on the winner (`M36_c19`) unchanged. Full output:
[`../../data/m36-blind-search.txt`](../../data/m36-blind-search.txt).

| variant | n | best peak near 171 d | ΔBIC | K (m/s) | rank |
|---|---:|---:|---:|---:|---:|
| mean, all epochs | 18 | 168.3 d | -4.4 | 3878 | >6 |
| mean, +BERV covariate | 18 | 161.6 d | -5.3 | 2376 | >6 |
| mean, internal screen | 17 | 174.9 d | +4.6 | 4141 | 4 |
| mean, screened, +BERV | 17 | 182.0 d | +7.2 | 5803 | 6 |
| mean, matched only | 17 | 174.9 d | +4.6 | 4141 | 4 |
| mean, matched, +BERV | 17 | 182.0 d | +7.2 | 5803 | 6 |
| median, all epochs | 18 | 173.2 d | -3.9 | 4174 | >6 |
| median, +BERV covariate | 18 | 161.6 d | -5.6 | 1377 | >6 |
| median, internal screen | 17 | 182.0 d | +3.5 | 2472 | >6 |
| median, screened, +BERV | 17 | 182.0 d | +3.8 | 2764 | >6 |
| median, matched only | 17 | 182.0 d | +3.5 | 2472 | >6 |
| median, matched, +BERV | 17 | 182.0 d | +3.8 | 2764 | >6 |
| clip, all epochs | 18 | 175.9 d | -3.0 | 5171 | >6 |
| clip, +BERV covariate | 18 | 161.6 d | -5.6 | 1405 | >6 |
| clip, internal screen | 17 | 182.0 d | +8.3 | 3276 | 5 |
| clip, screened, +BERV | 17 | 182.0 d | +7.2 | 3516 | >6 |
| clip, matched only | 17 | 182.0 d | +8.3 | 3276 | 5 |
| clip, matched, +BERV | 17 | 182.0 d | +7.2 | 3516 | >6 |

Read literally against the protocol's outcome table this is the middle row — a peak present
at ΔBIC 3–10 but never at rank 1. **That reading would be wrong**, and the reason is in the
K column.

## 4. Why the series are not usable

The fitted semi-amplitudes above run to **9,656 m/s**, and the top-ranked peaks of the search
sit at 8.5 d with K between 1,377 and 8,837 m/s. The signal this project actually measures on this
object is **K ≈ 306 m/s published, 380–470 m/s fitted here** (M14). A fit returning thousands
of m/s on a brown dwarf is not a velocity; it is the search fitting noise, and the 8.5 d
top peak is the sampling rather than the sky.

So the substantive outcome is the protocol's **fourth** row, not its second: *the paper-blind
family cannot extract usable velocities at all, and therefore states nothing about the
period.* Three configurations cleared a numerical gate; none of them cleared it meaningfully.

## 5. The defect, named

The gate constrained `|slope − 1|` and never constrained `slope_err`. That is the same error
this project already catalogued in M28 §6.5 — *an injection-gate uncertainty quoted as an
epoch-to-epoch standard deviation is meaningless at n = 2* — reappearing one level up: a gate
on a point estimate is meaningless when the estimate is unconstrained. `LESSONS.md` says
every adopted change must pass injection recovery; it does not yet say that a recovery number
without a usable error bar is not a pass. It should, and now does.

**The amended gate for any re-run:** eligibility requires `slope ∈ [0.80, 1.20]` **and**
`slope_err ≤ 0.10`. On this grid that admits **zero** configurations, which is the honest
answer this run should have produced directly.

## 6. The likely cause, and what it costs the original question

The protocol excluded iteration-2 templates deliberately, because the decision to iterate
twice was itself taken against the published series (M14 §6). M14 also found that the second
iteration is *the decisive change* — the one that takes the extraction from unusable to
usable, with per-nodding only sharpening it afterwards.

Those two facts together are the trap this design walked into. **Removing the paper's
influence also removed the ingredient that makes the extraction work**, so the experiment
cannot separate its two candidate explanations:

- the ~171 d period depends on configuration choices made with the paper in view; or
- iteration-1 templates simply cannot measure this object, whatever the period is.

The results here are entirely consistent with the second, and the K values argue strongly for
it. **The original question therefore remains open**, and M34 §3's statement of it stands
unaltered.

## 7. What a valid version would need

Not a re-run of this grid with a tighter gate — that would be choosing the gate after seeing
the slopes, which is the exact failure mode this experiment exists to avoid. It needs a
template-iteration rule that is *itself* paper-blind:

1. iterate the template until an **internal** convergence criterion is met (e.g. the change in
   the template between iterations falls below a fixed threshold), with the criterion and the
   threshold pre-registered before running;
2. re-run this grid on top of that template;
3. gate on slope **and** `slope_err ≤ 0.10`;
4. blind search on the winner.

That is a genuinely different experiment and needs its own pre-registration. It is **not**
started here, because writing it after seeing these numbers would need saying so plainly, and
the honest sequence is to record this outcome first.

## 8. Reproduce

```bash
cd "$(wslpath -a .)"
~/viperenv/bin/python scripts/injection/m36_blind_selection.py --dry-run   # the grid
~/viperenv/bin/python scripts/injection/m36_blind_selection.py            # ~40 min
```

Outputs `data/m36-selection.json`. The 684 viper series live in `~/viper-src/M36_*` and are
outside the repository, as all viper output is.
