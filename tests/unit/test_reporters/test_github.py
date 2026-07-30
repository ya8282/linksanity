"""Tests for reporters/github_reporter.py — all GitHub API calls mocked."""

from __future__ import annotations

import re

import httpx
import pytest
import respx
from markdown_it import MarkdownIt

from linksanity.config import Config
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.github_reporter import (
    _build_body,
    _find_existing_issue,
    report,
)

REPO = "owner/repo"
TOKEN = "ghp_test_token"
API = "https://api.github.com"
_MD = MarkdownIt("commonmark").enable("table")


def _result(
    status: LinkStatus = LinkStatus.BROKEN,
    url: str = "https://gone.example.com",
    source_file: str = "docs/index.md",
    line: int = 1,
    http_code: int | None = 404,
    cell: int | None = None,
    error: str | None = None,
) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=status,
        http_code=http_code,
        cell=cell,
        error=error,
    )


def _config(**kwargs: object) -> Config:
    return Config(github_issue=True, github_repo=REPO, **kwargs)  # type: ignore[arg-type]


# ── No broken links — no API call ────────────────────────────────────────────

class TestNoBroken:
    @respx.mock
    def test_no_broken_makes_no_api_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        # If any HTTP call is made, respx will raise because no routes are registered
        report([_result(LinkStatus.OK, http_code=None)], _config())


# ── Token validation ──────────────────────────────────────────────────────────

class TestTokenValidation:
    def test_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            report([_result()], _config())

    def test_empty_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "")
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            report([_result()], _config())


# ── Issue creation ─────────────────────────────────────────────────────────────

class TestIssueCreation:
    @respx.mock
    def test_creates_issue_when_none_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        # No existing issues
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 42})
        )
        report([_result()], _config())
        assert created.called

    @respx.mock
    def test_issue_title_contains_broken_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 1})
        )
        report([_result(), _result(url="https://other.example.com")], _config())
        payload = created.calls[0].request
        import json
        body = json.loads(payload.content)
        assert "[linksanity]" in body["title"]
        assert "2" in body["title"]


# ── Issue deduplication ────────────────────────────────────────────────────────

