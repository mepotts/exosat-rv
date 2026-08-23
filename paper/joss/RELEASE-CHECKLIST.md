# Release checklist — minting a Zenodo DOI for exosat-rv

Scope note: written 2026-08-13, when nothing in it had been executed. **Revised
2026-08-23: the repository split described in §2 has since been carried out**, and
`CITATION.cff`'s `repository-code` has been repointed with it. Still not done: no git
tag, no GitHub release, no Zenodo record, and no edit to `.zenodo.json` or
`pyproject.toml`. The 2026-08-13 state was verified against the repository contents and
two read-only, unauthenticated checks: the public GitHub releases/tags API, and Zenodo's
public search API. Items marked ✅ below were verified on 2026-08-23.

## 1. Current state

- **`CITATION.cff`** exists at the repository root and is substantially complete:
  title, abstract, one author (Matthew Potts), license (MIT), `repository-code`,
  version (`0.1.0`), `date-released` (`2026-08-10`), keywords, and a `references:`
  list of the five papers this project engages with most directly. ✅ `repository-code`
  now reads `https://github.com/mepotts/exosat-rv` (repointed at the split; it previously
  pointed into the monorepo tree). Gap: the author's `orcid` field is present only as a
  commented-out `# TODO: add your ORCID` line.
- **`.zenodo.json`** exists at the repository root and covers title, `upload_type:
  software`, description, one creator (`Potts, Matthew`), license, `access_right:
  open`, and keywords. Gaps relative to `CITATION.cff`: no `version` field, no
  `related_identifiers` (nothing links the record to the GitHub repo URL or to the Hoy
  et al. 2026 paper this project reproduces), and no ORCID.
- **The two files have already drifted.** `CITATION.cff`'s abstract ends "...No
  discovery is claimed and nothing is submitted anywhere. Beyond the reproduction..."
  while `.zenodo.json`'s description ends "...No discovery is claimed. Beyond the
  reproduction..." — the "nothing is submitted anywhere" clause exists in one and not
  the other. Harmless today; a warning that maintaining two overlapping metadata files
  by hand will not stay in sync without a deliberate process (see §3).
- ✅ **Both metadata files are now at the archived repository's root**, which is what
  Zenodo reads. Before the split they sat one level down, inside `astronomy/exosat-rv/`,
  where a monorepo release would not have used them.
- **No release or version tag exists yet.** `git ls-remote --tags origin` against
  `mepotts/exosat-rv` returns nothing (checked 2026-08-23). One stray tag, `itf-state`,
  survives in *local* clones: an automated itf-linker data snapshot authored by
  `github-actions[bot]`, carried through the split, unrelated to exosat-rv and not
  reachable from `main`. It is not a version release and should be deleted rather than
  reasoned about — see §2.
- **No Zenodo record exists yet.** A search of Zenodo's public API for "exosat-rv"
  returns no matching record.
- **Zenodo–GitHub integration status is not verifiable from the repository.** Whether
  `github.com/mepotts/exosat-rv` is enabled at
  `https://zenodo.org/account/settings/github/` can only be checked by logging into
  the Zenodo account tied to `matthew.e.potts@gmail.com`; this document does not
  assume either state.
- ✅ **`exosat-rv` is now its own repository**, `github.com/mepotts/exosat-rv`, with
  `main` pushed. This was the structural fact that shaped almost everything below, and
  it has changed; §2 records how.

## 2. The monorepo blocker — resolved 2026-08-23

**This section described the one blocker that had to be decided before any release. It
has been resolved: the split was executed. The reasoning is kept because it is why the
split happened, and because it explains what would break if the work ever moved back
under a shared root.**

### Why it was a blocker

Zenodo's GitHub integration archives **whole repositories** on each GitHub Release, and
reads metadata from the file(s) at the **repository root**. `exosat-rv` was
`mepotts/astronomy/exosat-rv/`, one of five independent sub-projects in that root. Two
consequences followed, neither of them exosat-rv-specific:

1. A GitHub Release on `mepotts/astronomy` would have archived **all five sub-projects
   plus `DISCOVERY/`, `IDEAS/`, everything** as a single zip, because there was no
   root-level `CITATION.cff`/`.zenodo.json` to scope or describe it — Zenodo would have
   fallen back to a generic, GitHub-derived title and description, and none of the
   curation already done in `CITATION.cff` would have been used.
