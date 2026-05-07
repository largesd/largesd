"""Unit tests for backend.sanitize — nh3-based HTML sanitization.

Covers OWASP XSS cheat-sheet vectors and common bypass techniques.
"""

from backend.sanitize import sanitize_html


class TestScriptTagRemoval:
    def test_simple_script_tag(self):
        raw = '<script>alert("XSS")</script>'
        assert "<script" not in sanitize_html(raw).lower()

    def test_script_with_src(self):
        raw = '<script src="http://evil.com/xss.js"></script>'
        assert sanitize_html(raw) == ""

    def test_nested_script(self):
        raw = "<scr<script>ipt>alert(1)</scr</script>ipt>"
        result = sanitize_html(raw)
        assert "<script>" not in result.lower()

    def test_malformed_script(self):
        raw = "<script >alert('xss')</script >"
        result = sanitize_html(raw)
        assert "<script" not in result.lower()

    def test_script_in_attribute(self):
        raw = "<p>safe</p><script>alert(1)</script>"
        result = sanitize_html(raw)
        assert "<script" not in result.lower()
        assert "safe" in result


class TestEventHandlerRemoval:
    def test_onerror(self):
        raw = "<img src=x onerror=alert(1)>"
        result = sanitize_html(raw)
        assert "onerror" not in result.lower()

    def test_onclick(self):
        raw = '<div onclick="alert(1)">Click me</div>'
        result = sanitize_html(raw)
        assert "onclick" not in result.lower()
        assert "Click me" in result

    def test_onload(self):
        raw = "<body onload=alert(1)>"
        result = sanitize_html(raw)
        assert "onload" not in result.lower()

    def test_onmouseover(self):
        raw = '<a onmouseover="alert(1)">hover</a>'
        result = sanitize_html(raw)
        assert "onmouseover" not in result.lower()
        assert "hover" in result

    def test_mixed_case_event_handler(self):
        raw = "<img src=x ONERROR=alert(1)>"
        result = sanitize_html(raw)
        assert "onerror" not in result.lower()


class TestAllowedTagsPreserved:
    def test_paragraph(self):
        raw = "<p>Hello world</p>"
        assert sanitize_html(raw) == "<p>Hello world</p>"

    def test_strong_and_em(self):
        raw = "<strong>bold</strong> and <em>italic</em>"
        assert sanitize_html(raw) == raw

    def test_heading_tags(self):
        raw = "<h1>Title</h1><h2>Subtitle</h2>"
        assert sanitize_html(raw) == raw

    def test_list_tags(self):
        raw = "<ul><li>One</li><li>Two</li></ul>"
        assert sanitize_html(raw) == raw

    def test_table_tags(self):
        raw = "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>B</td></tr></tbody></table>"
        assert sanitize_html(raw) == raw

    def test_anchor_with_safe_href(self):
        raw = '<a href="https://example.com" title="Example">link</a>'
        result = sanitize_html(raw)
        assert 'href="https://example.com"' in result
        assert 'title="Example"' in result
        assert "link" in result

    def test_blockquote_and_pre(self):
        raw = "<blockquote>Quote</blockquote><pre>Code</pre>"
        assert sanitize_html(raw) == raw


class TestHrefProtocolFiltering:
    def test_javascript_protocol_removed(self):
        raw = '<a href="javascript:alert(1)">click</a>'
        result = sanitize_html(raw)
        assert "javascript:" not in result.lower()
        assert "click" in result

    def test_data_uri_removed(self):
        raw = '<a href="data:text/html,<script>alert(1)</script>">click</a>'
        result = sanitize_html(raw)
        assert "data:" not in result.lower()
        assert "click" in result

    def test_http_allowed(self):
        raw = '<a href="http://example.com">link</a>'
        result = sanitize_html(raw)
        assert 'href="http://example.com"' in result
        assert "link" in result

    def test_https_allowed(self):
        raw = '<a href="https://example.com">link</a>'
        result = sanitize_html(raw)
        assert 'href="https://example.com"' in result
        assert "link" in result

    def test_mailto_allowed(self):
        raw = '<a href="mailto:test@example.com">email</a>'
        result = sanitize_html(raw)
        assert 'href="mailto:test@example.com"' in result
        assert "email" in result

    def test_vbscript_removed(self):
        raw = '<a href="vbscript:msgbox(1)">click</a>'
        result = sanitize_html(raw)
        assert "vbscript:" not in result.lower()
        assert "click" in result


class TestLinkRelAttribute:
    def test_link_rel_added(self):
        raw = '<a href="https://example.com">link</a>'
        result = sanitize_html(raw)
        assert 'rel="noopener noreferrer nofollow"' in result


class TestEmptyAndNoneInput:
    def test_empty_string(self):
        assert sanitize_html("") == ""

    def test_none_input(self):
        assert sanitize_html(None) == ""


class TestCommentRemoval:
    def test_html_comment_removed(self):
        raw = "<!-- comment --><p>text</p>"
        result = sanitize_html(raw)
        assert "<!--" not in result
        assert "<p>text</p>" in result


class TestOwaspVectors:
    """Selected vectors from the OWASP XSS Cheat Sheet."""

    def test_img_src_javascript(self):
        raw = "<img src=\"javascript:alert('XSS')\">"
        result = sanitize_html(raw)
        assert "javascript:" not in result.lower()

    def test_img_src_onerror(self):
        raw = "<img src=x onerror=\"alert('XSS')\">"
        result = sanitize_html(raw)
        assert "onerror" not in result.lower()

    def test_body_onload(self):
        raw = '<body onload=alert("XSS")>'
        result = sanitize_html(raw)
        assert "onload" not in result.lower()

    def test_iframe_removed(self):
        raw = '<iframe src="http://evil.com"></iframe>'
        result = sanitize_html(raw)
        assert "<iframe" not in result.lower()

    def test_object_removed(self):
        raw = '<object data="http://evil.com"></object>'
        result = sanitize_html(raw)
        assert "<object" not in result.lower()

    def test_embed_removed(self):
        raw = '<embed src="http://evil.com">'
        result = sanitize_html(raw)
        assert "<embed" not in result.lower()

    def test_style_tag_removed(self):
        raw = '<style>body{background:url("javascript:alert(1)")}</style>'
        result = sanitize_html(raw)
        assert "<style" not in result.lower()

    def test_form_removed(self):
        raw = '<form action="http://evil.com"><input type="submit"></form>'
        result = sanitize_html(raw)
        assert "<form" not in result.lower()

    def test_input_removed(self):
        raw = '<input type="text" onfocus="alert(1)">'
        result = sanitize_html(raw)
        assert "<input" not in result.lower()
        assert "onfocus" not in result.lower()

    def test_svg_onload(self):
        raw = '<svg onload="alert(1)">'
        result = sanitize_html(raw)
        assert "onload" not in result.lower()
        assert "<svg" not in result.lower()

    def test_mathml_removed(self):
        raw = "<math><mtext></mtext></math>"
        result = sanitize_html(raw)
        assert "<math" not in result.lower()

    def test_base_tag_removed(self):
        raw = '<base href="http://evil.com">'
        result = sanitize_html(raw)
        assert "<base" not in result.lower()