class TestDeduplication:
    @respx.mock
    def test_updates_existing_issue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        existing = [{"number": 7, "title": "[linksanity] 1 broken link(s) found"}]
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=existing)
        )
        patched = respx.patch(f"{API}/repos/{REPO}/issues/7").mock(
            return_value=httpx.Response(200, json={"number": 7})
        )
        report([_result()], _config())
        assert patched.called

    @respx.mock
    def test_does_not_create_when_existing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        existing = [{"number": 7, "title": "[linksanity] 1 broken link(s) found"}]
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=existing)
        )
        respx.patch(f"{API}/repos/{REPO}/issues/7").mock(
            return_value=httpx.Response(200, json={"number": 7})
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        report([_result()], _config())
        assert not created.called


# ── Body content ──────────────────────────────────────────────────────────────

class TestBodyContent:
    def test_body_contains_url(self) -> None:
        r = _result(url="https://gone.example.com")
        body = _build_body([r])
        assert "gone.example.com" in body

    def test_body_contains_source_file(self) -> None:
        r = _result(source_file="api/guide.md")
        body = _build_body([r])
        assert "api/guide.md" in body

    def test_body_contains_http_code(self) -> None:
        r = _result(http_code=404)
        body = _build_body([r])
        assert "404" in body

    def test_body_has_table_format(self) -> None:
        r = _result()
        body = _build_body([r])
        assert "|" in body  # Markdown table

    def test_no_cell_text_when_cell_is_none(self) -> None:
        r = _result(line=99)
        body = _build_body([r])
        assert "cell" not in body

    def test_cell_shown_when_set(self) -> None:
        r = _result(line=99, cell=3)
        body = _build_body([r])
        assert "cell 3, line 99" in body


# ── Body escaping ───────────────────────────────────────────────────────────────

class TestBodyEscaping:
    # Regression: attacker-influenced free-text fields (URLs, error messages
    # from third-party content) were interpolated into the issue body's
    # Markdown table without escaping. A "|" splits the cell/row; a raw
    # newline ends the row outright and corrupts the rest of the issue body.
    # See linksanity-n7o.

    def test_pipe_in_url_escaped(self) -> None:
        r = _result(
            url="https://gone.example.com/a|b",
            http_code=None,
            error="some error",
        )
        body = _build_body([r])
        assert "a\\|b" in body

    def test_pipe_in_error_escaped(self) -> None:
        r = _result(http_code=None, error="timeout | retrying")
        body = _build_body([r])
        assert "timeout \\| retrying" in body

    def test_newline_in_error_does_not_break_table(self) -> None:
        r = _result(http_code=None, error="first line\nsecond line")
        body = _build_body([r])
        assert "first line<br>second line" in body
        for line in body.splitlines():
            assert "first line" not in line or "second line" in line

    def test_pipe_in_source_file_escaped(self) -> None:
        r = _result(source_file="docs/a|b.md")
        body = _build_body([r])
        assert "a\\|b.md" in body

    def test_pipe_in_url_does_not_split_table_row(self) -> None:
        r = _result(url="https://gone.example.com/a|b", http_code=404)
        body = _build_body([r])
        row = next(line for line in body.splitlines() if "a\\|b" in line)
        unescaped_cells = re.split(r"(?<!\\)\|", row)
        assert len(unescaped_cells) == 6  # 4 columns -> 5 delimiters -> 6 split parts


# ── Body injection (link/HTML) ────────────────────────────────────────────────

class TestBodyInjection:
    # Regression: a backtick in a code-spanned free-text field (url,
    # source_file) could close the fixed single-backtick fence early,
    # letting trailing "[text](url)" markup escape the span and render as a
    # live link to an attacker-controlled domain inside a maintainer-facing
    # GitHub issue. The bare Detail cell had no code span at all, so no
    # breakout was even needed. See linksanity-n7o follow-up.

    def test_backtick_in_url_cannot_forge_live_link(self) -> None:
        r = _result(
            url="https://e.example/x`[CLICK-ME](https://evil.example)`",
            http_code=None,
            error="ok",
        )
        body = _build_body([r])
        html = _MD.render(body)
        # The only real link allowed to survive is the trusted static
        # footer link; the attacker-controlled domain must not appear as
        # an <a href>.
        assert 'href="https://evil.example"' not in html

    def test_backtick_in_source_file_cannot_forge_live_link(self) -> None:
        r = _result(source_file="docs/x`[CLICK-ME](https://evil.example)`.md")
        body = _build_body([r])
        html = _MD.render(body)
        assert 'href="https://evil.example"' not in html

    def test_link_syntax_in_bare_error_cell_not_rendered_as_link(self) -> None:
        r = _result(http_code=None, error="failed: [CLICK-ME](https://evil.example)")
        body = _build_body([r])
        html = _MD.render(body)
        assert 'href="https://evil.example"' not in html
        assert "[CLICK-ME](https://evil.example)" in html

    def test_raw_html_tag_in_bare_error_cell_not_rendered(self) -> None:
        r = _result(http_code=None, error="<img src=x onerror=alert(1)>")
        body = _build_body([r])
        html = _MD.render(body)
        assert "<img " not in html

    def test_ordinary_fixture_byte_identical_shape(self) -> None:
        r = _result(url="https://gone.example.com/path", source_file="api/guide.md")
        body = _build_body([r])
        assert "`https://gone.example.com/path`" in body
        assert "`api/guide.md`" in body
        assert "``" not in body


# ── _find_existing_issue helper ───────────────────────────────────────────────

class TestFindExistingIssue:
    @respx.mock
    def test_returns_none_when_no_linksanity_issues(self) -> None:
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[{"number": 1, "title": "Unrelated issue"}])
        )
        result = _find_existing_issue(TOKEN, REPO, "[linksanity] broken")
        assert result is None

    @respx.mock
    def test_returns_number_when_found(self) -> None:
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(
                200, json=[{"number": 5, "title": "[linksanity] 2 broken link(s) found"}]
            )
        )
        result = _find_existing_issue(TOKEN, REPO, "[linksanity] broken")
        assert result == 5
