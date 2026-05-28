"""Unit tests for docs/hooks/schema.py — JSON-LD emission for docs pages."""

from types import SimpleNamespace

import pytest

import schema  # docs/hooks/schema.py via conftest sys.path injection


class TestNormalizeKeywords:
    def test_list_of_strings(self):
        assert schema._normalize_keywords(["a", "b", "c"]) == "a, b, c"

    def test_list_with_whitespace_and_empties(self):
        assert schema._normalize_keywords(["a", " ", "b"]) == "a, b"

    def test_comma_separated_string_passthrough(self):
        assert schema._normalize_keywords("a, b, c") == "a, b, c"

    def test_none_returns_none(self):
        assert schema._normalize_keywords(None) is None

    def test_empty_string_returns_none(self):
        assert schema._normalize_keywords("   ") is None

    def test_empty_list_returns_none(self):
        assert schema._normalize_keywords([]) is None


class TestBuildAuthor:
    def test_string_name(self):
        assert schema._build_author("Jane Doe") == {"@type": "Person", "name": "Jane Doe"}

    def test_dict_with_name_and_url(self):
        result = schema._build_author({"name": "Jane", "url": "https://example.com"})
        assert result == {"@type": "Person", "name": "Jane", "url": "https://example.com"}

    def test_dict_with_name_only(self):
        assert schema._build_author({"name": "Jane"}) == {"@type": "Person", "name": "Jane"}

    def test_list_of_strings(self):
        result = schema._build_author(["Jane", "John"])
        assert result == [{"@type": "Person", "name": "Jane"}, {"@type": "Person", "name": "John"}]

    def test_single_item_list_unwrapped(self):
        assert schema._build_author(["Jane"]) == {"@type": "Person", "name": "Jane"}

    def test_none_returns_none(self):
        assert schema._build_author(None) is None

    def test_dict_without_name_returns_none(self):
        assert schema._build_author({"url": "https://example.com"}) is None


class TestNormalizeSameAs:
    def test_list_of_urls(self):
        urls = ["https://a.com", "https://b.com"]
        assert schema._normalize_same_as(urls) == urls

    def test_string_wrapped_in_list(self):
        assert schema._normalize_same_as("https://a.com") == ["https://a.com"]

    def test_empty_list_returns_none(self):
        assert schema._normalize_same_as([]) is None

    def test_none_returns_none(self):
        assert schema._normalize_same_as(None) is None


class TestBuildOrganization:
    def test_has_required_fields(self):
        org = schema.build_organization()
        assert org["@type"] == "Organization"
        assert org["@id"] == schema.ORG_ID
        assert org["name"] == "Humanbound"
        assert org["url"] == "https://humanbound.ai"


class TestBuildWebsite:
    def test_uses_config_fields(self):
        config = SimpleNamespace(site_url="https://docs.humanbound.ai/", site_description="Test description.")
        site = schema.build_website(config)
        assert site["@type"] == "WebSite"
        assert site["@id"] == schema.DOCS_WEBSITE_ID
        assert site["url"] == "https://docs.humanbound.ai"  # trailing slash stripped
        assert site["description"] == "Test description."
        assert site["publisher"] == {"@id": schema.ORG_ID}
        assert site["inLanguage"] == "en"


class TestBuildFaqPage:
    def _page(self, faq):
        return SimpleNamespace(
            meta={"faq": faq},
            canonical_url="https://docs.humanbound.ai/foo/",
            file=SimpleNamespace(src_path="foo.md"),
        )

    def test_valid_faq_produces_questions(self):
        page = self._page([{"q": "What is X?", "a": "X is Y."}])
        result = schema.build_faqpage(page)
        assert result["@type"] == "FAQPage"
        assert result["@id"] == "https://docs.humanbound.ai/foo/#faq"
        assert result["mainEntity"] == [
            {"@type": "Question", "name": "What is X?", "acceptedAnswer": {"@type": "Answer", "text": "X is Y."}}
        ]

    def test_missing_faq_returns_none(self):
        page = SimpleNamespace(meta={}, canonical_url="...", file=SimpleNamespace(src_path="foo.md"))
        assert schema.build_faqpage(page) is None

    def test_empty_faq_returns_none(self):
        page = self._page([])
        assert schema.build_faqpage(page) is None

    def test_item_missing_q_or_a_is_skipped(self):
        page = self._page([{"q": "What?", "a": "Answer."}, {"q": "No answer"}])
        result = schema.build_faqpage(page)
        assert len(result["mainEntity"]) == 1
        assert result["mainEntity"][0]["name"] == "What?"

    def test_non_dict_item_is_skipped(self):
        page = self._page([{"q": "Valid", "a": "Yes"}, "garbage"])
        result = schema.build_faqpage(page)
        assert len(result["mainEntity"]) == 1


class TestBuildTechArticle:
    def test_canonical_url_required(self):
        page = SimpleNamespace(canonical_url="", meta={}, title="T", file=SimpleNamespace(src_path="foo.md", abs_src_path="/tmp/foo.md"))
        config = SimpleNamespace(site_description="Site desc")
        with pytest.raises(RuntimeError, match="canonical_url is empty"):
            schema.build_techarticle(page, config)

    def test_minimal_techarticle_shape(self):
        page = SimpleNamespace(
            canonical_url="https://docs.humanbound.ai/foo/",
            meta={},
            title="Foo Title",
            file=SimpleNamespace(src_path="foo.md", abs_src_path="/tmp/foo.md"),
        )
        config = SimpleNamespace(site_description="Site desc")
        result = schema.build_techarticle(page, config)
        assert result["@type"] == "TechArticle"
        assert result["@id"] == "https://docs.humanbound.ai/foo/#article"
        assert result["headline"] == "Foo Title"
        assert result["description"] == "Site desc"
        assert result["url"] == "https://docs.humanbound.ai/foo/"
        assert result["isPartOf"] == {"@id": schema.DOCS_WEBSITE_ID}
        assert result["about"] == {"@id": schema.PRODUCT_ID}
        assert result["publisher"] == {"@id": schema.ORG_ID}
        assert "dateModified" in result

    def test_optional_fields_included_when_present(self):
        page = SimpleNamespace(
            canonical_url="https://docs.humanbound.ai/foo/",
            meta={"keywords": ["a", "b"], "author": "Jane", "sameAs": ["https://x.com"], "description": "Page desc"},
            title="Foo",
            file=SimpleNamespace(src_path="foo.md", abs_src_path="/tmp/foo.md"),
        )
        config = SimpleNamespace(site_description="Site desc")
        result = schema.build_techarticle(page, config)
        assert result["description"] == "Page desc"
        assert result["keywords"] == "a, b"
        assert result["author"] == {"@type": "Person", "name": "Jane"}
        assert result["sameAs"] == ["https://x.com"]
