"""Tests for reporters/github_reporter.py — all GitHub API calls mocked."""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx
from markdown_it import MarkdownIt

from linksanity._meta import HOMEPAGE_URL
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


# ── Footer link ────────────────────────────────────────────────────────────

class TestFooterLink:
    def test_body_footer_links_to_homepage(self) -> None:
        r = _result()
        body = _build_body([r])
        assert f"[linksanity]({HOMEPAGE_URL})" in body


# ── Pagination ─────────────────────────────────────────────────────────────
# Regression: _find_existing_issue only fetched page 1 (per_page=100), so in
# a repo with >100 open issues where the linksanity issue was not on page 1,
# it was never found and a duplicate issue was created every run. See
# linksanity-wfe.

def _issues_route(pages: dict[str, tuple[list[dict[str, object]], str | None]]):
    """Register a single route serving canned pages keyed by the `page` param.

    `pages` maps a page key (the request's `page` query param, or "1" for
    the first request with no `page` param) to a `(json_body, next_page_key)`
    tuple. `next_page_key=None` means no `Link: rel="next"` header.
    """

    def _callback(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        assert page in pages, f"unexpected page requested: {page!r}"
        body, next_page = pages[page]
        headers = {}
        if next_page is not None:
            headers["Link"] = (
                f'<{API}/repos/{REPO}/issues?page={next_page}>; rel="next"'
            )
        return httpx.Response(200, json=body, headers=headers)

    return respx.get(url__regex=rf".*/repos/{re.escape(REPO)}/issues.*").mock(
        side_effect=_callback
    )


class TestPagination:
    @respx.mock
    def test_match_on_page_3_is_found_and_updates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        route = _issues_route(
            {
                "1": ([{"number": 1, "title": "Unrelated 1"}], "2"),
                "2": ([{"number": 2, "title": "Unrelated 2"}], "3"),
                "3": (
                    [{"number": 7, "title": "[linksanity] 1 broken link(s) found"}],
                    None,
                ),
            }
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        patched = respx.patch(f"{API}/repos/{REPO}/issues/7").mock(
            return_value=httpx.Response(200, json={"number": 7})
        )
        report([_result()], _config())
        assert patched.called
        assert not created.called
        assert route.call_count == 3

    @respx.mock
    def test_match_on_page_1_issues_no_page_2_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        route = _issues_route(
            {
                "1": (
                    [{"number": 7, "title": "[linksanity] 1 broken link(s) found"}],
                    "2",
                ),
                "2": ([{"number": 8, "title": "Unrelated"}], None),
            }
        )
        respx.patch(f"{API}/repos/{REPO}/issues/7").mock(
            return_value=httpx.Response(200, json={"number": 7})
        )
        report([_result()], _config())
        assert route.call_count == 1

    @respx.mock
    def test_cap_exhaustion_warns_on_stderr_and_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        # 11 pages, one more than the _MAX_PAGES cap of 10, none matching.
        pages = {
            str(n): ([{"number": n, "title": f"Unrelated {n}"}], str(n + 1) if n < 11 else None)
            for n in range(1, 12)
        }
        route = _issues_route(pages)
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        report([_result()], _config())
        assert created.called
        assert route.call_count == 10
        err = capsys.readouterr().err
        assert "truncat" in err.lower() or "gave up" in err.lower()
        assert "duplicate" in err.lower()

    @respx.mock
    def test_pull_request_titled_linksanity_is_not_matched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        pr_and_issue = [
            {
                "number": 3,
                "title": "[linksanity] 1 broken link(s) found",
                "pull_request": {"url": f"{API}/repos/{REPO}/pulls/3"},
            },
        ]
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=pr_and_issue)
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        report([_result()], _config())
        assert created.called

    @respx.mock
    def test_pull_request_and_real_issue_same_page_matches_the_issue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression guard: the PR-skipping fixture above (`pr_and_issue`)
        # only ever contained a PR, so a real issue sharing the same page
        # was never exercised. A naive "return on first pull_request entry"
        # implementation would incorrectly skip past a genuine match here.
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        pr_and_real_issue = [
            {
                "number": 3,
                "title": "[linksanity] 1 broken link(s) found",
                "pull_request": {"url": f"{API}/repos/{REPO}/pulls/3"},
            },
            {"number": 7, "title": "[linksanity] 1 broken link(s) found"},
        ]
        respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=pr_and_real_issue)
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        patched = respx.patch(f"{API}/repos/{REPO}/issues/7").mock(
            return_value=httpx.Response(200, json={"number": 7})
        )
        report([_result()], _config())
        assert patched.called
        assert not created.called

    @respx.mock
    def test_malformed_link_header_terminates_cleanly_as_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A malformed `Link` header (no `rel="next"` entry httpx can parse)
        # must not raise and must not cause the loop to spin; it should be
        # treated the same as "no next page" and fall through to creation.
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        route = respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[{"number": 1, "title": "Unrelated"}],
                headers={"Link": "garbage; not a real link header, no brackets"},
            )
        )
        created = respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        report([_result()], _config())
        assert created.called
        assert route.call_count == 1

    @respx.mock
    def test_request_carries_sort_updated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        route = respx.get(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post(f"{API}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(201, json={"number": 99})
        )
        report([_result()], _config())
        assert route.calls[0].request.url.params["sort"] == "updated"
        assert route.calls[0].request.url.params["direction"] == "desc"

    @respx.mock
    def test_updated_issue_patch_has_refreshed_title_and_body(
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
        report(
            [_result(), _result(url="https://other.example.com")], _config()
        )
        payload = json.loads(patched.calls[0].request.content)
        assert payload["title"] == "[linksanity] 2 broken link(s) found"
        assert "2" in payload["title"]
        assert "body" in payload

    @respx.mock
    def test_non_2xx_on_later_page_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

        def _callback(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(
                    200,
                    json=[{"number": 1, "title": "Unrelated"}],
                    headers={"Link": f'<{API}/repos/{REPO}/issues?page=2>; rel="next"'},
                )
            return httpx.Response(500, json={"message": "boom"})

        respx.get(url__regex=rf".*/repos/{re.escape(REPO)}/issues.*").mock(
            side_effect=_callback
        )
        with pytest.raises(httpx.HTTPStatusError):
            report([_result()], _config())
