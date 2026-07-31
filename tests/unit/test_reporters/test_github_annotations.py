"""Tests for reporters/github_annotations.py."""

from __future__ import annotations

import io

import pytest

from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.github_annotations import _esc, _esc_prop, _line_for, report


def _result(
    status: LinkStatus = LinkStatus.BROKEN,
    url: str = "https://gone.example.com",
    source_file: str = "docs/index.md",
    line: int = 1,
    http_code: int | None = 404,
    error: str | None = None,
    **kwargs: object,
) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=status,
        http_code=http_code,
        error=error,
        **kwargs,  # type: ignore[arg-type]
    )


# ── _esc / _esc_prop ──────────────────────────────────────────────────────────

class TestEsc:
    def test_escapes_percent(self) -> None:
        assert _esc("100%") == "100%25"

    def test_escapes_cr(self) -> None:
        assert _esc("a\rb") == "a%0Db"

    def test_escapes_lf(self) -> None:
        assert _esc("a\nb") == "a%0Ab"

    def test_no_escaping_needed(self) -> None:
        assert _esc("plain text") == "plain text"


class TestEscProp:
    def test_escapes_comma(self) -> None:
        assert _esc_prop("a,b") == "a%2Cb"

    def test_escapes_colon(self) -> None:
        assert _esc_prop("a:b") == "a%3Ab"

    def test_escapes_message_chars_too(self) -> None:
        assert _esc_prop("100%\n") == "100%25%0A"


# ── _line_for ─────────────────────────────────────────────────────────────────

class TestLineFor:
    def test_broken_status_is_error_level(self) -> None:
        assert _line_for(_result(LinkStatus.BROKEN)).startswith("::error ")

    def test_error_status_is_error_level(self) -> None:
        assert _line_for(_result(LinkStatus.ERROR)).startswith("::error ")

    def test_redirect_status_is_warning_level(self) -> None:
        assert _line_for(_result(LinkStatus.REDIRECT)).startswith("::warning ")

    def test_too_many_redirects_is_error_level(self) -> None:
        # A redirect loop never resolves, so it's an error, not a warning —
        # same treatment as BROKEN/ERROR (see FAILING_STATUSES in queue.py).
        assert _line_for(_result(LinkStatus.TOO_MANY_REDIRECTS)).startswith("::error ")

    def test_includes_file_and_line_properties(self) -> None:
        line = _line_for(_result(source_file="docs/a.md", line=42))
        assert "file=docs/a.md" in line
        assert "line=42" in line

    def test_includes_title(self) -> None:
        assert "title=linksanity" in _line_for(_result())

    def test_message_uses_error_when_present(self) -> None:
        line = _line_for(_result(error="connection refused", http_code=None))
        assert "connection refused" in line

    def test_message_uses_http_code_when_no_error(self) -> None:
        line = _line_for(_result(error=None, http_code=404))
        assert "HTTP 404" in line

    def test_message_uses_unreachable_when_no_error_or_code(self) -> None:
        line = _line_for(_result(error=None, http_code=None))
        assert "unreachable" in line

    def test_message_includes_url(self) -> None:
        line = _line_for(_result(url="https://gone.example.com"))
        assert "https://gone.example.com" in line


# ── report() ──────────────────────────────────────────────────────────────────

class TestReport:
    def test_ignored_statuses_produce_no_output(self) -> None:
        buf = io.StringIO()
        report([_result(LinkStatus.OK), _result(LinkStatus.SKIPPED)], file=buf)
        assert buf.getvalue() == ""

    def test_broken_emits_error_line(self) -> None:
        buf = io.StringIO()
        report([_result(LinkStatus.BROKEN)], file=buf)
        assert buf.getvalue().startswith("::error ")

    def test_redirect_emits_warning_line(self) -> None:
        buf = io.StringIO()
        report([_result(LinkStatus.REDIRECT)], file=buf)
        assert buf.getvalue().startswith("::warning ")

    def test_mixed_statuses_filtered(self) -> None:
        buf = io.StringIO()
        report(
            [
                _result(LinkStatus.OK),
                _result(LinkStatus.BROKEN),
                _result(LinkStatus.SKIPPED),
                _result(LinkStatus.REDIRECT),
            ],
            file=buf,
        )
        assert len(buf.getvalue().splitlines()) == 2

    def test_more_than_max_per_level_truncates_with_notice(self) -> None:
        buf = io.StringIO()
        results = [
            _result(LinkStatus.BROKEN, url=f"https://gone{i}.example.com") for i in range(15)
        ]
        report(results, file=buf)
        lines = buf.getvalue().splitlines()
        error_lines = [ln for ln in lines if ln.startswith("::error ")]
        notice_lines = [ln for ln in lines if ln.startswith("::notice")]
        assert len(error_lines) == 10
        assert len(notice_lines) == 1
        assert "5" in notice_lines[0]

    def test_exactly_max_per_level_no_notice(self) -> None:
        buf = io.StringIO()
        results = [
            _result(LinkStatus.BROKEN, url=f"https://gone{i}.example.com") for i in range(10)
        ]
        report(results, file=buf)
        lines = buf.getvalue().splitlines()
        assert len(lines) == 10
        assert not any(ln.startswith("::notice") for ln in lines)

    def test_error_and_warning_levels_truncate_independently(self) -> None:
        buf = io.StringIO()
        errors = [_result(LinkStatus.BROKEN, url=f"https://e{i}.example.com") for i in range(12)]
        warnings = [
            _result(LinkStatus.REDIRECT, url=f"https://w{i}.example.com") for i in range(11)
        ]
        report(errors + warnings, file=buf)
        lines = buf.getvalue().splitlines()
        error_lines = [ln for ln in lines if ln.startswith("::error ")]
        warning_lines = [ln for ln in lines if ln.startswith("::warning ")]
        notice_lines = [ln for ln in lines if ln.startswith("::notice")]
        assert len(error_lines) == 10
        assert len(warning_lines) == 10
        assert len(notice_lines) == 2

    def test_empty_results_no_output(self) -> None:
        buf = io.StringIO()
        report([], file=buf)
        assert buf.getvalue() == ""

    def test_defaults_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        report([_result(LinkStatus.BROKEN)])
        captured = capsys.readouterr()
        assert captured.out.startswith("::error ")


# ── Odd input never raises ───────────────────────────────────────────────────

class TestOddInput:
    def test_empty_url_does_not_raise(self) -> None:
        buf = io.StringIO()
        report([_result(url="")], file=buf)

    def test_none_http_code_and_error_does_not_raise(self) -> None:
        buf = io.StringIO()
        report([_result(http_code=None, error=None)], file=buf)

    def test_unicode_does_not_raise(self) -> None:
        buf = io.StringIO()
        report(
            [_result(url="https://example.com/André", source_file="docs/résumé.md")],
            file=buf,
        )
        assert "André" in buf.getvalue()

    def test_message_escapes_percent_and_newline(self) -> None:
        buf = io.StringIO()
        report([_result(error="timeout at 50%\ndone")], file=buf)
        assert "%25" in buf.getvalue()
        assert "%0A" in buf.getvalue()

    def test_source_file_with_comma_and_colon_escaped_in_property(self) -> None:
        buf = io.StringIO()
        report([_result(source_file="docs/a,b:c.md")], file=buf)
        assert "file=docs/a%2Cb%3Ac.md" in buf.getvalue()
