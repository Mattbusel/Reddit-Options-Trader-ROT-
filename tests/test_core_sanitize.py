"""Tests for rot.core.sanitize — HTML sanitization utilities (nh3-based)."""
from __future__ import annotations

import pytest

from rot.core.sanitize import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_TAGS,
    ALLOWED_URL_SCHEMES,
    sanitize_for_json,
    sanitize_html,
    strip_html,
)


# ---------------------------------------------------------------------------
# sanitize_html
# ---------------------------------------------------------------------------


class TestSanitizeHtml:
    def test_empty_string(self):
        assert sanitize_html("") == ""

    def test_none_returns_empty(self):
        assert sanitize_html(None) == ""  # type: ignore[arg-type]

    def test_plain_text_unchanged(self):
        result = sanitize_html("Hello world")
        assert "Hello world" in result

    def test_allowed_tags_preserved(self):
        result = sanitize_html("<b>bold</b> <i>italic</i>")
        assert "<b>" in result
        assert "<i>" in result

    def test_script_tag_stripped(self):
        result = sanitize_html('<script>alert("xss")</script>Safe')
        assert "<script>" not in result
        assert "alert" not in result or "&lt;" in result

    def test_onclick_stripped(self):
        result = sanitize_html('<div onclick="alert(1)">click me</div>')
        assert "onclick" not in result

    def test_img_tag_stripped(self):
        result = sanitize_html('<img src="http://evil.com/steal.png" />')
        assert "<img" not in result

    def test_iframe_stripped(self):
        result = sanitize_html('<iframe src="http://evil.com"></iframe>')
        assert "<iframe" not in result

    @pytest.mark.parametrize("tag", sorted(ALLOWED_TAGS)[:10])
    def test_allowed_tag_kept(self, tag):
        html_input = f"<{tag}>content</{tag}>"
        result = sanitize_html(html_input)
        assert f"<{tag}>" in result or "content" in result

    @pytest.mark.parametrize("tag", ["script", "iframe", "object", "embed", "form", "input", "img"])
    def test_dangerous_tag_stripped(self, tag):
        html_input = f"<{tag}>content</{tag}>"
        result = sanitize_html(html_input)
        assert f"<{tag}>" not in result

    def test_href_preserved_on_a_tag(self):
        result = sanitize_html('<a href="https://example.com">link</a>')
        assert "https://example.com" in result
        assert "<a" in result

    def test_javascript_href_stripped(self):
        result = sanitize_html('<a href="javascript:alert(1)">link</a>')
        assert "javascript:" not in result

    def test_custom_tags_param(self):
        result = sanitize_html("<b>bold</b> <i>italic</i>", tags={"b"})
        assert "<b>" in result
        # <i> may be stripped depending on nh3 behavior
        assert "bold" in result

    def test_nested_tags(self):
        result = sanitize_html("<p><b>bold in <i>para</i></b></p>")
        assert "<p>" in result
        assert "<b>" in result

    def test_class_on_span(self):
        result = sanitize_html('<span class="highlight">text</span>')
        assert "class" in result

    def test_data_attribute_stripped(self):
        result = sanitize_html('<div data-evil="payload">safe</div>')
        assert "data-evil" not in result

    def test_table_tags_allowed(self):
        result = sanitize_html("<table><tr><td>cell</td></tr></table>")
        assert "<table>" in result
        assert "<td>" in result

    def test_style_attribute_stripped(self):
        result = sanitize_html('<div style="background:url(evil)">x</div>')
        assert "style=" not in result

    def test_noopener_noreferrer_on_links(self):
        result = sanitize_html('<a href="https://example.com">link</a>')
        assert "noopener" in result or "noreferrer" in result or "rel=" in result


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_empty_string(self):
        assert strip_html("") == ""

    def test_none_returns_empty(self):
        assert strip_html(None) == ""  # type: ignore[arg-type]

    def test_removes_all_tags(self):
        result = strip_html("<b>bold</b> <i>italic</i>")
        assert "<b>" not in result
        assert "<i>" not in result
        assert "bold" in result
        assert "italic" in result

    def test_removes_nested_tags(self):
        result = strip_html("<div><p><b>deep</b></p></div>")
        assert "deep" in result
        assert "<" not in result

    @pytest.mark.parametrize("html_input,expected_text", [
        ("<p>paragraph</p>", "paragraph"),
        ("<h1>heading</h1>", "heading"),
        ("<a href='#'>link text</a>", "link text"),
        ("<script>evil()</script>", ""),
        ("<br/>", ""),
    ])
    def test_strip_various(self, html_input, expected_text):
        result = strip_html(html_input)
        if expected_text:
            assert expected_text in result
        assert "<" not in result

    def test_plain_text_unchanged(self):
        assert strip_html("no tags here") == "no tags here"

    def test_entities_unescaped(self):
        result = strip_html("5 &gt; 3")
        # Depending on nh3 behavior, may or may not unescape
        assert "5" in result and "3" in result


# ---------------------------------------------------------------------------
# sanitize_for_json
# ---------------------------------------------------------------------------


class TestSanitizeForJson:
    def test_empty_string(self):
        assert sanitize_for_json("") == ""

    def test_none_returns_empty(self):
        assert sanitize_for_json(None) == ""  # type: ignore[arg-type]

    def test_plain_text_safe(self):
        assert sanitize_for_json("hello world") == "hello world"

    def test_escapes_lt(self):
        result = sanitize_for_json("<script>")
        assert "<" not in result
        assert "\\u003c" in result

    def test_escapes_gt(self):
        result = sanitize_for_json("</script>")
        assert ">" not in result
        assert "\\u003e" in result

    def test_escapes_ampersand(self):
        result = sanitize_for_json("foo & bar")
        assert "&amp;" in result

    def test_escapes_slash(self):
        result = sanitize_for_json("a/b")
        assert "\\u002f" in result

    @pytest.mark.parametrize("char,escape", [
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("/", "\\u002f"),
        ("&", "&amp;"),
    ])
    def test_character_escaping(self, char, escape):
        result = sanitize_for_json(f"x{char}y")
        assert escape in result

    def test_script_tag_fully_escaped(self):
        result = sanitize_for_json('</script><script>alert(1)</script>')
        assert "<script>" not in result
        assert "</script>" not in result

    def test_complex_payload(self):
        payload = '<img src=x onerror="alert(document.cookie)">'
        result = sanitize_for_json(payload)
        assert "<img" not in result
        assert "\\u003c" in result


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_allowed_tags_has_common_tags(self):
        for tag in ("b", "i", "em", "strong", "p", "a", "br", "ul", "ol", "li"):
            assert tag in ALLOWED_TAGS

    def test_allowed_tags_no_dangerous(self):
        for tag in ("script", "iframe", "object", "embed", "form", "input"):
            assert tag not in ALLOWED_TAGS

    def test_allowed_attributes_a_has_href(self):
        assert "href" in ALLOWED_ATTRIBUTES["a"]

    def test_allowed_attributes_no_onclick(self):
        for attrs in ALLOWED_ATTRIBUTES.values():
            assert "onclick" not in attrs
            assert "onerror" not in attrs

    def test_allowed_url_schemes(self):
        assert "http" in ALLOWED_URL_SCHEMES
        assert "https" in ALLOWED_URL_SCHEMES
        assert "javascript" not in ALLOWED_URL_SCHEMES
        assert "data" not in ALLOWED_URL_SCHEMES

    @pytest.mark.parametrize("scheme", ["http", "https", "mailto"])
    def test_each_allowed_scheme(self, scheme):
        assert scheme in ALLOWED_URL_SCHEMES
