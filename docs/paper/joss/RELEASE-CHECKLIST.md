# Release checklist — minting a Zenodo DOI for exosat-rv

Scope note: written 2026-08-13, when nothing in it had been executed. **Revised
2026-08-31: the repository split described in §2 and the metadata synchronization in §3
have since been carried out.** Still not done: no git tag, no GitHub release, no Zenodo
record, and no release-date declaration. The 2026-08-13 state was verified against the repository contents and
two read-only, unauthenticated checks: the public GitHub releases/tags API, and Zenodo's
public search API. Items marked ✅ below were verified on 2026-08-23.

## 1. Current state

- **`CITATION.cff`** exists at the repository root and is substantially complete:
  title, audit-qualified abstract, one author (Matthew Potts), license (MIT),
  `repository-code`, development version (`0.1.0`), keywords, and a `references:` list of
  the five papers this project engages with most directly. It deliberately has no
  `date-released` while no release exists. ✅ `repository-code`
  now reads `https://github.com/mepotts/exosat-rv` (repointed at the split; it previously
  pointed into the monorepo tree). Gap: the author's `orcid` field is present only as a
  commented-out `# TODO: add your ORCID` line.
- **`.zenodo.json`** exists at the repository root and covers title, `upload_type:
  software`, the same audit-qualified description, one creator (`Potts, Matthew`),
  license, `access_right: open`, keywords, version, and related identifiers. The remaining
  author-metadata gap in both records is the ORCID.
- ✅ **The two prose records are synchronized.** `CITATION.cff` is authoritative and an
  offline test requires `.zenodo.json`'s description to be byte-identical after YAML
  folding. This fixed the drift recorded by the first version of this checklist.
- ✅ **Both metadata files are now at the archived repository's root**, which is what
  Zenodo reads. Before the split they sat one level down, inside `astronomy/exosat-rv/`,
  where a monorepo release would not have used them.
- **No release or version tag exists yet.** `git ls-remote --tags origin` against
  `mepotts/exosat-rv` returned nothing when checked 2026-08-23, and the local tag list is
  empty as of 2026-08-31. The unrelated `itf-state` tag carried through the split was deleted;
  see §2.
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
- [x] Add a `version` field to `.zenodo.json` and keep it synchronized with
      `pyproject.toml`'s `[project] version` and `CITATION.cff`'s `version:` at every
      release. **Done 2026-08-24** — all three read `0.1.0`, and the synchronisation is
      no longer a thing to remember: `tests/test_citation_metadata.py` fails if they
      diverge, so CI catches it before a release does.
- [x] Add `related_identifiers` to `.zenodo.json`. **Done 2026-08-24**, and the choice
      of vocabulary was made deliberately: the repository is `isSupplementTo` (what
      Zenodo's own GitHub integration uses), and **Hoy et al. 2026 is `cites`, not
      `isSupplementTo`**. `isSupplementTo` would present this record as material
      accompanying their Nature paper. It is an independently authored reanalysis, not
      material supplied by those authors, and metadata that implies otherwise is a misrepresentation
      that propagates into OpenAIRE and every aggregator downstream. A test asserts the
      relation stays `cites`.
- [x] **Decided 2026-08-24: `CITATION.cff` is authoritative for the prose, and
      `.zenodo.json` is kept in lockstep** — its `description` is now the CITATION
      abstract *verbatim*, written programmatically rather than retyped, and a test
      asserts byte-identity so the drift below cannot recur. Both also had a stale
      `HANDOFF.md` path, from before the reorganisation moved it under `docs/`; fixed in
      both, and a test now checks that every document either record names actually
      exists. **Still to confirm at release time:** Zenodo's GitHub integration has historically
      preferred `.zenodo.json` over `CITATION.cff` when both are present at the
      repository root that gets archived — confirm current behavior at release time,
      since this has changed before. The abstract/description drift is already guarded
      by an offline test.
- [ ] Decide the version number for the first tagged release. `pyproject.toml` and
      `CITATION.cff` currently both say `0.1.0`, and the README records completed results
      through M37 plus an unexecuted M38 successor-protocol draft, with audit remediation still
      open — i.e. active, evolving work. Whether the first Zenodo
      snapshot should be tagged `v0.1.0` ("first archived state") or bumped to `v1.0.0`
      ("stable, citable API") is Matthew's call, not a default to assume.
- [ ] At the moment of tagging, add `CITATION.cff`'s `date-released` using the actual
      release date. It is intentionally absent until then.

**Step B — resolve the monorepo structure (see §2): DONE 2026-08-23.**

- [x] Execute the plan already recorded in `PUBLISHING.md`:
      `git filter-repo --subdirectory-filter exosat-rv` into a new, standalone
      repository, preserving commit history. ✅ 110 commits carried, earliest intact.
- [x] Verify the filtered result actually installs and its test suite still passes —
      `pip install -e ".[dev]"` then `pytest -m "not network"` — in a fresh clone, not
      assumed from the fact that internal paths are relative. ✅ Done exactly that way
      on 2026-08-23; the current offline suite and lint state must be rechecked from the release
      candidate after the audit correction pass. Live-archive checks are network-marked and CI
      deselects them. CI does not currently run lint, so lint needs a separate release check.
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
      everything." **Progress 2026-08-31:** `data/repro/` now freezes the adopted M14/M15
      RV/per-order/BERV, parameter and target tables, the VIPER configuration and tracked
      source patch observed in the audited checkout, and their hashes. That configuration
      records checkout state only; it does not prove which configuration governed the
      historical extraction runs. This is an in-repository downstream evidence bundle, not a
      Zenodo deposit or a raw-to-template replay; raw/reduced spectra and fitted templates
      remain external, with the latter hash-bound.
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
      not match the published series exactly: its amplitude is high by 19–34% in regression
      slope or 39–54% in direct fits, and its precision remains confound-limited.
      `data/published/hoy2026_nature_table2_rvs.csv` is a
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
      (`docs/paper/draft.template.html`) currently points at the project repository and
      explicitly distinguishes the downstream bundle from external raw/template assets;
      once a dataset DOI is minted, that section (and any eventual
      journal submission's own data-availability statement) should cite it directly.
      That edit is downstream of this checklist, not made here.

## 5. What this document does not do

This checklist does not authorize a tag, branch, GitHub release, Zenodo action, submission,
or correspondence. Preparatory metadata may be corrected in the repository; every external
release action remains gated to Matthew's explicit per-instance approval.
