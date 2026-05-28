"""Unit tests for docs/hooks/glossary_autolink.py."""

import re
from types import SimpleNamespace

import pytest

import glossary_autolink


@pytest.fixture(autouse=True)
def reset_cache():
    """Each test starts with a clean module cache."""
    glossary_autolink._GLOSSARY = None
    glossary_autolink._PATTERN = None
    yield


class TestSlugify:
    def test_basic(self):
        assert glossary_autolink._slugify("Testing & Assessment") == "testing-assessment"

    def test_single_word(self):
        assert glossary_autolink._slugify("Defense") == "defense"

    def test_strips_whitespace(self):
        assert glossary_autolink._slugify("  Scoring & Posture  ") == "scoring-posture"

    def test_collapses_multiple_dashes(self):
        assert glossary_autolink._slugify("A---B") == "a-b"


class TestParseGlossary:
    def test_extracts_terms_under_section(self):
        content = (
            "# Glossary\n"
            "\n"
            "## Testing & Assessment\n"
            "\n"
            "| Term | Definition |\n"
            "|------|-----------|\n"
            "| **Orchestrator** | The engine. |\n"
            "| **Experiment** | A test run. |\n"
        )
        terms = glossary_autolink._parse_glossary(content)
        assert terms == {
            "Orchestrator": "testing-assessment",
            "Experiment": "testing-assessment",
        }

    def test_tracks_section_changes(self):
        content = (
            "## Section A\n"
            "| **TermA** | Def. |\n"
            "## Section B\n"
            "| **TermB** | Def. |\n"
        )
        terms = glossary_autolink._parse_glossary(content)
        assert terms["TermA"] == "section-a"
        assert terms["TermB"] == "section-b"

    def test_skips_rows_before_first_section(self):
        content = (
            "| **Orphan** | Before any section. |\n"
            "## Real Section\n"
            "| **Kept** | After section. |\n"
        )
        terms = glossary_autolink._parse_glossary(content)
        assert "Orphan" not in terms
        assert terms["Kept"] == "real-section"

    def test_first_occurrence_wins_on_duplicate(self):
        content = (
            "## Section A\n"
            "| **Term** | First def. |\n"
            "## Section B\n"
            "| **Term** | Second def. |\n"
        )
        terms = glossary_autolink._parse_glossary(content)
        assert terms["Term"] == "section-a"


class TestGlossaryLink:
    def test_from_root(self):
        link = glossary_autolink._glossary_link("index.md", "section")
        assert link == "reference/glossary.md#section"

    def test_from_subdir(self):
        link = glossary_autolink._glossary_link("concepts/red-coworker.md", "anchor")
        assert link == "../reference/glossary.md#anchor"

    def test_from_deep_subdir(self):
        link = glossary_autolink._glossary_link("a/b/c.md", "anchor")
        assert link == "../../reference/glossary.md#anchor"

    def test_from_reference_dir(self):
        link = glossary_autolink._glossary_link("reference/commands.md", "anchor")
        assert link == "glossary.md#anchor"


