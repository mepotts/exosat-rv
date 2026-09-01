# Onboarding — read this first

You are picking up an independent astronomy project in pre-publication remediation. This
document is the fastest correct path into it. It assumes you have just opened this folder and
know nothing else about it.

---

## 1. What this is, in one paragraph

Point a high-resolution spectrograph at a *directly imaged companion* rather than at its host
star, and its own reflex motion can be measured — which makes satellites of that companion
detectable. Hoy et al. (2026, *Nature*) did this on the brown dwarf **CD-35 2722 B** and
reported a planetary-mass satellite. This project rebuilt the measurement from the public raw
frames with a separately implemented extraction whose configuration was calibrated against
the published RV series. Its downstream fits do not ingest those values, but the historical
search/reporting code is target- and paper-aware; this is not a blind reproduction. It
runs on a laptop against public archives; there is no telescope time and no institutional
affiliation behind it.

**Findings, with the audit qualifications that must travel with them.** The ~171 d signal is
recovered on the 17 nights retained by an internal quality screen, but the all-18-night series
degrades to noise. The second companion is not reproduced under the models and priors tested
here. η Tel B has no detected signal and has pointwise circular-orbit sensitivity of
~0.5–1.3 M_Jup, conditional on fitter-stage transmission. Clean transfer is demonstrated for
the same-setting nodding control; the former staring-mode claims were withdrawn when those
data proved to be HiRISE fibre observations reduced with a slit recipe.

---

## 2. Read these four files, in this order

| order | file | why |
|---|---|---|
| 1 | **`LESSONS.md`** | The consolidated trap catalogue. Every expensive mistake this project made, and how to avoid repeating it. **Read this before touching anything.** |
| 2 | `README.md` | What the project is and what it found. |
| 3 | `HANDOFF.md` | State of play, target roster, what is queued. |
| 4 | `docs/target-queue.md` | The ledger: every target, its verdict, and the evidence behind it. |

Then read the milestone document for whatever you are about to work on. `M*-RESULTS.md` files
are numbered and each owns a conclusion; `LESSONS.md` maps which one owns what.

---

## 3. Non-negotiable operating rules

These are not style preferences. Each was paid for.

1. **Nothing is submitted, sent, or published without Matthew's explicit per-instance
   approval.** Journals, arXiv, the MPC, email to other researchers — all gated. Preparing a
   submission is fine; sending it is not. See `LESSONS.md` §6.
2. **Never push to a remote or merge to `main` unless told to.**
3. **Do not claim priority.** "First" in this area is an argument about category boundaries,
   not a result. It was deliberately removed from every draft; do not reintroduce it.
4. **Every adopted pipeline change must pass injection recovery.** Internal fit statistics
   have each been, at least once, anti-correlated with truth. The paper's own precision
   statistic is invariant to a common-mode signal by construction.
5. **Check a milestone number is free before writing to it.** `ls docs/milestones/M*-RESULTS.md` and
   `git log --oneline -15`. Writing over a committed milestone has happened. `git status`
   showing `M` on a file you believe you created means something already lived there.
6. **Never re-type a number that a script can print.** An audit found 34 conflicting values
   that entered by hand-transcription, and fifteen wrong citations.
7. **Never reimplement a reference computation to "avoid a dependency."** Import it or extract
   its source. A reimplementation of the period search once produced a false retraction of the
   project's central result.

---

## 4. Environment

The analysis runs under **WSL**, not Windows Python.

```bash
~/viperenv/bin/python          # the ONLY interpreter with astropy
python3                        # has numpy, NOT astropy — will fail confusingly
```

Data lives **outside this repository**, in WSL:

```
~/cr2res/red*/                 # reduced products, per target
~/cr2res/raw_m26/, raw_m30/    # retained raw frames
~/viper-src/*.rvo.dat          # ~800 RV output series from every configuration run
~/viper-src/*_tpl.fits         # viper stellar templates (wavelength in ANGSTROM, not nm)
```

Run analysis scripts from the repo root via WSL:

```bash
# Run from inside WSL, at the repo root. The repo sits on the Windows side, so its WSL
# path is under /mnt/c/... -- `wslpath -a .` prints it and hardcodes no folder name:
cd "$(wslpath -a .)" && ~/viperenv/bin/python scripts/injection/m34_overfit_test.py
```

Scripts derive their own root and honour an override:

```bash
EXOSAT_ROOT=/path/to/repo ./scripts/cr2res/m15_allnights.sh
```

### Traps that will cost you a day each

- **Line endings.** `.gitattributes` pins `*.sh`/`*.py`/`*.sof` to LF. Lose that guard and Windows
  writes CRLF, WSL bash dies on the stray `\r`, and a driver script *appears to run and
  produces nothing*. Diagnose with `file script.sh` from **inside WSL**.
  The guard being present is not the same as it having applied: attributes act at checkout,
  so files cloned before `.gitattributes` existed keep their CRLF forever, and `git status`
  stays **clean** throughout, because git normalises to LF on the way *in*. That is what the
  split left behind -- 104 of 155 tracked scripts, `cr2env.sh` among them, so its
  `export PATH="$CR2RES_PREFIX/bin:$PATH"` resolved to `install\r/bin` and esorex fell off
  PATH without a word. Interrogate the working tree, not the index:

  ```bash
  git ls-files -z "*.sh" "*.py" "*.sof" | xargs -0 file | grep -c CRLF   # want 0
  # repair -- tracked and unmodified, so git rewrites them byte-for-byte:
  git ls-files -z "*.sh" "*.py" "*.sof" | xargs -0 rm -f && git checkout -- .
  ```
- **Wavelength units.** viper templates are Ångström; `cr2res` products are nm. Mixing them
  silently matches zero orders.
- **`set -u` must come after sourcing `cr2env.sh`**, which references unset variables.
- **`cr2res_obs_nodding` requires an even frame count.** With an odd count it writes empty
  products and exits 0.
- **Windows console is cp1252.** Printing `″`, `β` or `η` raises `UnicodeEncodeError` and can
  abort a script *before it writes its output file*. Wrap stdout or avoid non-ASCII in prints.

---

## 5. Building the documents

```bash
python scripts/m16_build_paper.py      # manuscript -> docs/paper/cd35-etatel-draft.html
python scripts/m33_render_notes.py     # the four notes -> matching .html
```

`.md` and `draft.template.html` are **sources**. The `.html` files are **build products** —
never hand-edit them. The notes share the manuscript's stylesheet, lifted at render time, so
changing the manuscript's typography updates all of them.

---

## 6. Where things stand

| draft | state |
|---|---|
| `docs/paper/rnaas-etatel-draft.md` | **Not submission-ready.** Its numerical curve is reproducible, but it must retain the fitter-stage/template-construction limitation and pointwise-completeness wording; it also needs an ORCID and Matthew's decision. |
| `docs/paper/draft.template.html` | **Not submission-ready.** Audit-driven claim corrections are incorporated and `data/repro/` freezes the adopted downstream M14/M15 evidence, but raw/template replay and a valid end-to-end independence experiment remain open. |
| `docs/paper/contrast-wall-note.md` | Checklist cleared bar **one data item**: PDS 70's R is still unmeasured, and closing it needs a nodding reduction or a standard star, not a re-read of what is on disk. The two open DOIs were closed 2026-08-24 (via arXiv, verified through CrossRef by title). |
| `docs/paper/methods-note.md` | **13 open items.** Least advanced; the remaining work is reconciling its own numbers against the milestone documents. |
| `docs/paper/sampler-reproducibility-note.md` | **Open decision.** Retiring it is the recommendation here, because its content is §5.1 of the manuscript and load-bearing there — but `NEXT-DIRECTIONS.md` C2 proposes publishing exactly this material as a standalone RNAAS note. Both cannot hold. Matthew's call. |

