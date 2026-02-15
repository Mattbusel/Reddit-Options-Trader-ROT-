"""Tests for XSS prevention utilities (sanitize.py).

Validates:
- HTML sanitization with nh3
- Plain text stripping
- JSON-in-HTML escaping
"""
from __future__ import annotations

from rot.core.sanitize import sanitize_for_json, sanitize_html, strip_html


class TestSanitizeHtml:
    """Test sanitize_html function."""

    def test_empty_string(self):
        assert sanitize_html("") == ""

    def test_none_returns_empty(self):
        assert sanitize_html(None) == ""

    def test_plain_text_unchanged(self):
        assert sanitize_html("Hello world") == "Hello world"

    def test_allowed_tags_preserved(self):
        result = sanitize_html("<b>bold</b> and <i>italic</i>")
        assert "<b>" in result
        assert "<i>" in result

    def test_preserves_table_formatting(self):
        table = "<table><tr><td>Data</td></tr></table>"
        result = sanitize_html(table)
        assert "<table>" in result
        assert "<td>" in result

    def test_script_tag_stripped(self):
        result = sanitize_html('<script>alert("xss")</script>Normal text')
        assert "<script>" not in result
        assert "Normal text" in result

    def test_onclick_attribute_stripped(self):
        result = sanitize_html('<a href="#" onclick="alert(1)">click</a>')
        assert "onclick" not in result

    def test_img_onerror_stripped(self):
        result = sanitize_html('<img src=x onerror="alert(1)">')
        assert "onerror" not in result

    def test_javascript_href_stripped(self):
        result = sanitize_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in result

    def test_strips_iframe(self):
        result = sanitize_html('<iframe src="https://evil.com"></iframe>')
        assert "<iframe" not in result

    def test_nested_malicious_tags(self):
        result = sanitize_html('<div><script>alert(1)</script></div>')
        assert "<script>" not in result

    def test_custom_tags_parameter(self):
        result = sanitize_html("<b>bold</b> <div>div</div>", tags={"b"})
        assert "<b>" in result
        assert "<div>" not in result

    def test_nested_script_encoding(self):
        result = sanitize_html('<scr<script>ipt>alert(1)</scr</script>ipt>')
        assert "<script>" not in result


class TestStripHtml:
    """Test strip_html function."""

    def test_empty_string(self):
        assert strip_html("") == ""

    def test_none_returns_empty(self):
        assert strip_html(None) == ""

    def test_removes_all_tags(self):
        result = strip_html("<b>bold</b> and <i>italic</i>")
        assert "<b>" not in result
        assert "<i>" not in result
        assert "bold" in result

    def test_plain_text_unchanged(self):
        assert strip_html("Hello world") == "Hello world"

    def test_strips_script_entirely(self):
        result = strip_html("<script>alert(1)</script>other text")
        assert "<script>" not in result
        assert "other text" in result


class TestSanitizeForJson:
    """Test sanitize_for_json function."""

    def test_empty_string(self):
        assert sanitize_for_json("") == ""

    def test_none_returns_empty(self):
        assert sanitize_for_json(None) == ""

    def test_script_close_tag_escaped(self):
        result = sanitize_for_json("</script>")
        assert "</script>" not in result
        assert "\\u003c" in result

    def test_angle_brackets_escaped(self):
        result = sanitize_for_json("<img src=x>")
        assert "<" not in result
        assert ">" not in result

    def test_ampersand_escaped(self):
        result = sanitize_for_json("a&b")
        assert "&amp;" in result

    def test_normal_text_safe(self):
        result = sanitize_for_json("Hello world 123")
        assert "Hello world 123" in result
