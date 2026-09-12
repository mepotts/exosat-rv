# Documentation

Start with the [project overview](../README.md). This index separates current results and
reproduction instructions from the historical lab record and maintainer operations.

## Read or reproduce the research

| Guide | Contents |
|---|---|
| [Getting started](getting-started.md) | Source installation, offline checks, downstream replay, and CLI scope |
| [M37: current audit](milestones/M37-RESULTS.md) | Corrected results and limits on the central reproduction claim |
| [Data guide](../data/README.md) | Comparison data versus extracted RVs, cached results, and frozen evidence |
| [Frozen evidence](../data/repro/README.md) | Included artifacts, hashes, external dependencies, and replay boundary |
| [Ongoing validation](validation.md) | M38 development evidence and remaining scientific gates |
| [Data sources](DATA-SOURCES.md) | Archive endpoints and known coverage limitations |
| [AI involvement](AI-CHECKLIST.md) | Stage-specific disclosure and evidence pointers |

## Research record

- [Milestone index](milestones/README.md): chronological investigations, including superseded
  conclusions. **M37 controls current claim wording**, not the most optimistic older headline.
- [Evidence records](evidence/README.md): machine-readable simulation results and verification
  artifacts, distinct from observational inputs in `data/`.
- [Citation audit](audits/REFERENCE-AUDIT.md) and [property audit](audits/PROPERTY-AUDIT.md):
  historical findings; read later corrections before using their conclusions.
- [Target ledger](target-queue.md): dataset verdicts and corrections. Archive availability and
  embargo dates are historical observations, not promises of present access.
- [Original specification](SPEC.md), [build plan](BUILD-PLAN.md), and
  [research directions](NEXT-DIRECTIONS.md): design history, not automatically current authority.

The former long-form root README mixed these histories into the landing page. Its exact
[pre-reorganization version](https://github.com/mepotts/exosat-rv/blob/907a524d1e718048ece8834563886c446591f4ac/README.md)
remains in Git history; individual milestone records remain in place.

## Manuscripts and release preparation

[Manuscript sources and generated drafts](paper/README.md) are work in progress, not published
papers. The [release notes](releases/v0.1.0.md) and
[release verification](releases/v0.1.0-verification.md) describe a particular prepared
development snapshot, not a formal release of every subsequent commit.
[Publishing notes](PUBLISHING.md) and the [JOSS checklist](paper/joss/RELEASE-CHECKLIST.md)
are planning documents, not submission approval.

## Contribute or maintain

- [Contributing](../CONTRIBUTING.md): setup, tests, evidence, and review expectations.
- [Agent instructions](../AGENTS.md): project-specific operational boundaries for coding agents.
- [Maintainer onboarding](ONBOARDING.md): local environment notes and entry points.
- [Lessons](LESSONS.md) and [handoff history](HANDOFF.md): detailed traps and prior decisions.
- [Organization guide](organization.md): file placement, stable paths, and source/output distinctions.
- [VIPER runbook](viper-runbook.md): historical extraction recipe; read its correction notices
  and the relevant milestone before attempting any replay.
