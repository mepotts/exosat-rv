# LESSONS — the consolidated trap catalog (exosat-rv)

**Read this file first.** It exists so no future agent re-learns these the hard way.
Every entry was paid for with a wrong result, a dead run, or a retraction.
Reading order for a new session: this file → `HANDOFF.md` banner →
`docs/target-queue.md` (the roster ledger) → the latest `M*-RESULTS.md`.

Historical scoring law, stated once: **every adopted extraction change was scored with
`scripts/injection/vs_published.py` against the published RVs, never an internal
metric, and had to pass fitter-stage injection recovery first.** Success was
"rms_pub ≤ threshold AND the downstream period search survives the BERV covariate" — both,
not either. M37 makes the consequence explicit: this is a paper-calibrated reproduction
workflow, not an end-to-end independent test. A future independence experiment must hold the
published values out rather than reuse this scoring law.

---

## 1. Method traps (the ones that produce *wrong science quietly*)

| # | Trap | Symptom | Rule |
|---|------|---------|------|
| 1 | viper modeled a gas cell that wasn't there | +283 m/s of structured residual | `-nocell` always for CRIRES+; check instrument config before trusting defaults (M6) |
| 2 | Template built from telluric-contaminated coadd | RV–BERV correlation the authors don't have | Telluric-clean the template; verify r(RV,BERV)≈0 after (M6) |
| 3 | Self-templating absorbs the signal | Known binary's amplitude halved | Any template recipe must pass injection recovery; M12 makes this conditional, not absolute (M11/M12) |
| 4 | Injection by shifting the *observation* | 92% of the injected shift absorbed → fake 100% gates | **Shift the TEMPLATE, never the observation** (M12 §8.1) |
| 5 | Optimizing a metric the signal can game | "Best" change worked by deleting the signal | Controls must be amplitude-matched; prefer signal-invariant metrics (across-order dispersion), and size a fix before ranking it (M9/M10) |
| 6 | Single-night template | 4.7 km/s BERV-locked artifact (r=+0.94) on beta Pic b | **Never build a template from one night** — no BERV lever to separate target lines from telluric residue (M20) |
| 7 | Template ladder upgraded without re-gating | PDS 70 9-night template: −62% injection recovery, a *fake-quiet* series that looks like an improvement | **Gate every template iteration**, not just the first; keep a bit-for-bit restore script (`m21_restore.sh`) (M23) |
| 8 | Phase–BERV degeneracy | CD-35's blind peak entangled with BERV at r=−0.71 | Ten-minute phase–BERV geometry pre-check **before** any campaign compute (M15, permanent) |
| 9 | Claiming "first ever" | "First RVs of beta Pic b" was wrong (A&A 2024 got there) | Literature-search every first; hedge as "to the best of our knowledge"; log corrections in place (M20 §5) |
| 10 | Trusting the mode label | The entire "staring" tier was actually **HiRISE fiber data**; slit-recipe reductions produced km/s artifacts we mistook for sky physics | **Check `INS MODE` + `ORIGFILE` in raw headers before classifying any dataset**; three ledgered verdicts had to be retracted (M27 banner, target-queue) |
| 11 | An injection gate read without its error bar | M36: three configurations "passed" `slope in [0.80, 1.20]` on 0.97 +- 2.28, 1.13 +- 1.54, 1.14 +- 0.92 — every 2-sigma interval containing **0**, i.e. total signal destruction | **A recovery number with no usable uncertainty is not a pass.** Gate the error too: this project's working configurations gate at 99–101% ± 1%, so require `slope_err <= 0.10` alongside the slope. Same family as M28 §6.5, one level up |
| 12 | Calling a screen-conditioned permutation probability “global” | The near-171 d peak is strong on 17 internally retained nights but all BERV-adjusted 18-night searches are compatible with noise | Always show the complete-series result beside the screened one. “Global” covers the period grid only; it does not pay for choosing an epoch screen. Treat the detection as conditional until the screen is fixed before new data (M37) |
| 13 | Assuming a preregistration proves what the runner executed | M36's prose fixed polynomial degrees and a wavelength interval that its command never passed; filename-only caches silently reused old products | Print and test the effective argv, pass every held-fixed value explicitly, bind caches to content/configuration manifests, and audit conformance before reading results. A post-audit code fix cannot rehabilitate a historical preregistered artifact (M37) |
| 14 | Calling a shifted-template injection “end to end” | Recovery validates the fit against an already-built template but cannot reveal signal absorbed while that template was constructed | Name the boundary **fitter-stage transmission**. A template-construction claim needs injection before template building, and injected/reference means must use the same valid-order intersection (M37) |

## 2. viper quirks (mechanical, cost hours each)

