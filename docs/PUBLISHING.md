# Publishing from this repository

*Release preparation, scientific claim boundaries, and historical venue guidance for
an independent (unaffiliated) researcher. Updated 2026-09-05 for the qualified
`v0.1.0` software/reanalysis candidate. The venue survey was checked on 2026-08-13;
its fees, policies, timing, and eligibility statements are historical, not reverified
for this preparation pass. Check the chosen venue's current terms before submitting.*

## Current preparation scope

The repository is preparing a **`v0.1.0` research-software and downstream-reanalysis
snapshot**, retaining the existing development version. This is not a declaration of a
stable API, broad instrument/target validation, or independent replication of the
original study. The [candidate release notes](releases/v0.1.0.md) define the deliverable;
the [verification record](releases/v0.1.0-verification.md) records which checks were
actually run, their results, and remaining limits.

[M37](milestones/M37-RESULTS.md) controls the scientific claims: extraction was calibrated
against the published RVs; the near-171-day result is conditional on an internal
17-of-18-night screen; all-18-night BERV-adjusted searches are compatible with noise under
the stated calibration. The second companion was not reproduced under the tested models
and priors. The eta Tel B curve is a pointwise circular-orbit completeness sensitivity
conditional on fitter-stage transmission. Broad transfer across observing modes and
end-to-end independent replication are not established.

[M38](milestones/M38-CONTROL-DEVELOPMENT.md) supplies tested generic and synthetic
infrastructure. It has not selected the observational control suite, frozen the scientific
decisions, validated a real CRIRES+/VIPER adapter, or run an authorized target experiment.
Those scientific steps are separate from preparing this software snapshot.

Preparing files and pushing code to GitHub do not themselves create a formal GitHub
Release, archive DOI, or manuscript submission. This pass prepares the candidate and does
not perform those publication actions. At publication, use the actual release date and
the identifier returned by the archive; do not invent a DOI, release date, or author ORCID.
The [release checklist](paper/joss/RELEASE-CHECKLIST.md) tracks the later publication steps.

> **Provenance.** This document was written in the `mepotts/astronomy` monorepo and covers
> that whole portfolio, so its historical venue survey still refers to sibling
> projects (`adql-copilot`, `itf-linker`, `seti-ellipsoid-broker`) that do not live in this
> repository. Their dated status is historical context, not a current queue for this repo.
> Paths that point at exosat-rv's own files are repo-relative and resolve here;
> references to the siblings link out to the monorepo. The venue guidance itself is
> project-independent, which is why it was carried across rather than trimmed.

## Historical venue survey — checked 2026-08-13

The descriptions below preserve the earlier survey. They do not establish current fees,
policy compliance, eligibility, or submission readiness for any manuscript.

