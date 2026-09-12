# Contributing

Scientific corrections, reproducibility reports, and focused software improvements are
welcome. Start with the [README](README.md), [current audit](docs/milestones/M37-RESULTS.md),
and [getting-started guide](docs/getting-started.md). Report problems through
[GitHub issues](https://github.com/mepotts/exosat-rv/issues), including the commit, environment,
command, expected behavior, and relevant output. Do not upload secrets or private data.

## Development checks

Install from source with the `dev` extra and run from the repository root:

```bash
python -m ruff check src tests
python -m compileall -q src tests scripts
python -m pytest -q -m "not network"
python scripts/m37_package_evidence.py --verify
python scripts/m37_render_results.py --check
```

CI checks package/test lint, compilation, and offline tests on Python 3.11 and 3.12.
Historical campaign scripts have separately recorded lint debt; compiling them is not a
claim that every script passes current lint rules. Add regression tests for fixes and use
synthetic fixtures where possible. Live-service checks must carry the `network` marker.

## Evidence and scientific claims

- Distinguish published comparison RVs, separately extracted RVs, simulations, and external
  spectra. Do not describe a downstream replay or fitter-stage injection as raw-to-RV or
  template-construction validation.
- Retain failed experiments and superseding corrections. Do not overwrite frozen evidence
  or regenerate a historical result in place just to make a test pass.
- Derive reported numbers from retained machine-readable results and checkable scripts.
  Record inputs, seeds, effective configuration, software identity, and limitations.
- For M38, generic synthetic development is allowed, but **target access is gated**. Follow
  the [draft protocol](docs/milestones/M38-PROTOCOL-DRAFT.md) and its unresolved decision
  register. Passing unit tests does not freeze a protocol or validate observational controls.
- Keep reusable code in `src/exosat_rv/`, drivers in `scripts/`, regression tests in `tests/`,
  scientific input/output tables in `data/`, and explanatory records in `docs/`. See the
  [organization guide](docs/organization.md) before moving existing artifacts.

Keep changes focused and request review of their scientific implications as well as code.
Coding-agent review is useful software review; it is not the independent human governance
or observer-blindness required by the future scientific protocol.

## Manuscripts, attribution, and external actions

Edit [manuscript sources](docs/paper/README.md), not generated HTML. Keep citation metadata
consistent and disclose AI involvement through [the checklist](docs/AI-CHECKLIST.md).
Project code is MIT licensed; that does not relicense third-party literature or archive data.

Maintainer approval is required for merging/pushing on their behalf. Journal/arXiv submissions,
release publication, DOI deposits, and correspondence require separate explicit approval;
a repository push is not approval for those actions.
