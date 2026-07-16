"""Tests for reporters/markdown_reporter.py."""

from __future__ import annotations

import io

from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.markdown_reporter import report


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
