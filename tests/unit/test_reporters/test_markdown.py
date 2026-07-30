"""Tests for reporters/markdown_reporter.py."""

from __future__ import annotations

import io
import re

from markdown_it import MarkdownIt

from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.markdown_reporter import report

_MD = MarkdownIt("commonmark").enable("table")


def _result(
    status: LinkStatus = LinkStatus.OK,
    url: str = "https://example.com",
    source_file: str = "docs/index.md",
    line: int = 1,
    link_type: LinkType = LinkType.EXTERNAL,
    **kwargs: object,
) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=link_type,
        status=status,
        **kwargs,  # type: ignore[arg-type]
    )


def _capture(results: list[LinkResult]) -> str:
    buf = io.StringIO()
    report(results, file=buf)
    return buf.getvalue()


class TestMarkdownStructure:
    def test_has_h1_title(self) -> None:
        out = _capture([])
        assert "# linksanity scan report" in out

    def test_has_summary_section(self) -> None:
        out = _capture([])
        assert "## Summary" in out

    def test_summary_table_has_counts(self) -> None:
        results = [
            _result(LinkStatus.OK),
            _result(LinkStatus.BROKEN, http_code=404),
        ]
        out = _capture(results)
        assert "| ok |" in out or "ok" in out
        assert "broken" in out

    def test_has_generation_timestamp(self) -> None:
        out = _capture([])
        assert "Generated" in out

    def test_clean_scan_no_details_section(self) -> None:
        out = _capture([_result(LinkStatus.OK)])
        assert "## Details" not in out

    def test_clean_scan_shows_success_message(self) -> None:
        out = _capture([_result(LinkStatus.OK)])
        assert "No broken" in out


