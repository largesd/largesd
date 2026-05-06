"""HTML sanitization using nh3 (Rust ammonia binding).

Replaces the previous regex-based sanitize_html() which was vulnerable to
bypasses via event handlers, malformed tags, nested scripts, data: URIs, etc.
"""

import nh3

ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "code",
    "pre",
    "span",
    "div",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "*": {"class", "id"},
}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(raw_html: str) -> str:
    """Sanitize raw HTML using an allowlist approach.

    Only known-safe tags, attributes, and URL protocols are preserved.
    All other content is stripped. link_rel is set to prevent tab-nabbing.
    """
    if not raw_html:
        return ""
    return nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        strip_comments=True,
        link_rel="noopener noreferrer nofollow",
    )
