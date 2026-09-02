# HANDOFF — exosat-rv

> ## M37 (2026-08-31) — READ THIS BEFORE THE OLDER BANNERS
>
> A parallel audit narrowed the central result and invalidated the claimed execution of M36.
> The authoritative record is [`M37-RESULTS.md`](milestones/M37-RESULTS.md).
>
> - The near-171-day signal is strong only on the 17 nights retained by the internal
>   across-order-spread screen. With all 18 nights, every BERV-adjusted global search is
>   compatible with noise. The old jackknife is a robustness test *within the screened set*.
> - The extraction was calibrated against the published RV series, and template-shift
>   injections begin after template construction. This is a paper-calibrated, conditional
>   recovery—not an independent end-to-end reproduction or end-to-end injection test.
> - M35's night/camera-aware photometric null survives at materially weaker sensitivity;
>   Gaia RUWE/NSS provide context, not proof of no perturbation.
> - M36 omitted registered fixed settings and had scoring/cache defects. Its “inconclusive”
>   interpretation is safe, but the historical JSON is not a valid preregistered execution.
>   Its injection plan also encodes the published orbit, and its search uses published epochs
>   and a hard-coded published-period window, so it was target-aware rather than paper-blind.
>   The audited runner is dry-run only: every non-dry invocation aborts before external
>   work or artifact creation. No replay was run.
> - `data/repro/` now freezes the small adopted RV/per-order tables and fingerprints the
>   remaining external inputs. Downstream statistics rerun offline, but raw-to-RV replay and
>   the historical environment remain unresolved.
>
> Older milestone banners below are preserved as history and are superseded where they
> conflict with M37. No manuscript is submission-ready on an “independent reproduction”
> claim. A successor protocol must be reviewed and committed before any new experiment.

> ## HISTORICAL M36 (2026-08-24) — invalidated as a preregistered execution by M37
>
> M34 §3's experiment — choose the extraction configuration by injection recovery alone,
> never consulting the published series — was pre-registered
> ([`M36-PREREGISTRATION.md`](milestones/M36-PREREGISTRATION.md), committed before the first
> run) and executed over 36 configurations in 40 minutes.
> **It did not answer the question, and the reason is a defect in my own protocol.** The gate
> constrained the recovery slope but never its uncertainty: slopes came back spanning −12.3 to
> +2.0 with errors of ±0.48 to ±6.12, and the three that "passed" did so on 0.97 ± 2.28,
> 1.13 ± 1.54 and 1.14 ± 0.92 — every 2σ interval containing zero, i.e. consistent with total
> signal destruction. The adopted configuration's own gates run at 99–101% ± 1%.
> The blind search was run anyway, as the protocol requires: the winner puts its best near-171 d
> peak at 174.9–182.0 d, ΔBIC +4.6 to +8.3, never rank 1 — but the fitted K values are
> **2,376–119,098 m/s** against a real signal of ~306 published / 380–470 fitted, so the series
> are noise and the search is fitting sampling, not sky.
> **This is not evidence against the M14 detection**; it is an experiment that failed to be
> sensitive. The likely cause is stated in [`M36-RESULTS.md`](milestones/M36-RESULTS.md) §6:
> the protocol excluded iteration-2 templates as paper-contaminated, and M14 found iteration 2
> is *the* decisive change — so removing the paper's influence also removed the ingredient that
> makes the extraction work. **M34 §3's question remains open**, and §7 sets out what a valid
> version needs: a paper-blind template-iteration rule, pre-registered separately. Not started.

> ## HISTORICAL M35 (2026-08-24) — photometry and astrometry corrected by M37
>
> `NEXT-DIRECTIONS.md` B1 and B2, the two items ranked ahead of any new science because a
> referee will ask for both, are done ([`M35-RESULTS.md`](milestones/M35-RESULTS.md)).
> **B1 — photometry.** The host shows **no periodicity at 171.454 d** in either ASAS-SN
> filter era: power 0.0007–0.0017, permutation *p* = 0.35–0.55 over 500 draws, on baselines
> of 1609 d (V) and 2439 d (g). Injection recovery sets the limit at **5 mmag**, against the
> star's own rotational amplitude of 57 mmag. Crucially the null is not a power failure —
> the same search recovers the star's catalogued 1.717 d rotation (VSX: ASAS J060919-3549.5,
> TTS/ROT) as its |1−f| daily alias at 2.379 d, *p* = 0.000, matching to 0.0028 c/d. **The
> satellite has no photometric activity explanation.** A first pass searching to 2000 d
> against a 1609 d baseline reproduced the methods note's own §5.3 defect and was redone with
> the grid capped at half the baseline; the 171 d numbers were unaffected.
> **B2 — astrometry.** Gaia DR3 for all 31 roster positions in one batched query: CD-35 2722
> is RUWE **1.023**, excess noise 0.099 mas, **NSS = 0**; η Tel B's host RUWE 1.013. **No
> target on the roster carries a non-single-star solution.** Six exceed RUWE 1.4 and all six
> are very bright stars where the solution degrades — not read as companions.
> **Neither result is in the manuscript yet.** Both are ready to cite and that is an
> editorial call, not an open question.

