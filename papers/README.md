# Literature archive

Papers this project reads and cites, fetched from arXiv and the publishers. **Not this
project's own writing** — the manuscripts are in [`../docs/paper/`](../docs/paper/).

- `text/` — extracted plain text, **committed**. It is what the milestone documents and the
  audits cite, so a claim can be checked against the source without re-fetching anything.
- `pdf/` — the originals. **Gitignored**: fetched from arXiv, not ours to redistribute.

Release source archives and Python source distributions exclude `text/`. Its copies remain
in the Git checkout/history for the existing audit trail; this exclusion does not remove them
from GitHub or establish redistribution rights. Readers of a release archive should retrieve
papers through the DOI/arXiv references in the milestone documents. The project's MIT license
does not relicense third-party publications. Unsent correspondence is also excluded from
release archives.

Every citation in the project was read against these files rather than against memory; the pass
that did it, and the fourteen errors it found, are in
[`../docs/audits/REFERENCE-AUDIT.md`](../docs/audits/REFERENCE-AUDIT.md).

The extracted text carries NUL bytes from PDF extraction, so git treats these files as binary
and never rewrites their line endings. That is deliberate — see `../.gitattributes`.
