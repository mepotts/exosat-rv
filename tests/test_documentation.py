"""Keep the public entry points navigable without network access.

This intentionally covers maintained navigation pages, not every historical lab note.
It checks inline Markdown file links and simple heading fragments used by these pages.
"""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "docs/getting-started.md",
    "docs/organization.md",
    "docs/validation.md",
    "docs/evidence/README.md",
    "docs/paper/README.md",
    "data/README.md",
    "scripts/README.md",
    "containers/README.md",
)


def _headings(text):
    """GitHub-style slugs for the plain headings referenced by these guides."""
    result = set()
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


@pytest.mark.parametrize("relative", PAGES)
def test_public_navigation_links_resolve(relative):
    page = ROOT / relative
    text = page.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for target in re.findall(r"\]\(([^\s)]+)\)", text):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        assert not parsed.path.startswith("/"), f"nonportable link in {relative}: {target}"
        destination = (page.parent / unquote(parsed.path)).resolve() if parsed.path else page
        assert destination.is_relative_to(ROOT), f"link escapes repository: {target}"
        assert destination.exists(), f"broken link in {relative}: {target}"
        if parsed.fragment:
            assert destination.suffix == ".md", f"unhandled fragment target: {target}"
            assert unquote(parsed.fragment) in _headings(destination.read_text(encoding="utf-8")), (
                f"missing heading in {relative}: {target}"
            )


def test_landing_page_has_public_research_sections():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    expected = {
        "results-and-limitations",
        "quickstart",
        "reproducibility",
        "repository-guide",
        "citation-and-license",
    }
    assert expected <= _headings(text)
    assert "ONBOARDING.md" not in text
    assert (ROOT / "AGENTS.md").is_file()
    assert "not independent confirmation" in text


def test_heading_helper_preserves_numbers_and_duplicate_suffixes():
    assert _headings("## 12. Blocking decision register\n## Quickstart\n## Quickstart\n") == {
        "12-blocking-decision-register",
        "quickstart",
        "quickstart-1",
    }
