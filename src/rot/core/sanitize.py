"""HTML sanitization utilities for defense-in-depth XSS prevention.

Jinja2 autoescape is ON by default (Starlette), so these functions are
a secondary safety layer for cases where content might be rendered with |safe
or stored in JSON blobs that feed into templates.

Uses nh3 (Rust-based, ~20x faster than deprecated bleach).
"""
from __future__ import annotations

import html
import logging
import re

log = logging.getLogger(__name__)

try:
    import nh3
    _HAS_NH3 = True
except ImportError:
    nh3 = None  # type: ignore[assignment]
    _HAS_NH3 = False
    log.warning("nh3 not installed -- HTML sanitization will use basic escaping only")


# Allowed tags for rich text (e.g., formatted signal reasoning)
ALLOWED_TAGS: set[str] = {
    "b", "i", "em", "strong", "a", "br", "p", "ul", "ol", "li",
    "code", "pre", "blockquote", "span", "div",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td",
}

# Allowed attributes per tag
# NOTE: "rel" for <a> is set via link_rel parameter, NOT in attributes
# (nh3/ammonia panics if "rel" appears in both places)
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "span": {"class"},
    "div": {"class"},
    "td": {"class", "colspan", "rowspan"},
    "th": {"class", "colspan", "rowspan"},
}

# URL schemes allowed in href attributes
ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto"}


def sanitize_html(content: str, tags: set[str] | None = None) -> str:
    """Sanitize HTML content, keeping only allowed tags and attributes.

    Args:
        content: Raw HTML string (potentially from user input).
        tags: Set of allowed tag names. Defaults to ALLOWED_TAGS.

    Returns:
        Sanitized HTML string safe for rendering with |safe.
    """
    if not content:
        return ""

    allowed = tags if tags is not None else ALLOWED_TAGS

    if _HAS_NH3:
        return nh3.clean(
            content,
            tags=allowed,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_URL_SCHEMES,
            link_rel="noopener noreferrer",
            strip_comments=True,
        )

    # Fallback: strip ALL HTML (conservative)
    return html.escape(content)


def strip_html(content: str) -> str:
    """Remove all HTML tags, returning plain text.

    Args:
        content: HTML string.

    Returns:
        Plain text with all tags removed.
    """
    if not content:
        return ""

    if _HAS_NH3:
        return nh3.clean(content, tags=set())

    # Fallback: regex strip + unescape
    text = re.sub(r"<[^>]+>", "", content)
    return html.unescape(text)


def sanitize_for_json(value: str) -> str:
    """Escape a string for safe embedding in JSON within HTML <script> tags.

    Prevents injection via </script> or HTML entities inside JSON.

    Args:
        value: Raw string to embed in JSON.

    Returns:
        String safe for JSON-in-HTML embedding.
    """
    if not value:
        return ""
    # Replace characters that could break out of script context
    return (
        value
        .replace("&", "&amp;")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("/", "\\u002f")
    )
