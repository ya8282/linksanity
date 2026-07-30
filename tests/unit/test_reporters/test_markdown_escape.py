"""Tests for reporters/_markdown_escape.py."""

from __future__ import annotations

from linksanity.reporters._markdown_escape import escape_plain, wrap_code_span


class TestWrapCodeSpan:
    def test_plain_text_unchanged_wrapping(self) -> None:
        assert wrap_code_span("plain") == "`plain`"

    def test_pipe_escaped(self) -> None:
        assert wrap_code_span("a|b") == "`a\\|b`"

    def test_lf_becomes_br(self) -> None:
        assert wrap_code_span("a\nb") == "`a<br>b`"

    def test_crlf_becomes_br(self) -> None:
        assert wrap_code_span("a\r\nb") == "`a<br>b`"

    def test_backslash_not_doubled(self) -> None:
        # Regression: code-span content is always literal in CommonMark, so
        # doubling backslashes shows up as visible doubled backslashes
        # (e.g. a Windows path). See linksanity-n7o follow-up.
        assert wrap_code_span("docs\\win\\path.md") == "`docs\\win\\path.md`"

    def test_single_backtick_content_gets_longer_fence(self) -> None:
        # A single backtick would close a single-backtick fence early;
        # the fence must be at least 2 backticks, with padding spaces.
        assert wrap_code_span("`") == "`` ` ``"

    def test_triple_backtick_content_gets_four_backtick_fence(self) -> None:
        assert wrap_code_span("```") == "```` ``` ````"

    def test_backtick_breakout_cannot_close_span_early(self) -> None:
        # Regression: a backtick inside a URL used to close the previous
        # fixed single-backtick fence early, letting a trailing
        # "[text](url)" render as a live Markdown link outside the code
        # span. See linksanity-n7o follow-up (link injection).
        payload = "https://e.example/x`[CLICK-ME](https://evil.example)`"
        result = wrap_code_span(payload)
        # The payload's longest backtick run is 1, so the fence must be 2
        # backticks -- long enough that none of the payload's own single
        # backticks can act as a closing delimiter. The payload ends with a
        # backtick, so a padding space is added on both sides.
        assert result == f"`` {payload} ``"
        assert result.count("``") == 2  # only the opening and closing fence

    def test_empty_string(self) -> None:
        assert wrap_code_span("") == "``"


class TestEscapePlain:
    def test_plain_text_unchanged(self) -> None:
        assert escape_plain("plain text") == "plain text"

    def test_escapes_backslash(self) -> None:
        assert escape_plain("a\\b") == "a\\\\b"

    def test_escapes_pipe(self) -> None:
        assert escape_plain("a|b") == "a\\|b"

    def test_lf_becomes_br(self) -> None:
        assert escape_plain("a\nb") == "a<br>b"

    def test_escapes_backtick(self) -> None:
        assert escape_plain("a`b") == "a\\`b"

    def test_escapes_square_brackets(self) -> None:
        assert escape_plain("a[b]c") == "a\\[b\\]c"

    def test_escapes_parens(self) -> None:
        assert escape_plain("a(b)c") == "a\\(b\\)c"

    def test_escapes_angle_bracket(self) -> None:
        assert escape_plain("a<b") == "a\\<b"

    def test_link_syntax_neutralized(self) -> None:
        # Regression: a bare (unwrapped) Detail cell let attacker-influenced
        # error text render as a live Markdown link. See linksanity-n7o
        # follow-up (link injection).
        escaped = escape_plain("failed: [CLICK-ME](https://evil.example)")
        assert escaped == "failed: \\[CLICK-ME\\]\\(https://evil.example\\)"

    def test_raw_html_tag_neutralized(self) -> None:
        # Regression: a bare Detail cell let attacker-influenced error text
        # pass through a raw HTML tag opener. See linksanity-n7o follow-up.
        escaped = escape_plain("<img src=x onerror=alert(1)>")
        assert escaped.startswith("\\<img")
        assert "onerror=alert\\(1\\)" in escaped

    def test_backslash_escaped_before_others_no_double_escape(self) -> None:
        # A literal "\|" in the input should become "\\\|" -- the backslash
        # and the pipe are each escaped once, in an order that doesn't let
        # the pipe's own escaping backslash get re-escaped.
        assert escape_plain("\\|") == "\\\\\\|"