2. Even if a root-level metadata file had been added and hand-written to describe
   `exosat-rv` specifically, the archived **content** would still have been the whole
   monorepo, and every later release of *any* sub-project (say, a future
   `adql-copilot` JOSS-driven tag) would have re-archived `exosat-rv`'s state at that
   same commit as a side effect — version numbers and DOIs would stop corresponding to
   independent release histories per project.

The fix was recorded in advance in `PUBLISHING.md` — **"at submission time, exosat-rv
splits into its own repository via `git filter-repo --subdirectory-filter exosat-rv`
(full history preserved), then tags v1.0 and mints its DOI. Until then it stays here."**

### What was actually done

- `exosat-rv` is now **`github.com/mepotts/exosat-rv`**, with `main` pushed.
- **History was preserved**: 110 commits carried across, the earliest
  (`Start exosat-rv: the paper's 20 epochs are exactly the 20 public nights`,
  2026-08-09) intact. The split was a real filter, not a file copy.
- Both metadata files now sit at the archived root, where Zenodo will read them.
- `CITATION.cff`'s `repository-code` was repointed to the new URL.
- The copy still under `astronomy/exosat-rv/` is marked non-canonical in its README.
  Deleting it is a separate, pending decision; until then, **commit to this repository,
  not that one**.

### Loose ends the split left behind — closed 2026-08-23

- ✅ **The `itf-state` tag came across and has been deleted.** It was an itf-linker data
  snapshot from 2026-07-31, not reachable from `main`, and it was the only tag in the
  repository — so release tooling reasoning about "the tags in this repo" would have
  seen a sibling project's artifact first. It existed only in local clones; the remote
  has no tags. This repository now has no tags, so the first one will be its own
  release. (Restore, if ever needed: `git tag itf-state 9205806`.)
- ✅ **~425 MB of gitignored working assets have been copied across** — 30 reference
  PDFs under `papers/pdf/` (115 MB) and 290 files of `data/` FITS products (310 MB).
  They are re-fetchable and are excluded from git by design, but they had existed only
  in the monorepo working copy, so deleting that copy would have lost them. Counts
  verified equal on both sides after the copy.
- **Still open, and outside this repository:** the monorepo's own root `README.md` and
  any sibling project that cross-references `exosat-rv` still point at the old path.
  That is a pass over `mepotts/astronomy`, not over this repository.

## 3. Checklist: tagged release -> Zenodo DOI

**Step A — metadata, at the exosat-rv level (can be done anytime before tagging):**

- [ ] Add a real ORCID to `CITATION.cff`'s author entry (currently a commented-out
      TODO). Zenodo, OpenAIRE, and ORCID's own auto-import all key off this field.
- [ ] Add a `version` field to `.zenodo.json` and keep it synchronized with
      `pyproject.toml`'s `[project] version` and `CITATION.cff`'s `version:` at every
      release (today all three would need to agree; only two currently carry the field).
- [ ] Add `related_identifiers` to `.zenodo.json`: at minimum, a link to the GitHub
      repository itself, and a link to Hoy et al. 2026 (DOI `10.1038/s41586-026-10751-w`)
      as the work this software reproduces (relation `isSupplementTo` or `cites`, per
      Zenodo's controlled vocabulary — pick the more accurate one at write time).
- [ ] Reconcile `CITATION.cff` vs `.zenodo.json` and pick one as authoritative, or keep
      both in lockstep deliberately. Zenodo's GitHub integration has historically
      preferred `.zenodo.json` over `CITATION.cff` when both are present at the
      repository root that gets archived — confirm current behavior at release time,
      since this has changed before — and fix the abstract/description drift noted in
      §1 either way.
- [ ] Decide the version number for the first tagged release. `pyproject.toml` and
      `CITATION.cff` currently both say `0.1.0`, and the README states "M0–M26
      complete, M27 open" — i.e. active, evolving work. Whether the first Zenodo
      snapshot should be tagged `v0.1.0` ("first archived state") or bumped to `v1.0.0`
      ("stable, citable API") is Matthew's call, not a default to assume.
- [ ] At the moment of tagging, update `CITATION.cff`'s `date-released` (currently a
      stale `2026-08-10`) to the actual release date.

