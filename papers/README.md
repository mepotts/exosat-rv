# Literature archive

Papers this project reads and cites, fetched from arXiv and the publishers. **Not this
project's own writing** — the manuscripts are in [`../docs/paper/`](../docs/paper/).

- `text/` — extracted plain text, **committed**. It is what the milestone documents and the
  audits cite, so a claim can be checked against the source without re-fetching anything.
- `pdf/` — the originals. **Gitignored**: fetched from arXiv, not ours to redistribute.

Every citation in the project was read against these files rather than against memory; the pass
that did it, and the fourteen errors it found, are in
[`../docs/audits/REFERENCE-AUDIT.md`](../docs/audits/REFERENCE-AUDIT.md).

The extracted text carries NUL bytes from PDF extraction, so git treats these files as binary
and never rewrites their line endings. That is deliberate — see `../.gitattributes`.