> ## M31 (2026-08-14) — the fibre chain transfers: HIP 65426's three HiRISE nights extracted, and the planet is below the background
>
> All **27/27 staged frames** of the three public HiRISE nights reduce through the
> M29-validated util_ path with **zero parameter changes** ([`M31-RESULTS.md`](milestones/M31-RESULTS.md)):
> 21 non-empty orders per frame, FPET wavelength solutions, ranges matching the bpbhi
> reference to <1 nm. On-sky proof reproduced on a second target: **h65hi2's deep frames
> share tellurics with its host at 11.8σ at exactly 0 km/s** (benchmark 9.8σ); h65hi1/h65hi3
> verified by contents with weaker telluric CCFs (~5σ/2.9σ), controls 9.6–23.3σ. Two new
> HiRISE-night facts: a third frame class exists (**trailing sky/offset frames share the
> host's DIT** — class by measured rate, not DIT), and raw-percentile probes cannot see a
> faint host trace that extracts at S/N 10. The sourced photometry closes a door:
> **ΔH2 = 11.14 (Chauvin+2017 Table F.1, fetched) puts HIP 65426 b 40–130× below the fibre
> background in every deep frame — CCF ceiling 2–3σ; this corpus is a telluric/sky
> reference + methods asset, not a companion dataset.** The exomoon lever stays the K2192
> slit series + Matthew's priority call. Disk: managed on the data volume (floor 4.0 GB,
> end 5.4 GB free); 90 calib raw deleted post-verification (logged); science raw + masters
> kept for re-extraction; no other thread's data touched. Fetches 90/90, zero failures.

> ## M30 (2026-08-14) — the outside sweep's "new public epochs": none were new
>
> `DISCOVERY/run3-prospectus.md` avenue #1 claimed three newly-public CRIRES+ blocks.
> Verified per-night against TAP + raw headers ([`M30-RESULTS.md`](milestones/M30-RESULTS.md)):
> **(a)** HIP 65426's "90 exposures" are M22's own five-night K2192 series (134 frames,
> consumed); **(b)** CD-35's "300 exposures Oct 2024" are the M4368 thermal-IR deep pair,
> shelved since M26; **(c)** the beta Pic series is still embargoed (truth: 6 nights /
> 1158 frames rolling 2026-09-25 → 10-01; its "K2166" ledger label is only a filter hint —
> header probe at release). What M30 *did* find: **three public HiRISE H1567 nights of
> HIP 65426** (27 frames, new to the ledger; science staged as `raw_m30/h65hi*`, calib
> lists banked), the public 2024-09 beta Pic deep pair header-classified **M4368 on
> `bet Pic b`** (shelved class), and the CD-35 embargoed-campaign pre-check: **standalone
> R² = 0.92 at 171.454 d (never fit the new epochs alone), joint with the existing series
> R² = 0.05 — the Dec 2026 releases decide the satellite jointly or not at all.**
> Meanwhile a concurrent session completed **and on-sky-validated** the first HiRISE
> extraction (bpbhi 39/39; host-telluric CCF 9.8σ at 0 km/s, M29 §19+) — M27 has begun
> in that thread; M31 here should extract the staged HIP 65426 nights through that
> path, not duplicate the beta Pic work. No reductions were run in M30; staging stayed
> science-only (27/27 frames, 1.3 GB, size-validated) because the data volume hit 100%.

> ## ⚠ M29 (2026-08-13) — READ BEFORE TRUSTING ANY NUMBER IN THIS REPO
>
> A day spent checking old work against its actual sources found **14 wrong citations
> across 60+ sites** and **34 conflicting object properties**, and **not one was found by
> producing a new result**. Before using any externally-sourced number here, check
> [`audits/REFERENCE-AUDIT.md`](audits/REFERENCE-AUDIT.md) and
> [`audits/PROPERTY-AUDIT.md`](audits/PROPERTY-AUDIT.md). The traps are
> [`LESSONS.md`](LESSONS.md) §5b.
>
> Three things that will bite immediately:
> - **All 39 shell scripts were CRLF and unrunnable under WSL** (a "completed" reduction
>   reported exit 0 and did nothing). Fixed by `.gitattributes`. Diagnose with
>   `file script.sh` **from inside WSL** — git-bash will tell you they are LF and be wrong.
> - **The "contrast wall" is superseded.** Its 2000×/5000×/30 000× figures were never
>   derived, and the axis itself was wrong. Outcomes are ordered by **S = contrast/θ²**
>   (M29 §§6–8) — and that is consistent with the data, not yet tested by it.
> - **YSES 1 b is a 2-night series.** The 2022 night reduces once the frame count is even,
>   then fails a pre-committed order screen. The "4-night/290-d prize" never existed.
>
> ## ⚠ START AT [`LESSONS.md`](LESSONS.md) — the consolidated trap catalog + map of all conclusions
> Then [`docs/target-queue.md`](target-queue.md) for the roster and the
> **HiRISE revelation (M27 pending)**: the entire "staring" tier is fiber-fed
> HiRISE data, three verdicts were corrected, and six public starlight-suppressed
> beta Pic b nights are waiting on a fiber-appropriate reduction.

