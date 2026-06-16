"""Tests for reporters/github_reporter.py — all GitHub API calls mocked."""

from __future__ import annotations

import httpx
import pytest
import respx

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


def _result(
    status: LinkStatus = LinkStatus.BROKEN,
    url: str = "https://gone.example.com",
    source_file: str = "docs/index.md",
    line: int = 1,
    http_code: int | None = 404,
) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=status,
        http_code=http_code,
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