**Step B — resolve the monorepo structure (see §2): DONE 2026-08-23.**

- [x] Execute the plan already recorded in `PUBLISHING.md`:
      `git filter-repo --subdirectory-filter exosat-rv` into a new, standalone
      repository, preserving commit history. ✅ 110 commits carried, earliest intact.
- [x] Verify the filtered result actually installs and its test suite still passes —
      `pip install -e ".[dev]"` then `pytest -m "not network"` — in a fresh clone, not
      assumed from the fact that internal paths are relative. ✅ Done exactly that way
      on 2026-08-23: **123 passed, 2 deselected**. The two deselected are the
      network-marked tests; CI now deselects them too, for the same reason.
- [x] Decide the new repository's name and the GitHub account/org it lives under.
      ✅ `github.com/mepotts/exosat-rv`.
- [x] Update `CITATION.cff`'s `repository-code` field (was
      `https://github.com/mepotts/astronomy/tree/main/exosat-rv`) to the new URL.
      ✅ Now `https://github.com/mepotts/exosat-rv`.
- [x] Update in-repo links that hard-code the monorepo URL, e.g. the manuscript
      draft's link to `github.com/mepotts/astronomy/blob/main/AI-CHECKLIST.md`.
      ✅ Repointed in the manuscript and both HTML drafts.
- [ ] **Still open:** update the links that point into the monorepo path from *outside*
      this repository — the monorepo's root `README.md` and any sibling project that
      cross-references exosat-rv. This is a pass over `mepotts/astronomy`, not over this
      repository, and it is not done here.
- [x] Delete the stray `itf-state` tag so this repository's only tags are its own
      releases. ✅ Done; the repository now has no tags. See §2.
- [x] Move or re-fetch the ~425 MB of gitignored working assets (`papers/pdf/`,
      `data/`) before the monorepo copy is deleted. ✅ Copied across and verified. See §2.
- [ ] ~~*Not recommended:* stay in the monorepo and enable Zenodo on
      `mepotts/astronomy` as-is.~~ **Moot** — the split has been executed, so this
      alternative is closed. It required a root-level `CITATION.cff`/`.zenodo.json`
      describing the whole five-project portfolio, an archived zip containing all five
      projects, and shared version/DOI history across unrelated release cadences.

**Step C — Zenodo/GitHub mechanics. The repository is now settled (Step B done):**

- [ ] Enable the GitHub integration for the target repository at
      `https://zenodo.org/account/settings/github/`, under the account tied to
      `matthew.e.potts@gmail.com`. This requires granting Zenodo OAuth access to the
      GitHub account.
- [ ] Confirm the toggle is **on** before tagging — Zenodo archives releases published
      after the integration is enabled; it does not retroactively archive past tags
      (irrelevant here today, since no tag exists yet, but matters if one is ever
      created before the toggle is flipped).
- [ ] Publish a **GitHub Release** (not a bare `git tag`) from the target commit.
      Zenodo's integration listens for the "release published" webhook event
      specifically; a pushed tag with no accompanying Release will not trigger an
      archive.
- [ ] After the webhook fires, verify the resulting Zenodo record directly: correct
      title, author name/ORCID, license (should inherit MIT from `LICENSE`, but
      confirm), version string, and that the archived zip's contents are actually what
      was intended to be cited — it should now be exosat-rv alone, not five projects.
- [ ] Add the Zenodo-provided DOI badge to `README.md`. Not done as part of
      this task (existing files were not modified); listed here as the concrete next
      step for whoever executes the release.
- [ ] Back-fill the minted DOI into `CITATION.cff` (the `cff-version: 1.2.0` schema
      supports an `identifiers:` block with `type: doi`). Also a follow-up edit, not
      done here.

**Step D — versioning going forward:**

- [ ] Zenodo mints two DOIs on the first release: a **concept DOI** (stable across all
      versions, for citing "the software" in general) and a **version DOI** (for citing
      the exact snapshot used in a given analysis). Every later tagged release adds a
      new version DOI under the same concept DOI. Decide which one `CITATION.cff`'s
      `message:` field should point readers to — most venues want the concept DOI in
      running text and the specific version DOI in a reproducibility/methods statement.