- K-band branch is **1-indexed**: `oset 1:19` for K2166, `1:18` for K2192 (order 02 has no det3). H-band is 0-indexed. Getting it wrong = `KeyError '08_01_ERR'`.
- `-ip` is a dead knob in this configuration — changing it does nothing; don't tune it.
- viper's *printed* rms is not the rms of its RV output column. Score from the column.
- Order mapping assumes the last table column is the reddest (`names[-1]`); staring/HiRISE products can store columns **descending**, which silently inverts the mapping.
- `-wlen` must match the product's actual setting; converter (`m15_convert.py`) validates per-order detector monotonicity (global det-means false-alarm on K2192).

## 3. ESO archive traps (all seven+ documented in `docs/target-queue.md`)

1. **`filter_path` lies** — seven documented cases. Product headers are the only band truth.
2. TAP caps at 20k rows (`MAXREC`) *silently* — window big queries by year (`m25_census2.py`).
3. calSelector returns **zero** calibs for HiRISE/staring frames — fall back to a direct `dbo.raw` CALIB query by night+setting (`m19_urls_from_raw.py`).
4. Old files are `.Z` (LZW) — Python needs `uncompresspy`.
5. Datalink host flakes — go straight to `dataportal.eso.org` URLs.
6. **Serial downloads only, and pace them.** Parallel lanes lost 37 files mid-batch. A long
   serial run also gets throttled: after 39 consecutive fetches a 21-file batch returned
   **21/21 failures** while the same URL succeeded on a manual retry seconds later, and the
   batch still exited 0 (M29). Wrap each fetch in a 3-try loop with a short sleep between
   files, and judge by `ls *.fits`, never by the exit status. The throttle window can
   outlast a retry loop -- a 3-try loop with 5 s sleeps failed all 21 files, then the
   identical command succeeded minutes later. Probe one URL by hand before concluding
   anything is wrong with the URLs or the resolver, and skip files already on disk so a
   rerun is cheap. Skip-existing must be size-validated (`find -size +1M`); judge a night by files on disk, never by attempt logs.