> ## HISTORICAL M12–M23 CONTEXT — preserve for provenance; use M37 for current claims
>
> The banners in this block record what was believed at those milestones. In particular,
> M14's “raw-data reproduction,” M15's “end-to-end” injection wording, and M12's active-plan
> language are superseded or narrowed by M37 and must not be used as the current verdict.
>
> **M23–M24 (2026-08-12, THE PLAN IS WALKED):** HD 1160 B — first multi-epoch series
> via the new staring branch, quality-limited (725 m/s / 41 d; one ±37 m/s night
> shows the ceiling), no claim. AF Lep b (68% transmission — dilution) and 51 Eri b
> (3 of 11 orders) land on the far side of the contrast wall, as predicted.
> CT Cha B: screened series leaves a 3.3σ variability candidate, undecidable at
> n=3. **PDS 70's nine-night upgrade FAILED its injection gate (−62%) — a
> fake-quiet series caught by machinery; the validated six-night state restored
> and reproduced exactly.** Final roster in M23 §5: eleven systems — one
> confirmation, one contradiction, four limits, one contamination case, four
> data-limited. Next levers are all dated (embargoes, M23 §6) or decisions
> (HIP 65426 b priority; the proposal case, now fully measured).
>
> **M20–M22 (2026-08-12):** the coordinate census's three host-name campaigns
> resolved. **HIP 65426 b**: 5 clean planet nights / 422 d at 131 m/s → companions
> ≥ ~0.4 M_Jup (~115 M⊕) excluded at P ≤ 100 d (90%), gates 98–101% — the
> exomoon-regime constraint (priority caveat: another team's active-programme data;
> M20 §5). **PDS 70**: the star, not the planet — flat at 130 m/s, ~3 M_Jup stellar
> limit. **beta Pic b**: km/s starlight contamination (Br-γ in the halo of a
> naked-eye star at 0.55″), diagnosed and halved; v3 (masked orders) pending. The
> **contrast wall is measured** (clean at 0.8″/2000×, flooded at 0.55″/5000×; M20
> §6). Correction log in M20 §5: "first RVs of beta Pic b" was wrong (2024 CRIRES+
> paper); all firsts now hedged. Two permanent rules: never single-night templates;
> product headers are the only band truth (six filter_path lies).
>
> **M17 (2026-08-11):** K-band spot-checks on the tier-2 targets — first-ever RVs of
> **beta Pic b** (162 m/s within-night on the planet, injection 100±0% in all 18
> K2166 orders → a campaign could reach ~100 M⊕ exomoons), **AB Pic b** (~120–190
> m/s over 2 nights, gates pass), and **CT Cha B** (usable only with per-order
> screening; disk emission suspected). viper's K-band branch is 1-indexed
> (`oset 1:19` for K2166); filter_path is now at five documented lies. The paper
> draft ([docs/paper/](paper/)) carries the CD-35 + eta Tel story with
> figures/tables; beta Pic b's raw K-nights (night-to-night repeatability of a
> planet RV) are the next queue item.
>
> **HISTORICAL M15 (2026-08-11, COMPLETE):** the validated recipe transferred to **eta Tel B**
> — which shares CD-35's exact H1567 setting — and produced the **first RV
> constraint ever placed on the object**: 127–129 m/s per epoch (beats the 163
> forecast), r(RV,BERV) ≈ 0, injection gates at 94–101% ±1–3 with 12–26 m/s
> residuals (4× cleaner than CD-35, both routes), **no credible detection** on
> either the archive or the full per-nodding route (all 20 epochs reduced from raw,
> zero failures), and an injection-calibrated 90% limit of **msini ≳ 0.5–1.2 M_Jup
> across P = 20–300 d** — sub-Jupiter over most of the range, 3× deeper than
> forecast. The machinery detects its own end-to-end K=300 injection at rank 1, so
> the null is meaningful. A weak <20 d comb moves periods between routes and
> combines — alias behavior, not claimed. The phase–BERV geometry check (ten
> minutes) confirmed 150–300 d is fully BERV-clean *before* any compute was spent —
> permanent practice from here on. Writeup-ready: "First RV constraints on
> eta Tel B."
>
> **HISTORICAL M14 (2026-08-11, CENTRAL CLAIM SUPERSEDED BY M37):** (1) **The second-satellite flip survives nested
> sampling**: dynesty on the Nature table gives ΔlogZ(2sat−1sat) between −0.8 and
> −6.6 across three model pairings × three prior styles × two seeds — never positive —
> against the paper's claimed +2.622. The M13 proxy (−0.51) was conservative.
> (2) **The drift floor is closed and the conclusion reproduces from raw data.**
> `-oversampling 2` (147→133) + a **second template iteration** (→ **85 m/s** mean,
> archive route; guard passes 105% ± 4%, every order 92–112%, o18 healed) + the
> paper's per-nodding-binned recipe on all 18 nights reduced from raw (→ **90 raw /
> 70–76 centered-robust**). The **blind period search finds ~169–171 d at rank 1 in
> every combine, ΔBIC +40 alone and +25 to +28 WITH a BERV nuisance covariate**, the
> fatal 60604 epoch excluded by a fully internal 3×-spread screen. Attribution is
> clean: at template iteration 1 the detection still collapses under BERV even
> per-nodding — iteration 2 is the decisive change. Success criterion (rms_pub ≤ 90
> AND BERV-robust blind detection) **met on both routes**. Amplitude runs 20–40% high
> (confound-limited hint, M13 §4's rules still apply). All of it injection-validated,
> including per-frame arms and an amplitude-matched K≈306 arm (9/11 orders 98–105%,
> rms 5–29 m/s).
>
> **M13 (2026-08-11):** the paper's **eleven orders are identified** —
> `oset 4,7,8,9,10,12,13,14,17,18,19`, confirmed three ways. The best config
> (`-kapsig 3` on that set, robust order combine) reaches **147–218 m/s against the
> published Nature RVs** (from 382 at M12 best), passes injection-recovery at
> **100% ± 5%**, and recovers **K = 304 ± 69 m/s against the published 306.0** at the
> published period — the amplitude reproduces from raw data. Re-running the inference on
> the **Nature** table: the 87.35 d period choice reproduces, but the second satellite's
> evidence **flips to −0.51** (paper: +2.62) under the same BIC/2 proxy that still
> reproduces the v1 comparison. `exosat-rv orbits` now defaults to the Nature table
> (`--version v1` for the superseded one). The scoring truth for any extraction change is
> [`data/published/hoy2026_nature_table2_rvs.csv`](../data/published/hoy2026_nature_table2_rvs.csv)
> via [`scripts/injection/vs_published.py`](../scripts/injection/vs_published.py).
>
> ## Historical M12 technical ground (claim strength superseded by M37)
>
> 1. **The paper was published in *Nature* on 22 July 2026 and M0–M11 all used the
>    pre-peer-review arXiv v1**, which its own comments field asks readers not to draw
>    conclusions from. The precision target moved **31.44 → 57.68 m/s**, the RV table
>    20 → 23 epochs with **timestamps corrected by 0.87 d**, the period 169.45 → 171.11 d,
>    Msini 0.743 → 0.918 M_Jup, and the second satellite's evidence
>    **delta-logZ 6.64 → 2.62**. `config.py` is pinned to superseded values throughout and
>    M6 fitted the superseded table.
> 2. **`viper` has been modelling a gas cell that was not in the beam** since M2 — `-nocell`
>    was never set, on data with `INS1 OPTI1 ID = FREE`. And **the template is a raw
>    observation with tellurics in it**, where the published recipe requires a telluric-free
>    one. Fixing both takes the paper's own error statistic 763 → 480 m/s and removes an
>    **RV–BERV correlation the authors explicitly report they do not have**.
> 3. **The gap is 8.3x, not 25x**, and it is now decomposed: of the baseline 823 m/s,
>    **522 m/s was BERV-correlated and is now 150 m/s**, while **~620 m/s of non-BERV
>    per-order systematic is untouched by any of it.** That residual is the real problem.
> 4. **Both fixes are adopted, and the GJ 229 B control has been overturned on evidence.**
>    An injection-recovery test on CD-35 2722 B itself (M12 §8) returns **95% ± 7%** of an
>    injected signal under the corrected model, where the control predicted **46%** — a 7σ
>    disagreement on the object that matters. Per-order recovery is **81–112%** corrected
>    against **−4% to 493%** at baseline. **Use injection recovery, not GJ 229 B, to judge
>    any forward-model change** — the control's signal is ~70x the target's, so it screens
>    the wrong regime. Build on `scratchpad/inject_run.sh`; and note M12 §8.1 — shift the
>    *template*, never the observation, or 92% of the injection vanishes into the telluric
>    anchor.
> 5. Two of M11's open suspects are closed for free: the ADP→cr2res conversion is **correct**
>    (checked against ESO's own `CWLEN` header values), and `-tpl_wave tell` is a **no-op**
>    for RV runs.

## Current state — authoritative at M37

[`M37-RESULTS.md`](milestones/M37-RESULTS.md) is the claim-bearing record:

- On the internally screened 17-night CD-35 series, the near-171-day peak is the strongest
  searched period and survives a linear BERV covariate under all three order-combination
  rules. Its `p_global < 0.01` values are nominal and conditional on the screen and on
  exchangeable fitted residuals; the calibration does not charge for choosing the screen.
- On all 18 nights, every BERV-adjusted global search is compatible with noise. The excluded
  night is therefore load-bearing for the claimed recovery, even though leave-one-out checks
  show that no retained night alone carries the screened result.
- The extraction was tuned with the paper visible and calibrated against published RVs.
  Template-shift injections test fitter-stage transmission only. The result is a separately
  implemented, paper-calibrated conditional recovery, not an independent raw-to-RV or
  end-to-end reproduction.
- The corrected host photometry shows no coherent modulation at the RV period at 12–13 mmag
  semiamplitude sensitivity, subject to its stated exchangeability and observed-noise
  assumptions. Gaia RUWE/NSS are context only, not an exclusion of activity or perturbation.
- The smaller-companion evidence is not reproduced under this project's tested models and
  priors. This is not a sampler-independent contradiction.
- `data/repro/` makes the adopted small RV/per-order tables and downstream audit reproducible.
  It does not bundle the raw exposures, fitted templates, or a contemporaneous historical
  environment, so raw-to-RV replay remains unresolved.

No current manuscript is submission-ready on an “independent reproduction” claim.

## Automatic continuation boundary

[`M38-PROTOCOL-DRAFT.md`](milestones/M38-PROTOCOL-DRAFT.md) is **DRAFT / NOT
PREREGISTERED / DO NOT RUN**. Automatic work may continue only on generic code, simulations,
declared controls, provenance machinery, and independent review needed to close M38's
blocking register. In particular, it may:

1. implement and test a stellar-only pre-template injection operator on synthetic spectra and
   declared controls;
2. implement control-only convergence, order-attrition, uncertainty, detection-completeness,
   and full adaptive-pipeline calibration experiments;
3. refactor a target-free period-search/null-calibration library and harden manifests,
   deny-list checks, stage barriers, and reconstructable output schemas; and
4. draft a replacement preregistration for independent review after every blocking choice is
   justified and frozen.

It must not open CD-35 target spectra, run a target reduction or injection, inspect a new
target RV/period diagnostic, or treat the M38 draft as execution authority. Any such need is a
stop condition pending a reviewed, committed replacement preregistration and the required
role-separated target mount.

The generic implementation completed under this boundary is recorded in
[`M38-CONTROL-DEVELOPMENT.md`](milestones/M38-CONTROL-DEVELOPMENT.md). It provides synthetic
injection/convergence, search/calibration, recovery-selection, manifest-chain, and application
firewall primitives, plus a replayable toy full-template chain, exact control/decision freeze
schemas, a signed stage ledger, and a dedicated target-free runtime probe. The runtime build and
launch evidence is in
[`M38-CONTROL-RUNTIME-EVIDENCE.md`](milestones/M38-CONTROL-RUNTIME-EVIDENCE.md); it is an
identity/launch-restriction probe, not the frozen scientific image.

The current executable/test/container snapshot is local commit `79170df`; all 13 M38 suites
pass 331 target-free tests with warnings fatal, and the exact scope is recorded in
[`m38-verification-2026-09-02.json`](evidence/m38-verification-2026-09-02.json). This is an
engineering checkpoint only; the current historical repository-wide tests were not rerun
because some intentionally open target-derived products outside the automatic boundary.

The control search in
[`M38-CONTROL-CANDIDATES.md`](milestones/M38-CONTROL-CANDIDATES.md) has **not** selected a
suite and has not identified a sufficient second same-setting positive control with independent
truth. None of the 18 blocking decisions is thereby resolved. The next automatic work remains
simulations, declared observational controls, external verifier/storage integration, and
replacement-preregistration drafting only. Human or independently controlled gates still must
name the roles and keys, choose and sign the control truths and scientific settings, freeze the
raw target manifest and production image, and approve a later role-separated target mount.

## Reading order

Start with [`M37-RESULTS.md`](milestones/M37-RESULTS.md) for the current scientific verdict and
[`M38-PROTOCOL-DRAFT.md`](milestones/M38-PROTOCOL-DRAFT.md) for the control-only successor
boundary. The numbered archive below is historical context, not an active plan.

0. [`papers/`](../papers/) — the source and its citation chain, as PDFs and extracted text.
   **Read `papers/text/hoy2026_v1.txt` in full before forming any view.** It did not exist
   until M7; six milestones ran on two papers and an appendix.
1. [`SPEC.md`](SPEC.md) — what is being tested and why it is worth testing.
2. [`M0-RESULTS.md`](milestones/M0-RESULTS.md) — what the archive contains. **Its arithmetic is corrected
   by M1 and M2; do not quote it alone.**
3. [`M1-RESULTS.md`](milestones/M1-RESULTS.md) — the source read properly, and two retractions of M0.
4. [`M2-RESULTS.md`](milestones/M2-RESULTS.md) — RV extraction, and why it falls short. Carries two
   corrections of its own.
5. [`M3-RESULTS.md`](milestones/M3-RESULTS.md) — the positive control that makes M2's null readable.
6. [`M6-RESULTS.md`](milestones/M6-RESULTS.md) — the historical reproduction claim, superseded
   and narrowed by M37. Do not quote it as the current verdict.
7. [`M4-RESULTS.md`](milestones/M4-RESULTS.md) — the alias structure of the second signal.
8. [`M5-RESULTS.md`](milestones/M5-RESULTS.md) — analogue targets, and the control's provenance.
8b. [`M7-RESULTS.md`](milestones/M7-RESULTS.md) — the literature this method came from, three
    attribution corrections, and the generalisation framework.
8c. [`M8-RESULTS.md`](milestones/M8-RESULTS.md) — young close-in giants, and why satellite survival
    and cross-correlation observability trade as an inverse cube.
8d. [`M9-RESULTS.md`](milestones/M9-RESULTS.md) — **order screening falsified, and the reweighting that
    fooled the target and was caught by the control.** Read §5 before touching order weights.
8e. [`M10-RESULTS.md`](milestones/M10-RESULTS.md) — the astrometric route, inventoried. Read §5: its
    kill-check is open.
8f. [`M11-RESULTS.md`](milestones/M11-RESULTS.md) — **the template rebuilt the published way, and why
    it suppresses the signal.** Third change running that improved the target and failed
    the control. **Read M12 §5.3 alongside it: M11 changed three things at once and ran
    with the cell error present, so its verdict is conditional.**
8g. [`M12-RESULTS.md`](milestones/M12-RESULTS.md) — historical technical ground: the published
    Nature version, the gas cell that was never switched off, the telluric-contaminated
    template, and the RV–BERV correlation. Use M37 for claim strength.
9. [`BUILD-PLAN.md`](BUILD-PLAN.md) — stack, architecture, milestones.
10. [`DATA-SOURCES.md`](DATA-SOURCES.md) — endpoints, and the traps in each.
11. [`docs/viper-runbook.md`](viper-runbook.md) — **rebuild the RV pipeline from
    scratch.** Nothing in it is documented upstream for archive data.

The rest of this file is the expensive part: claims that turned out false, approaches
measured and rejected, and silent failures that cost data. The code is not the expensive
part.

---

## 1. Claims published here and later found false

### "The paper's Hill radius of 1.07 au cannot be true" (M0) — **FALSE, retracted in M1**

M0 published a disproof of a value in a peer-reviewed paper. The disproof was wrong twice:

1. **Wrong quantity.** 1.07 au is a Domingos et al. (2006) satellite *stability limit*, not
   a Hill radius. The paper computes the Hill radius separately and notes it varies over the
   companion's orbit.
2. **Wrong orbit.** M0 used the projected separation (2.8" = 62.6 au) as a circular
   semi-major axis. The companion has **e > 0.9** and P ~ 5000 yr, so a ~ 222 au, and the
   Domingos eccentricity term collapses the stable zone by more than 10x.

Recomputed with the paper's own parameters, 1.07 au falls out at e_host ~ 0.93–0.94 —
inside the published ">0.9". **The paper was right.** Full working in
[`M1-RESULTS.md`](milestones/M1-RESULTS.md) §1.1.

**Root cause, and the lesson that outlives the specific error:** M0 reasoned from an AI
summary of a source it had not read, all the way to a public claim. It *had* tagged the
value unverified — and tagging it did not stop the reasoning. **An unverified value must
not be an input to any conclusion, not merely absent from tests.**

### "The paper's evidence for a second satellite is delta-log-Z = 2.6" (M0) — **FALSE, retracted in M1**

2.6 compares the **88-day model against the 115-day model** — two candidate *periods* for
the second signal. The evidence that a second satellite exists at all is **delta-log-Z =
6.9**, against an eccentric one-satellite alternative. M0 understated the existence
evidence and overstated the period certainty. See M1 §1.3.

### "The detection is neither confirmed nor contradicted" as a statement about the paper (M3) — **TOO BROAD, corrected in M6**

M3 established that the *radial velocities* could not be re-derived from the archive at the
required precision. True, and it still stands. But it was written as the project's verdict on
the **paper's conclusion**, which M3 never tested.

Reproducing an analysis has two independent halves — obtaining the same measurements, and
drawing the same inference from them. Failing the first says nothing about the second.

**The preprint publishes its full RV table** (Table 2, appendix A). Feeding it to an
independent fitter reproduces the conclusion: the ~169 d signal above the 0.1% FAP level, an
~88 d second satellite preferred over 14/70/115 d, K₂ agreeing to 0.1%, and both model
comparisons in the same direction as the paper's. See [`M6-RESULTS.md`](milestones/M6-RESULTS.md).

**General lesson: before concluding a result cannot be reproduced, check whether the authors
published the intermediate data.** Many papers do, in an appendix nobody reads. Three
milestones were spent re-deriving numbers that were printed on page 23.

### "The GQ Lup B null is Köhler et al. 2024, the first dedicated RV exosatellite search" (SPEC, M5) — **FALSE on both counts, corrected in M7**

Found by extracting Hoy et al.'s reference list — something no earlier milestone did.

1. **Wrong author.** arXiv:2408.10299 is **Horstman et al. 2024**. Köhler is not an author
   on it. SPEC had already corrected the *instrument* (Keck/KPIC, not viper/CRIRES+) and
   still kept the wrong name, then propagated it to M5-RESULTS.
2. **Wrong priority.** It is not the first. **Ruffio et al. 2023** (HR 7672 B,
   arXiv:2301.04206) and **Vanderburg & Rodriguez 2021** (HR 8799, arXiv:2110.14650)
   precede it, and **Vanderburg, Rappaport & Mayo 2018** (arXiv:1805.01903) proposed the
   method. **Three published nulls preceded Hoy et al.'s detection**, not one.

**Root cause:** the project cited a paper by its arXiv number without opening it, twice,
and corrected the detail that was challenged rather than re-deriving the claim. The
reference list of the source paper was never extracted in six milestones.

**Rule: when a citation is found to be wrong in one respect, re-check every other claim
attached to it.** A partial correction is how the wrong author survived M5.

### "The individual nodding frames are the lever that closes the precision gap" (HANDOFF, runbook) — **WRONG BY 2 ORDERS OF MAGNITUDE, corrected in M9**

HANDOFF §next-actions and `docs/viper-runbook.md` §7 both put re-extracting the nodding
frames first, on the grounds that it is "the only remaining difference the authors
themselves name". True — and the authors also **quantify** it, in their own Fig. 4:
**31.44 m/s vs 34.49 m/s, a ~10% gain.** Against a factor of 25 it cannot be the answer, and
nothing in the project had checked the size of a lever before ranking it first.

M9 then measured the other cheap lever, order screening: **6%** (823 → 776 m/s).

**Rule: before ranking a fix, find the number the source attaches to it.** Both of these
were quantified in the paper we are reproducing.

### "Weighting orders by their measured scatter improves the RVs" (M9, briefly) — **FALSE, caught by the control before publication**

Empirical weighting (1/rms_order²) gives **514 m/s on CD-35 2722 B, the best number M9
produced and a 1.6x gain on viper's own output.** It also drops the GJ 229 B control from
Δχ² = 63.8 to **5.8**, and the recovered amplitude from 6165 to 1825 m/s.

For a target with a real signal, an order's scatter *is* the signal, so inverse-scatter
weighting downweights exactly the orders carrying it. On a target with no detected signal
the pathology is invisible.

**This is the case HANDOFF's control rule was written for, and it is the first time the rule
has actually caught something.** Without GJ 229 B the screen would have been adopted and
every subsequent null would have been deeper and more wrong. Pinned by
`test_empirical_weighting_looks_best_on_target_and_destroys_the_control`.

### "M2's co-added template failed because it skipped RV alignment" (M9 §7) — **FALSE, disproved in M11 by reading the source**

M9 named this the leading suspect: the co-added template made things worse (823 → 1638 m/s),
which is the signature of co-adding without aligning spectra in velocity first.

**viper does align.** `viper.py` line 624 divides by `(1 + par.rv/c)` before co-adding, and
line 630 applies exactly Köhler et al.'s eq. 14 weighting, `w = T_atm/ε²`. The published
recipe is implemented faithfully.

**Reading the code cost minutes; testing the hypothesis cost an afternoon.** When a suspicion
is about what a program does, read the program.

### "Rebuilding the template per the published recipe will close the gap" (M9 §7) — **FALSE, and it suppresses signal, M11**

Two template iterations with `-tpl_wave tell`, exactly as Hoy et al. describe, takes
CD-35 2722 B from 776 to 620 m/s — and collapses the GJ 229 B control from Δχ² 76.5 to 23.7,
with recovered amplitude falling from 5948 to **2452 m/s, 41% of correct, after a single
iteration**.

**Self-templating absorbs the signal**: the template is co-added from the target's own
spectra aligned by RVs measured against a template that already contains the signal, so the
residual is baked in and later velocities are partly the star measured against itself.
Köhler et al. §2.2 flag the hazard for targets with real Doppler shifts; their prescribed
workaround is what viper implements and was not sufficient at our precision.

**Do not iterate a self-built template on a target whose signal you are trying to measure,
without verifying amplitude recovery on a known signal.** Pinned by
`test_self_templating_suppresses_a_known_signal`.

## 2. Inherited claims that do not survive checking

### Table 1's log-evidence difference does not match the quoted value — minor, real

Table 1 gives logZ = −122.654 ± 0.952 and −129.295 ± 0.920, differing by **6.641**, while
the text quotes **6.9**. Both are recorded in `config.py` and pinned by
`test_table1_logz_difference_does_not_match_the_quoted_delta`. Small, and noted rather than
made much of — unlike §1, this one was checked against the actual PDF.

## 3. Approaches measured and rejected

| Approach | Why rejected |
|---|---|
| Working from a source paper without archiving it or its references | Six milestones ran on the Hoy PDF read once and discarded, plus two hand-picked citations. The reference list named the framework paper (Lazzoni+2022), the method's proposal (Vanderburg+2018) and two unnoticed prior nulls. `papers/` and `scripts/fetch_paper.py` now exist; **extract the reference list first.** |
| Reading a null result on the close-in case as "hot Jupiter moons are impossible" | The naive tidal argument (all stable orbits inside corotation) assumes a *synchronised* planet. Young planets are not synchronised, and tau_spin-down goes as a^6 — the answer flips over a factor of 3 in orbital distance. See [`M8-RESULTS.md`](milestones/M8-RESULTS.md) §2. |
| Defaulting a host's density to Jupiter's when computing a Roche limit | A 37 M_Jup object in 1.2 R_Jup is ~27 g/cm^3, not 1.3. The wrong default returns 3.1 R_host against the paper's 8.4 — a plausible-looking number, no error raised. Densities are now computed from mass and radius and pinned by a test. |
| Weighting viper's per-order RVs by inverse **formal** variance | Not merely useless but **actively harmful**: 2620 m/s against 823 for a plain mean. Order 8 has the largest scatter (4130 m/s) and the smallest formal error (101 m/s), so it dominates. M2 knew the errors were untrustworthy; M9 measured the cost of using them anyway. |
| Applying the paper's telluric-order rule to ESO's combined product | Keeping only orders where viper constrains the telluric abundance (12/14/15/16) makes the target **worse** (1142 vs 823 m/s) and weakens the control (63.8 → 46.7). Either our `atm0` errors do not mean what they appear to, or the rule needs the per-nodding data. |
| Masking per-order RVs on the RV value alone | An order counts only if its RV *and* its error are finite and positive — what viper itself does. Masking on RV alone shifts the plain mean from 823 to 878 m/s: it looks like rounding and is a silent failure to reproduce M2. |
| Populating `config.py` from AI summaries of the paper body | Produced three wrong values and one false published claim (§1). The `[SUMM]` tier is now **eliminated**, not merely flagged. |
| Extracting the PDF via WebFetch, then via poppler under WSL | WebFetch returned only compressed streams; poppler is not installed in WSL and would need sudo. **`pypdf` in the project venv did it in one call** — 27 pages, 55,679 chars. Try the pure-Python route first. |
| Framing M4 as "is the 87-day signal a harmonic of the 169-day orbit?" | The paper asks exactly this, fits the eccentric one-satellite model (e = 0.29), and rejects it by delta-log-Z = 6.9. Re-scoped to the **alias structure**, which the paper states openly is unresolved. See M1 §3-4. |
| Assuming ESO's reduced products are what the paper used | They are not. The authors kept **individual nodding frames** rather than the combined spectrum, buying 31.44 m/s against 34.49 m/s. Working from archived products costs ~10% precision by construction. M1 §2. |
| `CONTAINS(POINT(...), CIRCLE(...))` on ESO `dbo.raw` | Hard-fails with a SQL-Server geography error — the table holds rows whose coordinates do not validate. A plain ra/dec box works and is faster. |
| `astroquery.eso` for archive access | Wraps the web form; awkward for the `dbo.raw` / `ivoa.ObsCore` comparison that is the whole of M0. `pyvo` gives direct ADQL against both. |
| Reducing all 20 nights from raw with esorex/cr2res | M0 measured that 17 are already reduced by ESO. Building cr2res to recover 3 nights is a late optimisation, not a prerequisite. |
| Using `EMPEROR` (the paper's sampler) for M3 | Would make the reproduction circular. `radvel` is used instead so that agreement means something. |
| Using `sy_hmag` from the NASA Exoplanet Archive as the companion brightness cut | It is the **system** magnitude, dominated by the primary. Useless for a companion flux cut. |
| Treating "could not re-derive the measurements" as "could not reproduce the result" | They are separate claims. M2-M3 spent three milestones on the extraction while the paper's own RV table sat in appendix A. **Check for published intermediate data first.** |
| Reading a null result without a positive control | M2's null was equally consistent with an imprecise pipeline and a broken one. Only the GJ 229 B control (M3) distinguished them. **Never report a null from this pipeline without re-running the control.** |
| Using a spectrally mismatched template | The GJ 229 B control returns reduced chi2 = 0.53 (nothing) with an L-dwarf template on a T dwarf, and 5.36 with a matched one. Template match is the difference between working and broken, not a refinement. |
| Trusting viper's formal RV errors | Per-order rms exceeds the formal error by factors of 2-42. Measure precision from within-night repeats instead. |
| Believing `-createtpl` or `-telluric add` would fix M2's precision | Both were tried. The co-added template changed nothing. `-telluric add` is a **no-op on CRIRES** — `config_viper.ini`'s `[CRIRES]` section already sets it, along with `oset = 7:17` and `kapsig = 15 6`. **Read `config_viper.ini` before claiming any viper setting is off.** |
| Adding `-tellshift` for cell-free data | It frees the telluric wavelengths, which for cell-free CRIRES+ *are* the wavelength reference and must stay fixed (Köhler+2025 §5.4). It tripled the scatter. |
| Treating M6 as an independent test of the detection | Fitting the authors' published RVs tests their **inference**, not their **measurement**. A systematic in their extraction would reproduce perfectly. M6 rules out "they fit the model wrong"; it cannot rule out "the velocities are wrong". |
| Trusting the NASA Exoplanet Archive alone for the M5 target list | It caps companion mass at 30 M_Jup and therefore **does not contain CD-35 2722 B**. M5 was rebuilt archive-first, with CD-35 2722 B's rediscovery as the control. |
| Resolving companions by SIMBAD **name** | Identifiers are unforgiving about spacing: `CD-35  2722B` resolves, `CD-35 2722 B` and `BET PIC B` do not. Normalise and match against *all* identifiers instead. |
| Resolving companions by **position alone** | A cone search finds the system, not the component. It resolved `BET PIC B` to beta Pic **c** and `PZ TEL B` to the G9IV primary. Two stages are needed: cone for the system, identifier match for the component. |
| Ranking M5 targets by **frame count** | beta Pic b has 753 frames — on 6 nights. AB Pic B's 64 frames span 3 days. An RV orbit needs epochs spread over time; rank by nights and baseline. |
| Filtering companions by SIMBAD `otype` alone | `tau Boo B` (M3V) and `HD 149274B` (M5) are typed `*` and pass as "borderline". Spectral type is the more specific statement and must override. |

## 4. Silent failures that cost data

### `pathlib.Path.write_text()` truncated `README.md` to zero bytes

On Windows, `write_text()` defaults to the cp1252 locale encoding. Writing a string
containing `→` raised `UnicodeEncodeError` — **but only after opening the file in write
mode**, which had already truncated it. The exception looked like "nothing happened"; the
file was in fact destroyed. A follow-up read-modify-write then read the now-empty file,
found nothing to replace, and wrote the emptiness back.

**Rule: always pass `encoding="utf-8"` explicitly to both `read_text` and `write_text` on
this platform.** The read side is worse than the write side — cp1252 is a single-byte codec
that decodes almost any byte without raising, so reading a UTF-8 file with it produces
silent mojibake rather than an error.

Damage was limited to `README.md`, rewritten from source. Nothing else round-tripped
through Python text I/O.

### A hand-written night count that disagreed with the pipeline

An ad-hoc scoping script counted **18** public reduced nights; the pipeline reports **17**
in H band. The pipeline is right — the extra night (2024-01-03) was taken in the **K**
setting. The ad-hoc script had no band filter. Cross-check band before quoting an epoch
count.

## 5. Things that look like problems and are not

- **`access_estsize` is 0** for every CRIRES+ product in ObsCore. The column is unpopulated,
  not the products empty. Download size is unknown until M1 fetches one.
- **`sorted(...)[0]` on a settings set** looks arbitrary but is deliberate: reduced products
  carry no setting, so they inherit the night's raw settings, and a stable pick is needed.
  Now written as `min(...)`.
- **`nan pc` distances** were SIMBAD returning NaN rather than NULL for a missing parallax,
  which a bare truthiness check lets through as though it were a measurement. Now filtered
  with `math.isfinite`.
- **`archive.eso.org` timing out** is not a code fault. It served M0's queries, then went
  unreachable for all of M1 (connect timeout, HTTP 000) while `www.eso.org` returned 302 and
  other TAP services 200. Retry before debugging.
- **Two extra public nights (2023-01-04, 2023-02-01)** exist that the paper does not use.
  They are J/YJ band, not H, so they are not a discrepancy — see M0 §3. They may still be
  useful to M4 for baseline leverage.

## 5b. The literature that should have been read first

Reading these two before M2 would have saved most of it:

- **Köhler et al. 2025, [arXiv:2505.08315](https://arxiv.org/abs/2505.08315)** (A&A 698 A44)
  — the viper instrument paper. States that CRIRES+ is **not stabilised** and drifts up to
  **1 km/s** without proper wavelength correction (which is precisely M2's ~800 m/s), that
  telluric lines are the cell-free wavelength reference and must be held **fixed**, and that
  the achievable cell-free precision is **10–16 m/s in K band on bright stars** (3 m/s with a
  gas cell). It does **not** characterise cell-free H-band precision, which is the regime
  this project needs.
- **arXiv:2408.10299** — *"RV Measurements of Directly Imaged Brown Dwarf GQ Lup B to Search
  for Exosatellites"*, using **Keck/KPIC**. The first dedicated RV exosatellite search around
  a directly imaged companion, and the right prior for M5 — but SPEC wrongly described it as
  a viper/CRIRES+ paper by the same group. Corrected.

## 6. Values still unverified

**None.** The last one — CD-35 2722 B's H magnitude — was sourced in M3 to Wahhaj et al.
2011 (arXiv:1101.2893): **H = 12.78 ± 0.12** MKO, J = 13.63, K = 12.01. SPEC had estimated
~14 and was wrong by 1.2 mag, in the favourable direction.

Companion magnitudes in hand for M5 calibration: DH Tau b 14.96, kappa And b 15.01,
HN Peg b 15.40, TYC 8998-760-1 b 15.87, GU Psc b 17.70, 51 Eri b 18.99.

One value is *inferred rather than measured* and labelled as such: the GJ 229 Bb/Ba
luminosity ratio ≈ 0.45 in M3 §4 is derived from the amplitude it explains, so it is a
consistency check, not evidence.

## 7. Risk register

**DOWNGRADED (M7) — "cell-free H-band RV precision may not reach ~31 m/s at all."**
The register said every published characterisation of the cell-free regime (Köhler et al.
2025 §5.4) is K band on bright standards, and that nothing established H band on a faint
companion. **The paper under reproduction is that characterisation**: 31.44 m/s, H band,
cell-free, S/N ~ 18 companion, same instrument, same code. It was in hand the whole time and
was never read as evidence about the instrument.

The risk as worded is therefore closed. What replaces it is narrower and entirely ours:
**why does this project's extraction sit 25x above a precision the same configuration is
documented to reach?** M2 §5 lists what remains untried. This is a reproduction gap, not a
physics limit — a materially better position, and it means a null from this pipeline cannot
be published as "the archive route is closed".

**RETIRED (M1) — whether ESO's `calib_level=2` products preserve what `viper` needs.**
If they had been order-merged or resampled, forward-modelling RV extraction would have been
impossible from them and the project would have reverted to building cr2res for all 20
nights. The products are per-order extractions with native wavelength solutions
(7 orders x 3 detectors x 2048 pixels, labelled by `ORDER`/`DETEC`/`XPOS`, curved dispersion
within each segment). `viper` can use them. See M1-RESULTS §5.

Note the first automated verdict said the opposite — `describe()` counted wavelength columns,
saw one, and reported ORDER-MERGED. **Acting on it would have meant rebuilding cr2res for 20
nights that never needed it.** Structural columns beat statistical heuristics; the classifier
now keys on ORDER/DETEC and `tests/test_fetch.py` pins both shapes.

Residual cost, known in advance: the archived product is the *combined* one (ESO serves one
per night; the paper used individual nodding frames), so it carries a ~10% precision penalty
— 34.49 vs 31.44 m/s. M3 must not read that offset as disagreement.
