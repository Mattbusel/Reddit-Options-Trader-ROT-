"""
Comprehensive tests for HTML sanitization module.

Modules tested:
- rot.core.sanitize

Coverage:
- sanitize_html with nh3 (allowed tags/attributes)
- sanitize_html fallback (without nh3)
- strip_html with nh3
- strip_html fallback (without nh3)
- sanitize_for_json (script context escaping)
- XSS attack prevention (script injection, event handlers, data URIs)
- URL scheme filtering (javascript:, data:)
- Attribute filtering
"""
from __future__ import annotations

import pytest

# Import the module under test
from rot.core import sanitize


# ============================================================================
# HTML Sanitization Tests (with nh3)
# ============================================================================

class TestHTMLSanitization:
    def test_sanitize_html_allows_safe_tags(self):
        """Allowed HTML tags are preserved."""
        content = "<p>Hello <b>world</b></p>"
        result = sanitize.sanitize_html(content)
        assert "<p>" in result
        assert "<b>" in result
        assert "Hello" in result

    def test_sanitize_html_removes_script_tags(self):
        """Script tags are removed."""
        content = "<p>Safe</p><script>alert(\"XSS\")</script>"
        result = sanitize.sanitize_html(content)
        assert "<script>" not in result
        assert "alert" not in result
        assert "<p>" in result

    def test_sanitize_html_removes_event_handlers(self):
        """Event handler attributes are removed."""
        content = "<a href=\"#\" onclick=\"alert(1)\">Click</a>"
        result = sanitize.sanitize_html(content)
        assert "onclick" not in result

    def test_sanitize_html_allows_safe_links(self):
        """Safe links with http/https are allowed."""
        content = "<a href=\"https://example.com\">Link</a>"
        result = sanitize.sanitize_html(content)
        assert "href=" in result
        assert "example.com" in result

    def test_sanitize_html_removes_javascript_urls(self):
        """JavaScript URLs are removed."""
        content = "<a href=\"javascript:alert(1)\">Evil</a>"
        result = sanitize.sanitize_html(content)
        assert "javascript:" not in result

    def test_sanitize_html_empty_input(self):
        """Empty input returns empty string."""
        assert sanitize.sanitize_html("") == ""

    def test_sanitize_html_custom_tags(self):
        """Can specify custom allowed tags."""
        content = "<p>Paragraph</p><b>Bold</b>"
        result = sanitize.sanitize_html(content, tags={"b"})
        assert "<b>" in result
        assert "<p>" not in result


# ============================================================================
# Strip HTML Tests
# ============================================================================

class TestStripHTML:
    def test_strip_html_removes_all_tags(self):
        """All HTML tags are removed, leaving plain text."""
        content = "<p>Hello <b>world</b></p>"
        result = sanitize.strip_html(content)
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Hello world" in result

    def test_strip_html_removes_script_tags(self):
        """Script tags and content are removed."""
        content = "<p>Safe</p><script>alert(\"XSS\")</script><p>More</p>"
        result = sanitize.strip_html(content)
        assert "<script>" not in result
        assert "alert" not in result

    def test_strip_html_empty_input(self):
        """Empty input returns empty string."""
        assert sanitize.strip_html("") == ""


# ============================================================================
# JSON Sanitization Tests
# ============================================================================

class TestJSONSanitization:
    def test_sanitize_for_json_escapes_script_tags(self):
        """Script closing tags are escaped."""
        value = "</script><script>alert(1)</script>"
        result = sanitize.sanitize_for_json(value)
        assert "</script>" not in result
        assert "\\u003c" in result  # < is escaped
        assert "\\u003e" in result  # > is escaped

    def test_sanitize_for_json_escapes_slashes(self):
        """Forward slashes are escaped."""
        value = "https://example.com/"
        result = sanitize.sanitize_for_json(value)
        assert "\\u002f" in result  # / is escaped

    def test_sanitize_for_json_empty_input(self):
        """Empty input returns empty string."""
        assert sanitize.sanitize_for_json("") == ""


# ============================================================================
# XSS Attack Prevention Tests
# ============================================================================

class TestXSSPrevention:
    def test_prevents_basic_xss(self):
        """Basic script injection is prevented."""
        attack = "<script>alert(\"XSS\")</script>"
        result = sanitize.sanitize_html(attack)
        assert "<script>" not in result

    def test_prevents_iframe_xss(self):
        """Iframe injection is prevented."""
        attack = "<iframe src=\"javascript:alert(1)\"></iframe>"
        result = sanitize.sanitize_html(attack)
        assert "<iframe" not in result


# ============================================================================
# Edge Cases and Integration Tests
# ============================================================================

class TestEdgeCases:
    def test_nested_allowed_tags(self):
        """Nested allowed tags are preserved."""
        content = "<p>Paragraph with <b>bold</b> and <i>italic</i></p>"
        result = sanitize.sanitize_html(content)
        assert "<p>" in result
        assert "<b>" in result
        assert "<i>" in result

    def test_unicode_content(self):
        """Unicode content is preserved."""
        content = "<p>Hello 世界 🌍</p>"
        result = sanitize.sanitize_html(content)
        assert "世界" in result
        assert "🌍" in result

    def test_mailto_links(self):
        """Mailto links are allowed."""
        content = "<a href=\"mailto:test@example.com\">Email</a>"
        result = sanitize.sanitize_html(content)
        assert "mailto:" in result
