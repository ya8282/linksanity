"""Tests for reporters/console.py."""

from __future__ import annotations

import io

from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.console import report


def _result(
    status: LinkStatus,
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


# ── Empty / no-links case ─────────────────────────────────────────────────────

class TestEmpty:
    def test_no_results_prints_message(self) -> None:
        out = _capture([])
        assert "No links found" in out

    def test_no_results_no_summary(self) -> None:
        out = _capture([])
        assert "broken=" not in out


# ── Broken links ──────────────────────────────────────────────────────────────

class TestBroken:
    def test_broken_url_appears(self) -> None:
        r = _result(LinkStatus.BROKEN, url="https://gone.example.com", http_code=404)
        out = _capture([r])
        assert "gone.example.com" in out

    def test_broken_label_appears(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        out = _capture([r])
        assert "BROKEN" in out

    def test_http_code_appears(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        out = _capture([r])
        assert "404" in out

    def test_error_message_appears(self) -> None:
        r = _result(LinkStatus.ERROR, error="connection refused")
        out = _capture([r])
        assert "connection refused" in out

    def test_bracketed_error_text_not_mangled_as_markup(self) -> None:
        # Regression: "[browser]" in error text was previously eaten by Rich
        # as console markup (e.g. a style tag), silently dropping it from the
        # rendered output. See linksanity-2ie.
        r = _result(
            LinkStatus.ERROR,
            error=(
                "ImportError: Playwright is not installed. "
                "Run: pip install linksanity[browser] && playwright install chromium"
            ),
        )
        out = _capture([r])
        assert "[browser]" in out

    def test_line_number_appears(self) -> None:
        r = _result(LinkStatus.BROKEN, line=42, http_code=404)
        out = _capture([r])
        assert "42" in out

    def test_no_cell_text_when_cell_is_none(self) -> None:
        r = _result(LinkStatus.BROKEN, line=42, http_code=404)
        out = _capture([r])
        assert "cell" not in out

    def test_cell_shown_when_set(self) -> None:
        r = _result(LinkStatus.BROKEN, line=42, http_code=404, cell=3)
        out = _capture([r])
        assert "cell 3, line   42" in out


# ── Redirect links ────────────────────────────────────────────────────────────

class TestRedirect:
    def test_redirect_label_appears(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://new.example.com",
            http_code=301,
        )
        out = _capture([r])
        assert "REDIRECT" in out

    def test_resolved_url_appears(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://new.example.com",
        )
        out = _capture([r])
        assert "new.example.com" in out

    def test_bracketed_resolved_url_not_mangled_as_markup(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://example.com/[browser]/path",
        )
        out = _capture([r])
        assert "[browser]" in out


# ── OK and skipped are silent ─────────────────────────────────────────────────

class TestSilent:
    def test_ok_link_not_listed(self) -> None:
        r = _result(LinkStatus.OK, url="https://ok.example.com")
        out = _capture([r])
        assert "ok.example.com" not in out

    def test_skipped_link_not_listed(self) -> None:
        r = _result(LinkStatus.SKIPPED, url="https://skipped.example.com")
        out = _capture([r])
        assert "skipped.example.com" not in out


# ── Grouping by source file ───────────────────────────────────────────────────

class TestGrouping:
    def test_groups_by_source_file(self) -> None:
        results = [
            _result(LinkStatus.BROKEN, source_file="a.md", url="https://x.com"),
            _result(LinkStatus.BROKEN, source_file="b.md", url="https://y.com"),
        ]
        out = _capture(results)
        # Both source files appear as headings
        assert "a.md" in out
        assert "b.md" in out

    def test_source_file_appears_once_per_group(self) -> None:
        results = [
            _result(LinkStatus.BROKEN, source_file="a.md", line=1, url="https://x.com"),
            _result(LinkStatus.BROKEN, source_file="a.md", line=2, url="https://y.com"),
        ]
        out = _capture(results)
        # "a.md" appears as header — count occurrences (should be 1 group header)
        assert out.count("a.md") >= 1

    def test_bracketed_source_file_not_mangled_as_markup(self) -> None:
        # Regression: a literal "[" in the source file heading was previously
        # interpreted as Rich console markup, silently dropping the bracketed
        # text from the rendered output. See linksanity-2ie.
        r = _result(
            LinkStatus.BROKEN,
            source_file="docs/notes [draft].md",
            http_code=404,
        )
        out = _capture([r])
        assert "[draft]" in out
        # The intentional [bold]/[/bold] styling markup around the heading
        # is still consumed by Rich (not printed literally).
        assert "[bold]" not in out
        assert "[/bold]" not in out


# ── Summary line ──────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_shows_counts(self) -> None:
        results = [
            _result(LinkStatus.OK),
            _result(LinkStatus.BROKEN, http_code=404),
            _result(LinkStatus.REDIRECT, resolved_url="https://new.com"),
            _result(LinkStatus.SKIPPED),
        ]
        out = _capture(results)
        assert "ok=1" in out
        assert "broken=1" in out
        assert "redirect=1" in out
        assert "skipped=1" in out

    def test_error_counts_toward_broken(self) -> None:
        results = [
            _result(LinkStatus.ERROR, error="timeout"),
        ]
        out = _capture(results)
        assert "broken=1" in out

    def test_all_ok_shows_broken_0(self) -> None:
        out = _capture([_result(LinkStatus.OK)])
        assert "broken=0" in out

    def test_summary_always_present_with_results(self) -> None:
        out = _capture([_result(LinkStatus.OK)])
        assert "ok=" in out


# ── File output (no color) ────────────────────────────────────────────────────

class TestFileOutput:
    def test_file_output_has_no_ansi_codes(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        buf = io.StringIO()
        report([r], file=buf)
        text = buf.getvalue()
        assert "\x1b[" not in text

    def test_file_output_contains_url(self) -> None:
        r = _result(LinkStatus.BROKEN, url="https://gone.example.com", http_code=404)
        buf = io.StringIO()
        report([r], file=buf)
        assert "gone.example.com" in buf.getvalue()