class TestAutolink:
    def setup_method(self):
        """Seed the cache so we don't read from disk in tests."""
        glossary_autolink._GLOSSARY = {
            "Orchestrator": "testing-assessment",
            "Tier 2 Classifier": "defense",
            "Tier 2": "defense",
        }
        # Longest first so "Tier 2 Classifier" beats "Tier 2".
        terms_sorted = sorted(glossary_autolink._GLOSSARY.keys(), key=len, reverse=True)
        escaped = [re.escape(t) for t in terms_sorted]
        glossary_autolink._PATTERN = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    def test_first_occurrence_only(self):
        md = "Orchestrator does X. Then the Orchestrator does Y."
        result = glossary_autolink._autolink(md, "foo.md")
        # First "Orchestrator" linked, second left alone
        assert result.count("[Orchestrator]") == 1
        assert "[Orchestrator](reference/glossary.md#testing-assessment) does X" in result
        assert "Then the Orchestrator does Y" in result

    def test_exact_case_only(self):
        md = "orchestrator should not link, but Orchestrator should."
        result = glossary_autolink._autolink(md, "foo.md")
        assert "[Orchestrator]" in result
        # lowercase one is left alone
        assert "orchestrator should not link" in result

    def test_longest_term_wins(self):
        md = "The Tier 2 Classifier works well."
        result = glossary_autolink._autolink(md, "foo.md")
        assert "[Tier 2 Classifier]" in result
        # Should NOT also have linked "Tier 2"
        assert "Tier 2 Classifier]" in result
        assert "[Tier 2]" not in result.replace("[Tier 2 Classifier]", "")

    def test_skips_fenced_code(self):
        md = "Use `Orchestrator` in code.\n\n```\nThe Orchestrator runs.\n```\n\nOrchestrator does X."
        result = glossary_autolink._autolink(md, "foo.md")
        # Inside `inline code` should NOT link
        assert "`Orchestrator`" in result
        # Inside fenced block should NOT link
        assert "The Orchestrator runs." in result
        # Outside both should link
        assert "[Orchestrator](" in result

    def test_skips_tilde_fenced_code(self):
        md = "~~~\nOrchestrator inside tilde fence.\n~~~\n\nOrchestrator outside."
        result = glossary_autolink._autolink(md, "foo.md")
        assert "Orchestrator inside tilde fence." in result
        assert "[Orchestrator]" in result

    def test_skips_headings(self):
        md = "## Orchestrator heading\n\nOrchestrator in body."
        result = glossary_autolink._autolink(md, "foo.md")
        assert "## Orchestrator heading" in result  # heading unchanged
        assert "[Orchestrator](" in result  # body linked

    def test_skips_existing_link(self):
        md = "See [Orchestrator config](other.md) and Orchestrator."
        result = glossary_autolink._autolink(md, "foo.md")
        # Existing link untouched
        assert "[Orchestrator config](other.md)" in result
        # Bare term linked
        assert "[Orchestrator](" in result

    def test_skips_image(self):
        md = "![Orchestrator diagram](diagram.png) and Orchestrator below."
        result = glossary_autolink._autolink(md, "foo.md")
        assert "![Orchestrator diagram](diagram.png)" in result
        assert "[Orchestrator](" in result


class TestOnPageMarkdown:
    def test_glossary_self_link_skipped(self):
        glossary_autolink._GLOSSARY = {"Term": "section"}
        glossary_autolink._PATTERN = re.compile(r"\b(Term)\b")
        page = SimpleNamespace(file=SimpleNamespace(src_path="reference/glossary.md"))
        md = "Term should not link in the glossary itself."
        result = glossary_autolink.on_page_markdown(md, page, {"docs_dir": "/tmp"}, [])
        assert "[Term]" not in result

    def test_empty_glossary_returns_unchanged(self, tmp_path):
        # No glossary file — cache initializes to empty dict
        glossary_autolink._GLOSSARY = None
        page = SimpleNamespace(file=SimpleNamespace(src_path="foo.md"))
        result = glossary_autolink.on_page_markdown(
            "Some text.", page, {"docs_dir": str(tmp_path)}, []
        )
        assert result == "Some text."

    def test_normal_page_autolinks(self, tmp_path):
        glossary = tmp_path / "reference" / "glossary.md"
        glossary.parent.mkdir(parents=True)
        glossary.write_text(
            "# Glossary\n\n## Defense\n\n| **Firewall** | The firewall. |\n",
            encoding="utf-8",
        )
        page = SimpleNamespace(file=SimpleNamespace(src_path="concepts/x.md"))
        result = glossary_autolink.on_page_markdown(
            "The Firewall protects.", page, {"docs_dir": str(tmp_path)}, []
        )
        assert "[Firewall](../reference/glossary.md#defense)" in result