7. Targets hide under **host-star and programme names** — only a coordinate census with reverse sky-clustering finds them (that's how YSES 1 b's record series and beta Pic b's K campaign were found).
8. The archive's "staring" datasets are **HiRISE** (fiber-fed SPHERE→CRIRES+). See trap 1.10.

## 4. cr2res reduction traps

- Mixed-setting nights crash `obs_nodding` ("Expect only one DROT POSANG") — split SOFs per setting (queued: cd35d1).
- **HiRISE/fibre data needs the `util_*` recipes, not `obs_*`.** `cr2res_util_trace`'s
  `smooth_y` defaults to **401 px**, sized for a ~180 px slit order; a fibre trace is
  **2-9 px** and is smoothed away before detection. Use `util_calib` -> `util_trace`
  (small `smooth_y`, `min_cluster`) -> `util_extract` (`--height` a few px, `--method SUM`).
  The `obs_*` recipes are slit-geometry wrappers; the utilities underneath are general (M29 §15).
- A recipe can "succeed" in 0.656 s and write **empty extractions** (YSES 1 2022) — staging must verify *table contents*, not file existence.
- **`cr2res_obs_nodding` requires an EVEN number of science frames.** That *is* the YSES 1 2022 cause, found M29: an 8-exposure template aborted after 7 (the archive holds 7 too — nothing was lost in download), leaving 3 A and 4 B. The log says `Require an even number of raw frames` / `Invalid Inputs` / `Failed to reduce detector 1,2,3` — and the recipe then writes **all 11 products anyway, empty, and exits 0**. Drop one frame to make the count even. Check `ESO TPL EXPNO` vs `ESO TPL NEXP` at staging: an aborted sequence is common and silent.
- Some frames arrive with UTC/LST stripped — patch placeholder keywords at staging (AF Lep).
- Dark failures are non-fatal (`reduce_one.sh` continues); missing darks ≠ dead night.
- Delete raw after a reduction verifies — raw kept "just in case" filled 1007G to 100% and killed a batch.

## 5. Ops rules (WSL/Windows/harness)

- Long shell chains go in **committed script files** — inline one-liners died silently twice and cost whole runs.
- **`cr2res_obs_nodding` needs an EVEN frame count** — see §4. An aborted template leaves an odd number and the recipe writes 11 empty products at exit 0.
- **Line endings break DATA files too, not only scripts.** A URL list written by Windows
  Python (`open(p,'w')`) carries `
` on every line. `curl` still fetches -- the CR is
  dropped from the request -- but any shell check built from the same string looks for
  `NAME
.fits` and never matches, so every success scores as a failure and the loop
  retries forever. This was misdiagnosed twice as archive throttling before `od -c` on
  the list settled it (M29). **Write LF explicitly (`newline="
"`), or generate the
  list inside WSL.** The lists written WSL-side in the same session were clean.
- **Line endings will break every script in this repo.** Git is configured `core.autocrlf=true`, so it rewrites `*.sh` to CRLF on checkout; WSL's bash then fails with `$'
': command not found`, a bogus `No such file or directory` on the sourced env file, and a syntax error — while the *task* still reports exit 0. All 39 shell scripts were in this state (found M29, after a "completed" reduction had done nothing). Pinned in `.gitattributes` (now `* text=auto eol=lf` for the whole repo, since data files break the same way) -- but a pin acts **at checkout only**, so it cannot repair a clone whose files predate it. The defect came back intact when this repo was split out of the monorepo: `.gitattributes` arrived one commit after the files did, and 104 of 155 tracked scripts sat CRLF while `git status` read **clean** the entire time, because git normalises on the way *in*. `cr2env.sh` was among them, so `PATH` gained a component ending in CR and esorex silently left the PATH. After any clone, split or re-clone, interrogate the working tree, not the index: `git ls-files -z "*.sh" "*.py" "*.sof" | xargs -0 file | grep -c CRLF` must print 0, and repairs with `git ls-files -z "*.sh" "*.py" "*.sof" | xargs -0 rm -f && git checkout -- .`. Diagnose with `file script.sh` **from inside WSL** — a `grep $'
'` from git-bash reports LF and will mislead you.
- `git commit -F <file>` always; PowerShell here-strings mangle multi-line messages.
- Read **full** logs on failure — `tail -30` hid the actual retry error once.
- Long WSL jobs run as harness background tasks; recover from TAP outages with a probe-then-rerun loop and a 6 h ceiling.
- A result table outside Git is not reproducible because a script path exists. Freeze small
  load-bearing outputs with content hashes and distinguish copied artifacts from hash-only
  external inputs. `data/repro/manifest.json` is the M37 pattern; it deliberately does not
  pretend to reconstruct an uncaptured historical environment.

## 5b. Attribution and sourcing traps (M29 — nine errors in one day, none found by doing science)

A day of checking old work against its actual sources turned up fourteen wrong citations
and thirty-four conflicting property values. Not one was found by producing a new result.
The failure has one shape: **when a fact was not in front of the writer, a plausible one
got generated instead of the source being opened.**

| # | Trap | What it cost | Rule |
|---|------|--------------|------|
| 1 | **The filename is not the citation.** `tokadjian2023_pathways_survival.pdf` contains Makarov & Efroimsky; `martinez2020_ominous_fate.pdf` is Trani et al.; `blunt2026_gravity_*.pdf` is Kral et al. Papers were downloaded correctly by *topic*, named from a remembered author, and every later reader trusted the name. | 14 wrong citations in 60+ places, including a shipped constant `TOKADJIAN_SPIN_RATIO` and user-visible CLI output | **Read the title page. Never cite from a filename, and never verify one citation against another** — verify against the PDF |
| 2 | **An unsourced number will eventually be generated.** The A–B separation was taken as 3.17″ from memory when the repo documents 2.8″; the contamination measurement sampled 161 points instead of 142 and had to be withdrawn. The "2000×/5000×/30 000×" contrast wall was asserted in M20 and propagated to the README, the queue and a draft paper with no derivation anywhere. | one withdrawn measurement; a paper rebuilt three times | **Every externally-sourced number carries its source or the mark UNSOURCED.** A number with neither is a guess with good posture |
| 3 | **Check what a table column actually *is*.** Lazzoni's `Kp` is apparent magnitude (validated on YSES 1 b to 0.14 mag) but wrong by 2.4 mag on β Pic b. Bohn's and Viswanath's equivalent columns are **Δmag, not apparent magnitude** — read the header, or watch whether the value falls J→K→L (contrast) or tracks the host (magnitude). | contrast wrong by ~9×, twice, in opposite directions | **Before using a column, confirm its quantity and band from the paper's own header** |
| 4 | **A true claim decays when the paper publishes.** "H26's reference [11] is Lazzoni" was correct against the preprint and became false on publication — the list went 37 → 47 entries, Lazzoni moved to [10], and [11] became the CRIRES+ instrument paper. | a headline finding wrong in 5 places | **Cite by author, never by bracket number**, and record which *version* a claim was checked against |
| 5 | **Over-correction is its own failure.** After finding the contrast figures underived, this project declared them "wrong by one to two orders of magnitude" — and that was also wrong. The truth needed a third pass. | two reversals on one axis in a day | When a correction rests on a single un-validated input, **say the axis is unresolved** rather than asserting the replacement |

The compounding defence is cheap: `scripts/fetch_paper.py` archives a paper and extracts
its text in one command. Four of the day's errors would not have survived it, and the two
papers whose absence blocked the contrast question (Bohn 2020, Currie 2013) took minutes
to add once anyone looked.

## 5c. The verdict may be about the wrong object (M29)

**Check that the spectrum belongs to the companion before believing anything about it.** A
pair closer than one resolution element cannot be separated, so the extraction is of the
host - and every other check in this project passes anyway:

- the **injection gate** tests whether the *fitter* transmits an imposed velocity, and a
  bright host transmits it better than a faint companion;
- **RV precision** improves on a host;
- **across-order dispersion** improves on a host.

Measured from the nodding slit function at the cost of one file read: `R = separation /
PSF_FWHM`, plus the profile height at the companion's offset. Resolved cases in this project
sit at R >= 1.32 with wing <= 0.15, blended at R <= 0.54 with wing >= 0.55
(`m29_blend.py`). **HD 206893 B's "clean, gates 100-102%" verdict was withdrawn on this
basis.** Beta Pic b's contamination result survives but its mechanism changes: there was
never a resolved companion to contaminate.

Corollary for the instrument case: below R of about 1 no contrast is good enough, because
there is no companion spectrum at all. Fibre-fed suppression is a requirement in that
regime, not an improvement.

### 5d. Check whether a milestone number is taken before writing to it (M32)

M32's results were first written to `M30-RESULTS.md` without checking. M30 existed — the
archive-sweep reconciliation, committed the same day — and the write replaced it. Recovered
from `HEAD` intact, but only because `git status` was read before committing.

Milestone numbers are **allocated across more than one thread and are not sequential in
time**: M29 was still gaining sections while M30 was committed and M31 was open with
uncommitted scripts and no results document. "The highest number I remember" is not the next
free number.

**Before claiming a number:** `ls docs/milestones/M*-RESULTS.md` and `git log --oneline -15`.
**Before committing:** read the status letters. **`M` on a file you believe you just created
means something already lived there.** `A` is a new file; `M` is an overwrite.

The general form: the `Write` tool does not distinguish creating from replacing, so the check
has to happen before the write, not after.

## 6. Human-gated actions (never automate)

- The author email (`paper/author-query-draft.md`) is **sent by Matthew only**.
- HIP 65426 b's headline uses another team's active-programme data — publication priority is **Matthew's decision** (M20 §5) and gates the paper fold-in of M20–M24.
- Never push/merge to main, never submit anywhere (journals, MPC) without explicit approval.

## 7. Where the conclusions live

| Artifact | What it holds |
|---|---|
| `M13/M14-RESULTS.md` | Historical extraction development and model comparison; M37 narrows the detection and independence wording |
| `M15-RESULTS.md` | eta Tel B null and pointwise circular sensitivity, conditional on fitter-stage transmission; M37 owns that scope correction |
| `M17-RESULTS.md` | Historical K-band tier; M29/M37 withdraw or narrow the beta Pic and observing-mode claims |
| `M20-RESULTS.md` | Census harvest: HIP 65426 b exomoon-regime limit, PDS 70 star, beta Pic b contamination, **the contrast wall**, correction log |
| `M23-RESULTS.md` | Roster closed: 1 confirmation, 1 contradiction, 4 limits, 1 contamination, 4 data-limited (§5); embargo calendar (§6) |
| `docs/target-queue.md` | **The living ledger**: every system's verdict + the HiRISE/M27 banner + archive traps + standing machinery |
| `docs/paper/draft.template.html` | The manuscript (generated, never hand-edited) + Figs 5–12 answering Hoy figure-for-figure |
| `M28-RESULTS.md` | The first audit; M37 establishes that its permutation and jackknife conclusions are conditional on the internal screen |
| `M29-RESULTS.md` | YSES 1 b's 2022 night reduced then **rejected** by a pre-committed screen; the CRLF defect; the contrast axis derived, twice corrected, and finally replaced by **S = contrast/theta^2** (§§6-8) |
| `M35-RESULTS.md` | Historical photometry/Gaia check; M37 and `data/m35-photometry-v2.json` supersede the sensitivity and astrometric wording |
| `M36-RESULTS.md` | Inconclusive historical target-aware attempt; M37 establishes that its paper-derived injection plan and search were not paper-blind and that it did not faithfully execute the preregistration |
| `M37-RESULTS.md` | Authoritative audit correction: complete-versus-screened RV evidence, corrected M35, M36 invalidation, claim scope, and downstream evidence bundle |
| `audits/REFERENCE-AUDIT.md` | Every citation checked against source PDFs: 14 wrong across 60+ sites |
| `audits/PROPERTY-AUDIT.md` | 268 object properties: 171 verified, 34 conflicting, 63 unsourced |

**Open front after M37:** review and commit a valid successor protocol before any new
paper-blind run; then close the raw-to-RV provenance/environment gap. Proper HiRISE reduction
and the other target-specific queues remain secondary until the central evidence boundary is
settled.