## 4. Checklist: a companion dataset deposit (the reduced RV series)

This is a **separate** Zenodo upload (`upload_type: dataset`, not `software`) for the
actual measured radial-velocity series, distinct from the code that produces them. It
is not automatic and needs its own scoping:

- [ ] **Scope it explicitly.** `data/` today mixes inventory JSON, posterior-sample
      arrays, per-milestone provenance bookkeeping, and the actual per-target RV
      tables in one directory. A dataset deposit should contain the RV tables only
      (e.g. the per-target combined and per-order series referenced throughout the
      `M*-RESULTS.md` files), not a dump of everything under `data/`. Deciding exactly
      which files qualify is a human call — Matthew's, not a default "upload
      everything."
- [ ] **Write a self-contained data dictionary.** A Zenodo dataset is expected to be
      interpretable without also cloning the code repository. Today the meaning of
      each column (BJD timescale, RV units and sign convention, what "combined" vs
      "per-order" vs "per-nodding" means, which pipeline run/commit produced a given
      file) lives implicitly across `LESSONS.md`, the `M*-RESULTS.md` series, and
      inline code comments — none of it is currently a standalone document a dataset
      consumer could read on its own.
- [ ] **Attach provenance per row or per file**, not just in surrounding prose: which
      ESO programme ID and observation night each measurement derives from.
      `DATA-SOURCES.md` and the `M*-RESULTS.md` files have this information; a dataset
      deposit needs it carried in a header or sidecar manifest shipped with the data
      itself.
- [ ] **Choose a data license, separately from the code's MIT license.** CC-BY-4.0
      (attribution required) or CC0 (public-domain dedication) are the usual choices
      for derived scientific datasets; MIT is a software license and is not the
      conventional choice for data.
- [ ] **Re-check ESO's archive terms of use for this specific act.** Publishing
      scientific *results* derived from ESO archival data with programme-ID
      acknowledgment is standard and already this project's practice. Redistributing a
      standalone, bulk, machine-readable dataset of derived reduced values is a
      further step beyond citing a results table in a paper, and should be checked
      against ESO's current data-access policy before choosing a license — this is
      flagged as an open question, not resolved here.
- [ ] **Cross-link the two deposits.** The dataset record's `related_identifiers`
      should point at the software DOI (`isDerivedFrom` or similar), and the software
      record should be updated to point back at the dataset DOI once minted — in
      practice this means the software deposit's metadata gets a follow-up edit after
      the dataset exists, or the two are coordinated to mint together.
- [ ] **Separate "ours" from "theirs."** This project's own from-raw extraction does
      not yet match the published precision (confound-limited; M14 measures a 20–40%
      amplitude excess), and `data/published/hoy2026_nature_table2_rvs.csv` is a
      transcription of Hoy et al.'s own table, kept for comparison. A dataset deposit
      must clearly separate the project's own measured values from that transcription;
      redistributing a transcribed copy of another paper's table as a separately
      citable dataset is a different act from using it internally for comparison, and
      is worth a moment's thought about Nature's reuse terms before it is included in
      a public deposit.
- [ ] **Timing, tied to the embargo calendar.** The epochs that decide the project's
      central open questions are embargoed until Dec 2026 – May 2027 (see
      `docs/target-queue.md`). A dataset deposited now would be a snapshot of the
      currently non-embargoed subset only. Whether to deposit now and version a
      follow-up once the embargo lifts, or wait and deposit once, is Matthew's call,
      not a technical default.
- [ ] **Update the data-availability statement once a DOI exists.** The manuscript
      draft's "Data & code availability" section
      (`docs/paper/draft.template.html`) currently points at "the project repository"
      for everything; once a dataset DOI is minted, that section (and any eventual
      journal submission's own data-availability statement) should cite it directly.
      That edit is downstream of this checklist, not made here.

## 5. What this document does not do

No git command was run, no tag or branch was created, no GitHub release was published,
no Zenodo account action was taken, and no existing file in this repository —
including `CITATION.cff`, `.zenodo.json`, and `pyproject.toml` — was modified in the
course of writing it.