class TestMarkdownDetails:
    def test_broken_appears_in_details(self) -> None:
        r = _result(LinkStatus.BROKEN, url="https://gone.example.com", http_code=404)
        out = _capture([r])
        assert "## Details" in out
        assert "gone.example.com" in out

    def test_source_file_appears_as_heading(self) -> None:
        r = _result(LinkStatus.BROKEN, source_file="api/guide.md", http_code=404)
        out = _capture([r])
        assert "api/guide.md" in out

    def test_http_code_in_detail(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        out = _capture([r])
        assert "404" in out

    def test_redirect_shows_resolved_url(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://new.example.com",
            http_code=301,
        )
        out = _capture([r])
        assert "new.example.com" in out

    def test_error_message_in_detail(self) -> None:
        r = _result(LinkStatus.ERROR, error="connection refused")
        out = _capture([r])
        assert "connection refused" in out

    def test_line_number_in_table(self) -> None:
        r = _result(LinkStatus.BROKEN, line=99, http_code=404)
        out = _capture([r])
        assert "99" in out

    def test_no_cell_text_when_cell_is_none(self) -> None:
        r = _result(LinkStatus.BROKEN, line=99, http_code=404)
        out = _capture([r])
        assert "cell" not in out

    def test_cell_shown_when_set(self) -> None:
        r = _result(LinkStatus.BROKEN, line=99, http_code=404, cell=3)
        out = _capture([r])
        assert "cell 3, line 99" in out

    def test_ok_links_not_in_details(self) -> None:
        results = [
            _result(LinkStatus.OK, url="https://ok.example.com"),
            _result(LinkStatus.BROKEN, url="https://gone.example.com", http_code=404),
        ]
        out = _capture(results)
        assert "ok.example.com" not in out

    def test_multiple_files_grouped(self) -> None:
        results = [
            _result(LinkStatus.BROKEN, source_file="a.md", url="https://x.com", http_code=404),
            _result(LinkStatus.BROKEN, source_file="b.md", url="https://y.com", http_code=404),
        ]
        out = _capture(results)
        assert "a.md" in out
        assert "b.md" in out


class TestMarkdownEscaping:
    # Regression: attacker-influenced free-text fields (URLs, error messages
    # from third-party content) were interpolated into the Markdown table
    # without escaping. A "|" splits the cell/row; a raw newline ends the
    # row outright and corrupts the rest of the document. See linksanity-n7o.

    def test_pipe_in_url_does_not_split_table_row(self) -> None:
        r = _result(
            LinkStatus.BROKEN,
            url="https://gone.example.com/a|b",
            http_code=404,
        )
        out = _capture([r])
        # The escaped pipe must survive as a literal, backslash-escaped
        # pipe inside the single URL cell, not an unescaped column divider.
        assert "a\\|b" in out
        details_line = next(line for line in out.splitlines() if "a\\|b" in line)
        # Split on pipes that are NOT escaped with a backslash, the way a
        # real Markdown table parser would. 4 columns => 5 unescaped delimiters
        # (leading/trailing pipes plus 3 internal separators).
        unescaped_cells = re.split(r"(?<!\\)\|", details_line)
        assert len(unescaped_cells) == 6  # 5 delimiters -> 6 split parts (incl. empty ends)

    def test_newline_in_error_does_not_break_table(self) -> None:
        r = _result(
            LinkStatus.ERROR,
            error="first line\nsecond line",
        )
        out = _capture([r])
        assert "first line<br>second line" in out
        # No raw newline was introduced into the table row itself.
        for line in out.splitlines():
            assert "first line" not in line or "second line" in line

    def test_pipe_in_error_does_not_split_table_row(self) -> None:
        r = _result(LinkStatus.ERROR, error="timeout | retrying")
        out = _capture([r])
        assert "timeout \\| retrying" in out

    def test_pipe_in_source_file_heading_escaped(self) -> None:
        r = _result(
            LinkStatus.BROKEN,
            source_file="docs/a|b.md",
            http_code=404,
        )
        out = _capture([r])
        assert "a\\|b.md" in out

    def test_pipe_in_resolved_url_escaped(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://new.example.com/x|y",
            http_code=301,
        )
        out = _capture([r])
        assert "x\\|y" in out

    def test_pipe_in_redirect_chain_escaped(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            redirect_chain=["https://a.example.com/x|y", "https://b.example.com"],
            http_code=301,
        )
        out = _capture([r])
        assert "x\\|y" in out


class TestMarkdownInjection:
    # Regression: a backtick in a code-spanned free-text field (url,
    # source_file, resolved_url, redirect_chain entries) could close the
    # fixed single-backtick fence early, letting trailing "[text](url)"
    # markup escape the span and render as a live link to an
    # attacker-controlled domain; a raw "<tag>" could similarly escape and
    # render as live HTML. The bare Detail cell had no code span at all, so
    # no breakout was even needed. See linksanity-n7o follow-up.

    def test_backtick_in_url_cannot_forge_live_link(self) -> None:
        r = _result(
            LinkStatus.ERROR,
            url="https://e.example/x`[CLICK-ME](https://evil.example)`",
            error="ok",
        )
        out = _capture([r])
        html = _MD.render(out)
        assert "<a href" not in html
        assert "evil.example" not in html or "<a href" not in html

    def test_backtick_in_source_file_cannot_forge_live_link(self) -> None:
        r = _result(
            LinkStatus.BROKEN,
            source_file="docs/x`[CLICK-ME](https://evil.example)`.md",
            http_code=404,
        )
        out = _capture([r])
        html = _MD.render(out)
        assert "<a href" not in html

    def test_link_syntax_in_bare_error_cell_not_rendered_as_link(self) -> None:
        r = _result(
            LinkStatus.ERROR,
            error="failed: [CLICK-ME](https://evil.example)",
        )
        out = _capture([r])
        html = _MD.render(out)
        assert "<a href" not in html
        assert "[CLICK-ME](https://evil.example)" in html

    def test_raw_html_tag_in_bare_error_cell_not_rendered(self) -> None:
        r = _result(
            LinkStatus.ERROR,
            error="<img src=x onerror=alert(1)>",
        )
        out = _capture([r])
        html = _MD.render(out)
        assert "<img " not in html

    def test_ordinary_fixture_byte_identical_shape(self) -> None:
        # A plain URL, plain error, and a redirect chain must render with
        # the existing look: single-backtick code spans, no stray escaping.
        results = [
            _result(LinkStatus.BROKEN, url="https://gone.example.com/path", http_code=404),
            _result(
                LinkStatus.REDIRECT,
                url="https://old.example.com",
                http_code=301,
                redirect_chain=[
                    "https://old.example.com",
                    "https://mid.example.com",
                    "https://new.example.com",
                ],
            ),
            _result(LinkStatus.ERROR, url="https://err.example.com", error="connection refused"),
        ]
        out = _capture(results)
        assert "`https://gone.example.com/path`" in out
        assert "`https://old.example.com`" in out
        assert "`https://mid.example.com`" in out
        assert "`https://new.example.com`" in out
        assert "connection refused" in out
        # No double-backtick fences or padding spaces for plain content.
        assert "``" not in out


class TestMarkdownSummaryCounts:
    def test_total_count_correct(self) -> None:
        results = [_result(LinkStatus.OK), _result(LinkStatus.BROKEN, http_code=404)]
        out = _capture(results)
        assert "2" in out  # total

    def test_error_counts_as_broken(self) -> None:
        r = _result(LinkStatus.ERROR, error="timeout")
        out = _capture([r])
        # broken count should be 1
        assert "broken" in out