**[Research Notes of the AAS (RNAAS)](https://journals.aas.org/research-notes/)** —
the first rung, and free. ≤1,500 words, one figure *or* one table, moderated by an
editor but not peer-reviewed, published within ~72 hours, DOI-assigned and indexed
in ADS (citable forever). Independent affiliations are accepted. Right-sized for:
an eta Tel B sensitivity note, the ITF-linker method note, or the seti-ellipsoid tool
note. The latter two belong to the sibling projects; their draft status was recorded
in the monorepo survey. No priority claim is made here.

**[The Open Journal of Astrophysics](https://astro.theoj.org/)** — free,
peer-reviewed, arXiv-overlay: the paper lives on arXiv and OJA runs real referee
review on it. The strongest free venue for a full-length paper from an
unaffiliated author. Requires the paper to be on arXiv first (see endorsement,
below).

**Nature Matters Arising** — the formal channel for a substantive challenge to a
published Nature paper. The historical survey considered this route for the CD-35
2722 B analysis; the current result is non-reproduction under the tested models and
priors, not a general contradiction of the reported second companion. The survey
recorded no submission fee and a process in which the original authors see the submission
and respond. Etiquette (and the journal) expect prior correspondence with the
authors — the drafted query letter in
[`paper/author-query-draft.md`](paper/author-query-draft.md) is
step one of that path, not just politeness.

**Mainstream journals** (AJ/ApJ, A&A, MNRAS, PASP) — all accept "Independent
Researcher, City" as an affiliation; review is on the work. Publication charges
vary widely (A&A currently publishes under subscribe-to-open with no author
charge while that program holds; AAS journals and MNRAS carry article charges
with waiver processes). Check current terms per journal.

**[JOSS](https://joss.theoj.org/)** (Journal of Open Source Software) — free,
peer-reviewed, for the *tools*: adql-copilot's draft in
[`adql-copilot/paper/`](https://github.com/mepotts/astronomy/tree/main/adql-copilot/paper) is aimed here.

**arXiv** — the field's noticeboard; astro-ph requires a one-time
**endorsement** for new submitters. Practical routes for an independent: an
established author who knows the work (author correspondence, e.g. the Hoy query,
often leads here naturally), or publish first via RNAAS (which needs no arXiv)
and let the record speak. Never pay anyone for endorsement; it is free by design.

**Zenodo** — an archive that can provide a citable software DOI. A metadata file or
pushed tag alone does not establish an archived record. The integration must be configured
and an actual release/deposit completed, then the resulting record verified. Repository
contents do not establish the account's integration state; see the release checklist.

## What the field expects a companion repo to look like

The pattern, from working astronomers' repositories (the
[showyourwork](https://github.com/showyourwork/showyourwork) ecosystem and the
repo-per-paper practice common among its users): **one repository or one clearly
bounded directory per paper**, containing the manuscript source, every script
needed to regenerate every figure from raw or archived data, an environment
specification, and a tagged release archived to Zenodo at submission time — so
the README can carry an arXiv badge, a DOI badge, and a one-line "reproduce
figure N with command X."

The exosat-rv draft is generated from a template with figure exports produced by
committed scripts. **The repository split was completed on 2026-08-23**; the canonical
repository is now [mepotts/exosat-rv](https://github.com/mepotts/exosat-rv). The earlier
plan to split at submission and tag v1.0 is superseded. The current candidate retains
version `0.1.0`, with readiness determined by its verification record.

The bundled `data/repro/` evidence supports downstream reanalysis. ESO raw exposures,
reduced spectra, and fitted templates are external, and the historical effective
environment/configuration was not captured at execution. Committed scripts and an
audited checkout do not by themselves reconstruct the complete historical raw-to-RV run.

## What to expose, and what to hold

**Exposed deliberately, as policy.** Dead ends, retractions, correction logs,
`LESSONS.md`, the milestone documents, pipeline code, and the bounded downstream
evidence bundle. Preserve the distinction between executable code, retained evidence,
and historical processing that cannot yet be replayed. The audit trail makes corrections
inspectable; it does not substitute for independent scientific validation.

**Held, or gated on a human decision:**

- **Unsent correspondence.** A letter should reach its recipient before the
  public; drafts belong out of the tree or sent promptly once public.
- **Headline results derived from another team's active observing programme**,
  until the priority question is decided by a person, not a pipeline (the
  standing example: HIP 65426 b, `docs/milestones/M20-RESULTS.md` §5 — made public
  2026-08-13 by explicit decision).
- **Speculation about other groups' unpublished or embargoed data.** Embargo
  dates are public facts and may be listed; inferences about what rivals will
  find are not for the record.
- **Always:** no credentials or tokens, no third-party personal contact details,
  and no machinery that submits to shared registries (MPC, TNS, journals)
  without per-batch human review — automated submission is permanently out of
  scope.

## AI authorship, disclosure, and submission

Most of the historical analysis in this repository was carried out by Claude agents
via Claude Code under the owner's direction; later auditing and engineering also used
Codex agents. Disclose the tools and their roles from the recorded work rather than
inventing model/version details. The following publisher-policy discussion was assembled
in the 2026-08-13 survey and requires venue-specific rechecking before submission.

**This project's authorship remains human.** Matthew Potts is the named author and
answers for every claim. The AI systems are disclosed tools; their involvement does
not transfer responsibility for the work.

**Disclose substantive AI use as part of the methodology.** Follow the chosen venue's
current disclosure rules. Since in this work the agent drove much of the analysis,
the honest form is a Methods paragraph describing the
agentic workflow itself — model and version, what the agent did, and the
verification actually performed, with the limitations found by M37. Historical
published-RV scoring and fitter-stage injection recovery must be identified as such;
they did not establish independence or full-chain signal retention.

The disclosure is split into two artifacts so the manuscript stays lean: a
condensed **"AI contribution and responsibility statement"** in the paper itself
([`docs/paper/draft.template.html`](paper/draft.template.html)),
and the full stage-by-stage **[AI-CHECKLIST.md](AI-CHECKLIST.md)** it links to —
involvement levels 0–4 per research stage with evidence pointers into the
repository, modeled on the Agents4Science 2025 mandatory checklists. No
mainstream venue requirement is established by this document; the checklist is a
voluntary, inspectable disclosure, and the chosen venue may require its own form.
Future papers copy and re-grade the checklist table per paper. The honest
adaptation: where the WASP-4b paper's human co-author was a domain expert
auditing the AI's analysis, here verification is primarily *mechanical*
(historical fitter-stage injection checks, published-RV comparisons, offline
recalculations, and later synthetic tests) plus the public audit trail. Those checks
have different scopes and do not establish external domain-expert review. The human role is direction,
adversarial challenge, external-consequence decisions, and sole accountability.
The statement says so explicitly rather than borrowing the expert-audit framing.

Mapped to the CRediT taxonomy journals ask for (AI listed as a disclosed tool,
never an author):

| CRediT role | Matthew Potts (author) | AI agents (disclosed tools) |
|---|---|---|
| Conceptualization | direction, research questions | approach within those questions |
| Methodology, Software, Data curation | — | ✓ |
| Formal analysis, Investigation, Visualization | — | ✓ |
| Validation | adversarial review of claims | machine-enforced gates |
| Writing — original draft | — | ✓ |
| Writing — review & editing | ✓ | revisions under review |
| Supervision, Project administration | ✓ | — |
| Accountability for the published record | ✓ (sole) | none — cannot hold it |

**Check the target venue's current AI policy at submission time** — policies
are converging but not identical (Science required a policy change to allow
disclosed AI text at all; some funders now reject substantially-AI-developed
proposals). Venues that experiment with AI-as-author (Sakana's AI Scientist at
an ICLR 2025 workshop; Stanford's Agents4Science 2025, where AI agents are
primary authors and reviewers by design) are sandboxed meta-science
experiments, not channels for astronomy results.

**Worked examples of AI-driven papers (found 2026-08-13):**

- *Transit Timing Variations of Exoplanet WASP-4b: Evidence of Orbital Decay* —
  [Agents4Science 2025](https://openreview.net/forum?id=Yja2KMahOL), AI primary
  author with a working exoplanet astronomer (A. Shporer, MIT) as human
  co-author. Archival public-data orbit reanalysis — the same shape as the
  exosat-rv work. Its mandatory AI-involvement checklist (disclosure by research
  stage: planning, execution, writing) is the closest thing to a standard
  "methods section for AI-driven work" that exists; readable in a browser
  (OpenReview blocks automated fetchers).
- *QITT-Enhanced … Cosmological Parameter Estimation* — same venue; the AI
  framework is literally the named first author ("Denario Astropilotai"), with
  professional cosmologists as co-authors ([Denario project,
  arXiv:2510.26887](https://arxiv.org/abs/2510.26887)).
- *Kosmos* ([arXiv:2511.02824](https://arxiv.org/abs/2511.02824)) — autonomous
  discovery system; its report style is the model for quantified transparency:
  independent scientists audited its statements (79.4% accurate) and the papers
  disclose the AI/human split explicitly.
- Sakana's AI Scientist-v2 passed an ICLR 2025 *workshop* review fully
  AI-generated — then was withdrawn by design; the enduring peer-reviewed
  artifact is the human-authored Nature paper about the system. The lesson:
  AI-as-author remains a sandboxed experiment; AI-driven work with a human
  accountable author is the publishable path in mainstream venues.

**AI never submits.** Three independent reasons, any one sufficient: (1)
submission portals require legal representations — originality, licensing,
accountability — that only a human can truthfully make; (2) peer review is a
months-long correspondence with an accountable person; (3) this repository's
standing safety policy gates every outward send behind per-item human review.
Agents prepare submission packages down to the last byte; the owner presses
submit.

## Current exosat-rv queue

| Work | State | Next step |
|---|---|---|
| `v0.1.0` software/reanalysis snapshot | Candidate preparation; no stable-API or independent-replication claim | Complete and review the linked candidate verification, then make a separate publication decision |
| eta Tel B sensitivity note | Numerical curve is reproducible; retain pointwise circular-orbit and fitter-stage limitations from M37 | Reconcile the draft and verify venue requirements before considering submission; no "first" claim |
| CD-35 analysis and tested second-companion non-reproduction | Draft requires the complete/screened and paper-calibration qualifications | Resolve scientific/reproducibility limitations appropriate to the proposed paper and review the submission package |
| M38 validation | Generic/synthetic engineering checkpoint; protocol remains a draft | Establish independent control truth, validate the real extraction chain, calibrate decisions, and freeze/review the protocol before target access |

The monorepo survey also listed ITF-linker and seti-ellipsoid-broker RNAAS drafts and an
adql-copilot JOSS draft on 2026-08-13. Those sibling projects are outside this preparation
scope; their current readiness has not been checked here.
