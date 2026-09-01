"""The three files that describe this release must agree, offline.

`pyproject.toml`, `CITATION.cff` and `.zenodo.json` each carry a version, and two of them
carry the same abstract in different words. The JOSS release checklist calls the drift out
by name -- Zenodo's GitHub integration has historically preferred `.zenodo.json` over
`CITATION.cff` when both are present, so whichever one is stale is the one the DOI record
may end up quoting. A citation record that disagrees with itself is the kind of error that
survives into other people's bibliographies, so it is checked here rather than remembered.

`CITATION.cff` is authoritative for the prose; `.zenodo.json` is kept in lockstep.
No YAML dependency: the abstract is a folded block and is read as text, and `tomllib` is
standard library on the 3.11 floor this project already requires.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/mepotts/exosat-rv"
HOY_DOI = "10.1038/s41586-026-10751-w"


def _cff():
    return (ROOT / "CITATION.cff").read_text(encoding="utf-8")


def _zenodo():
    return json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))


def _pyproject():
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def _folded(text, key):
    """Read a YAML folded scalar (`key: >-`) back into one line."""
    m = re.search(r"^%s: >-\n((?:  .*\n)+)" % re.escape(key), text, re.M)
    assert m, "no folded '%s:' block in CITATION.cff" % key
    return " ".join(line.strip() for line in m.group(1).splitlines() if line.strip())


def test_all_three_files_agree_on_the_version():
    cff = re.search(r'^version: "([^"]+)"', _cff(), re.M)
    assert cff, "CITATION.cff carries no version"
    assert cff.group(1) == _pyproject()["project"]["version"] == _zenodo()["version"]


def test_the_zenodo_description_is_the_citation_abstract_verbatim():
    """Not 'similar to' -- identical. The two drifted once already."""
    assert _zenodo()["description"] == _folded(_cff(), "abstract")


def test_both_records_point_at_the_repository_that_is_actually_archived():
    assert re.search(r'^repository-code: "([^"]+)"', _cff(), re.M).group(1) == REPO_URL
    ids = {r["identifier"] for r in _zenodo()["related_identifiers"]}
    assert REPO_URL in ids


def test_the_audited_paper_is_cited_and_not_claimed_as_a_supplement():
    """`isSupplementTo` on Hoy et al. would present this as material accompanying their
    Nature paper. This project audits and cites that work; it is not their supplement."""
    rel = {r["identifier"]: r["relation"] for r in _zenodo()["related_identifiers"]}
    assert rel.get(HOY_DOI) == "cites"


@pytest.mark.parametrize("path", ["HANDOFF.md", "LESSONS.md", "SPEC.md", "AI-CHECKLIST.md"])
def test_documents_named_in_the_citation_record_exist_where_it_says(path):
    """The 2026-08-24 reorganisation moved every one of these under docs/. A citation
    record that names a path the archive does not contain is a broken record."""
    for text in (_cff(), json.dumps(_zenodo())):
        for named in re.findall(r"(?<![\w/])((?:docs/)?%s)" % re.escape(path), text):
            assert (ROOT / named).exists(), "%s names %r, which does not exist" % (path, named)