**The highest-value open validation project** is now the M38 successor design, not a corrected
rerun of M36. M36's injection bank was paper-derived — K = 1530 m/s at the published
171.454-day orbit — and its execution was also invalid: the gate ignored slope uncertainty,
the runner did not pass the pre-registered polynomial degrees, and the scorer could compare
means formed from different valid-order sets. Treat all existing CD-35 spectra and M34/M36
products as development material. The maintenance runner is deliberately dry-run-only and
cannot produce a post-audit replay. A replacement needs a new frozen, paper-independent
injection bank and fresh validation material; genuine blind rediscovery would additionally
require a clean-room analyst and untouched science data. Otherwise call the result a locked
reanalysis or prospective confirmation, not a retrospective blind experiment.

---

## 7. Things that are true and non-obvious

- **The pipeline is not a reconstruction of Hoy et al.'s unpublished procedure.** It is a
  separate implementation, but its extraction choices were calibrated against their RVs.
  Method diversity is useful; the numerical agreement is not independent evidence.
- **End-to-end independence and absence of overfitting are not established.** M34 bounds
  selection only within a configuration family explored with the published series visible.
  The broad transfer argument was weakened by the HiRISE reclassification, and M36's attempted
  injection-selected test was paper-derived as well as invalid/inconclusive. The strongest
  uncontaminated transfer remains the same-setting η Tel B nodding series.
- **A companion closer than one resolution element has no extractable spectrum at any
  contrast**, and every other diagnostic — precision, dispersion, injection recovery —
  *improves* on a host. Only the spatial profile catches it. This withdrew one verdict.
- **Use M35's v2 photometry, not its original headline.** Nightly/per-camera analysis gives
  no 171.454 d detection (nominal night-permutation *p* = 0.13–0.16, conditional on
  exchangeability of the final camera-corrected night bins). On nested deterministic 720/1440/2880 phase
  grids, the four host/filter rows first reach at least 90% phase recovery at 12/13/12/13
  mmag semiamplitude, so the cross-series threshold is 13 mmag (26 mmag peak-to-peak); 5 mmag
  is recovered in 43.2–44.2% of the finest-grid phases. The two source IDs reuse the same
  2,173 timestamp/camera measurements with alternative aperture magnitudes and are not
  independent replications. This is sensitivity conditional on one observed-noise realization
  and an estimated fixed-period permutation threshold, not a binomial confidence interval.
  Gaia's ordinary RUWE and absent NSS entry are context, not proof of no astrometric perturbation.
- **β Pic b is not white space.** Kenworthy et al. (2026, MNRAS) published dedicated RV
  limits. The slit extraction in this repository is host-dominated, not a planet RV; the public
  HiRISE nights are useful only as a fibre-pipeline or separate-check project, not as a
  priority claim.
- **A catalogue magnitude column widely used in this field is wrong** in two of the three cases
  checked against primary sources, by 1.6 and 2.4 mag. Treat compiled photometry as
  provisional.

---

## 8. First moves

```bash
git log --oneline -20                  # what happened recently
cat docs/LESSONS.md                    # the traps

# Offline tests plus network-marked tests, run from inside WSL. viperenv is the only interpreter carrying the whole set:
# Windows python has no scipy, WSL python3 has no astropy, and each fails a different slice.
# If an import is missing:  ~/viperenv/bin/pip install -e ".[dev]"
cd "$(wslpath -a .)" && PYTHONPATH=src ~/viperenv/bin/python -m pytest tests/ -q
```

Then ask Matthew what he wants next rather than guessing. Editorial decisions remain his. The
adopted RV/per-order/BERV/configuration evidence is now frozen in `data/repro/`, and M37 reruns
the screened/all-18 null from it. Before M38 preregistration, authorized development is limited
to generic code, simulations, and declared controls: the pre-template injection operator,
convergence metrics, paper-free period search and calibration, manifests, and the information
firewall. Do not mount or inspect CD-35 raw/reduced spectra or templates, and do not execute a
claim-bearing M38 target stage, until the protocol is reviewed and frozen and the required
role-separated executor/custodian process exists. Extending raw-to-template reproducibility is
a separate project; it does not relax that barrier.
