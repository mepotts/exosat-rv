# Repository organization

The root is a research landing page plus standard package, citation, license, contribution,
and agent metadata. The structure follows the separation of package, tests, documentation,
and examples used by astronomy tools such as
[RadVel](https://github.com/California-Planet-Search/radvel) and
[exoplanet](https://github.com/exoplanet-dev/exoplanet), with additional evidence/history
directories needed for this reanalysis. Their structure informed this layout; their code
and prose were not copied.

| Location | Put here | Do not confuse with |
|---|---|---|
| `src/exosat_rv/` | Importable, reusable code; `m38/` is experimental validation infrastructure | Campaign-specific shell drivers |
| `scripts/` | Research orchestration, report renderers, and historical milestone drivers | Installed CLI/package APIs |
| `tests/` | Small generated fixtures and regression tests | Retained science evidence or downloads |
| `data/published/` | Published comparison RV tables | Independently selected validation truth |
| `data/repro/` | Frozen adopted downstream inputs and their manifest | A complete raw-to-RV archive |
| `data/viper/`, `data/m*.json` | Historical extraction outputs and analysis caches | Automatically current or validated results |
| `data/export/` | Exported tables and manuscript figures | Primary raw observations |
| `docs/milestones/` | Methods, findings, limitations, and superseding notices | A flat list of currently accepted conclusions |
| `docs/evidence/` | Machine-readable validation/run/verification records | Target input spectra |
| `docs/paper/` | Our manuscript sources and generated draft previews | Published literature |
| `papers/` | Third-party literature reference material | Our own paper drafts |
| `containers/m38/` | Restricted target-free runtime prototype | A production scientific environment |

## Stable paths and new work

The September 2026 navigation cleanup preserves scientific paths deliberately. Historical
scripts import other milestone drivers, manifests bind artifacts, and report builders refer
to fixed locations. Renaming those files for appearance would require a separate migration
with dependency and evidence verification. The historical milestone numbers need not be
consecutive; their identifiers are stable provenance, not a recommended execution order.

For new work, use descriptive names within the existing owner directory. Give a new
experiment a distinct plan, result, verification record, and narrative link; do not overwrite
the previous experiment. Add a topic subdirectory when there is a coherent new collection,
not merely to hide a long file list. If an existing path must move, check imports, manifests,
renderers, docs links, package rules, and tests together and preserve provenance.

Local `.venv/`, `.codex-*-tests/`, cache directories, `build/`, `dist/`, downloaded FITS,
and logs are ignored by Git. Their presence on disk does not put them on the GitHub landing
page. They were not deleted in this reorganization.

`containers/m38/` is an exact five-file sealed context. Its guide lives in the parent
`containers/README.md`; adding even a documentation file inside the sealed directory is
intentionally rejected by the runtime audit. Keep the strict allowlist unchanged.

## Source versus generated material

Keep small, load-bearing evidence in Git with its provenance. Keep large/raw downloads
external and document their identity and retrieval path. A hash of an external file identifies
it but does not supply it. Preserve source/result distinctions and third-party rights.

The [script guide](../scripts/README.md) identifies report builders. Generated HTML and
marked numerical blocks are checked or rebuilt from their owning sources, not edited by hand.
The [data guide](../data/README.md) and [evidence guide](evidence/README.md) explain retained
artifact classes. Current installation/usage belongs in the README and getting-started guide;
machine-specific operating history belongs in maintainer onboarding and handoff notes.
