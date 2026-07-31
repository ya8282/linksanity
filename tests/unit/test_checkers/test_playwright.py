"""Unit tests for checkers/playwright.py check() — browser mocked, no real launch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# These tests mock the browser but still need the `playwright` package importable
# (patch targets + `from playwright.async_api import ...` inside check()). The
# no-browser CI job installs without the `browser` extra, so skip there; the
# test-browser job runs them.
pytest.importorskip("playwright")

from playwright.async_api import Error as PlaywrightError

from linksanity.checkers.playwright import check, crawl_page
from linksanity.fixer import build_redirect_proposals, is_permanent_redirect
from linksanity.queue import LinkQueue, LinkStatus, LinkType

URL = "https://example.com/page"


def _build_mock_response(
    status: int | None,
    redirect_hops: list[tuple[str, int | None]] | None,
) -> MagicMock | None:
    """Build the `response` object returned by `page.goto()`.

    `redirect_hops` models Playwright's `request.redirected_from` linked list:
    a list of (hop_url, hop_status) in request order (oldest hop first).
    `hop_status=None` models a hop whose `request.response()` resolves to
    `None` (status genuinely unknown). Omit / pass `None` for the no-redirect
    case.
    """
    if status is None:
        return None

    response = MagicMock()
    response.status = status

    if redirect_hops:
        requests = []
        for hop_url, hop_status in redirect_hops:
            hop_request = MagicMock()
            hop_request.url = hop_url
            if hop_status is None:
                hop_request.response = AsyncMock(return_value=None)
            else:
                hop_response = MagicMock()
                hop_response.status = hop_status
                hop_request.response = AsyncMock(return_value=hop_response)
            requests.append(hop_request)
        # requests is oldest-first; redirected_from walks newest -> oldest.
        for i, req in enumerate(requests):
            req.redirected_from = requests[i - 1] if i > 0 else None
        response.request.redirected_from = requests[-1]
    else:
        response.request.redirected_from = None

    return response


def _mock_playwright_context(
    status: int | None = 200,
    resolved_url: str = URL,
    *,
    redirect_hops: list[tuple[str, int | None]] | None = None,
) -> AsyncMock:
    """Build a mock async_playwright() context returning a fake browser/page/response.

    See `_build_mock_response` for `redirect_hops`.
    """
    response = _build_mock_response(status, redirect_hops)

    page = AsyncMock()
    page.goto = AsyncMock(return_value=response)
    page.url = resolved_url

    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = MagicMock()
    pw.chromium = chromium

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=pw)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_crawl_context(
    status: int | None = 200,
    resolved_url: str = URL,
    *,
    redirect_hops: list[tuple[str, int | None]] | None = None,
    hrefs: list[str] | None = None,
    ids: list[str] | None = None,
) -> AsyncMock:
    """Like `_mock_playwright_context`, plus the extra mocks `crawl_page` needs:
    `page.wait_for_load_state` and two `page.eval_on_selector_all` calls
    (hrefs, then element ids) when the page is reachable.
    """
    response = _build_mock_response(status, redirect_hops)

    page = AsyncMock()
    page.goto = AsyncMock(return_value=response)
    page.url = resolved_url
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.eval_on_selector_all = AsyncMock(side_effect=[hrefs or [], ids or []])

    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = MagicMock()
    pw.chromium = chromium

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=pw)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestCheckCellForwarding:
    @pytest.mark.asyncio
    async def test_cell_set_on_ok_result(self) -> None:
        ctx = _mock_playwright_context(status=200, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=3)
        assert result.status == LinkStatus.OK
        assert result.cell == 3

    @pytest.mark.asyncio
    async def test_cell_set_on_no_response_result(self) -> None:
        ctx = _mock_playwright_context(status=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=7)
        assert result.status == LinkStatus.ERROR
        assert result.error == "no response"
        assert result.cell == 7

    @pytest.mark.asyncio
    async def test_cell_set_on_broken_result(self) -> None:
        ctx = _mock_playwright_context(status=404, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=5)
        assert result.status == LinkStatus.BROKEN
        assert result.cell == 5

    @pytest.mark.asyncio
    async def test_cell_defaults_to_none(self) -> None:
        ctx = _mock_playwright_context(status=200, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.cell is None


class TestCheckRedirectDetection:
    """`page.url` differing from the requested URL is not itself a redirect —
    only `response.request.redirected_from` (a real navigation-level redirect)
    is. Mirrors the http.py `history`-based fix for the same defect."""

    @pytest.mark.asyncio
    async def test_url_normalization_alone_is_not_a_redirect(self) -> None:
        # page.url comes back lowercased/normalized with zero real redirects.
        ctx = _mock_playwright_context(status=200, resolved_url=URL, redirect_hops=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check("https://EXAMPLE.com/page", "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert result.redirect_chain is None
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    async def test_genuine_redirect_is_still_detected(self) -> None:
        final_url = "https://example.com/canonical"
        ctx = _mock_playwright_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, 301)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.REDIRECT
        assert result.resolved_url == final_url


class TestRedirectChainAndCodes:
    """linksanity-f8t: check() must populate redirect_chain/redirect_codes so
    is_permanent_redirect (fixer.py) can tell a 301 from a 302."""

    @pytest.mark.asyncio
    async def test_single_301_hop_is_permanent(self) -> None:
        final_url = "https://example.com/canonical"
        ctx = _mock_playwright_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, 301)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.redirect_chain == [URL, final_url]
        assert result.redirect_codes == [301]
        assert is_permanent_redirect(result) is True

    @pytest.mark.asyncio
    async def test_multi_hop_chain_with_mixed_codes_is_not_permanent(self) -> None:
        hop_a = "https://example.com/a"
        hop_b = "https://example.com/b"
        final_url = "https://example.com/c"
        ctx = _mock_playwright_context(
            status=200,
            resolved_url=final_url,
            redirect_hops=[(hop_a, 301), (hop_b, 302)],
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(hop_a, "f", 1, LinkType.EXTERNAL)
        assert result.redirect_chain == [hop_a, hop_b, final_url]
        assert result.redirect_codes == [301, 302]
        assert is_permanent_redirect(result) is False

    @pytest.mark.asyncio
    async def test_no_redirect_chain_and_codes_stay_none(self) -> None:
        ctx = _mock_playwright_context(status=200, resolved_url=URL, redirect_hops=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.OK
        assert result.redirect_chain is None
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    async def test_hop_with_unknown_status_reports_none_not_a_guess(self) -> None:
        """A hop whose `request.response()` resolves to None means its status
        code is genuinely unknown. We must not fabricate a code (e.g. assume
        200) or silently drop the hop, since a wrong code could make
        is_permanent_redirect auto-apply a rewrite based on a guess. We fall
        back to reporting the whole result as chain=None, codes=None — the
        same "temporary redirect" behaviour as before this fix."""
        final_url = "https://example.com/canonical"
        ctx = _mock_playwright_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, None)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.REDIRECT
        assert result.resolved_url == final_url
        assert result.redirect_chain is None
        assert result.redirect_codes is None
        assert is_permanent_redirect(result) is False

    @pytest.mark.asyncio
    async def test_end_to_end_301_redirect_is_auto_applicable_not_temporary(self) -> None:
        """Headline regression test for linksanity-f8t: a genuine 301 --js
        redirect must render as an auto-applicable permanent proposal, not the
        '(temporary redirect, use --redirects all to apply)' string."""
        final_url = "https://example.com/canonical"
        ctx = _mock_playwright_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, 301)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "docs/guide.md", 1, LinkType.EXTERNAL)

        queue = LinkQueue()
        queue.add(URL, "docs/guide.md", 1, LinkType.EXTERNAL)
        queue.record(result)

        proposals = build_redirect_proposals(queue.results(), queue)
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.auto_applicable is True
        assert "temporary redirect" not in proposal.detail
        assert proposal.detail == "301 → https://example.com/canonical"


class TestCrawlPageRedirectChainAndCodes:
    """Same defect, same fix, for the crawl_page() code path."""

    @pytest.mark.asyncio
    async def test_single_301_hop_is_permanent(self) -> None:
        final_url = "https://example.com/canonical"
        ctx = _mock_crawl_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, 301)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.REDIRECT
        assert result.redirect_chain == [URL, final_url]
        assert result.redirect_codes == [301]
        assert is_permanent_redirect(result) is True

    @pytest.mark.asyncio
    async def test_no_redirect_chain_and_codes_stay_none(self) -> None:
        ctx = _mock_crawl_context(status=200, resolved_url=URL, redirect_hops=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.OK
        assert result.redirect_chain is None
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    async def test_hop_with_unknown_status_reports_none_not_a_guess(self) -> None:
        final_url = "https://example.com/canonical"
        ctx = _mock_crawl_context(
            status=200, resolved_url=final_url, redirect_hops=[(URL, None)]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.REDIRECT
        assert result.redirect_chain is None
        assert result.redirect_codes is None
        assert is_permanent_redirect(result) is False


class TestCrawlPageStatusClassificationAndExtraction:
    """crawl_page()'s own status classification (linksanity-yvh) — the
    BROKEN/OK/ERROR branches and the extraction guard around them, distinct
    from the redirect-chain/codes coverage above."""

    @pytest.mark.asyncio
    async def test_no_response_reports_error_and_skips_extraction(self) -> None:
        # hrefs/ids are non-empty here so that, combined with the
        # assert_not_called() below, this test actually fails if the
        # extraction-skip guard is removed (an empty-list default would make
        # `links == []` / `ids == set()` pass regardless of whether
        # extraction ran).
        ctx = _mock_crawl_context(status=None, hrefs=["https://example.com/a"], ids=["main"])
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.ERROR
        assert result.error == "no response"
        assert links == []
        assert ids == set()
        page = ctx.__aenter__.return_value.chromium.launch.return_value.new_page.return_value
        page.eval_on_selector_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_playwright_error_reports_error_and_skips_extraction(self) -> None:
        # Non-empty hrefs/ids + assert_not_called() below: see comment on
        # test_no_response_reports_error_and_skips_extraction.
        ctx = _mock_crawl_context(
            status=200, resolved_url=URL, hrefs=["https://example.com/a"], ids=["main"]
        )
        pw = ctx.__aenter__.return_value
        browser = pw.chromium.launch.return_value
        page = browser.new_page.return_value
        page.goto.side_effect = PlaywrightError("boom")
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.ERROR
        assert result.error == "boom"
        assert links == []
        assert ids == set()
        page.eval_on_selector_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_broken_status_skips_extraction(self) -> None:
        # Non-empty hrefs/ids + assert_not_called() below: see comment on
        # test_no_response_reports_error_and_skips_extraction.
        ctx = _mock_crawl_context(
            status=404, resolved_url=URL, hrefs=["https://example.com/a"], ids=["main"]
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.BROKEN
        assert result.resolved_url is None
        assert links == []
        assert ids == set()
        page = ctx.__aenter__.return_value.chromium.launch.return_value.new_page.return_value
        page.eval_on_selector_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_ok_status_extracts_links_and_ids(self) -> None:
        ctx = _mock_crawl_context(
            status=200,
            resolved_url=URL,
            hrefs=["https://example.com/a"],
            ids=["main"],
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert links == ["https://example.com/a"]
        assert ids == {"main"}

    @pytest.mark.asyncio
    async def test_redirect_extracts_links_and_sets_resolved_url(self) -> None:
        final_url = "https://example.com/canonical"
        ctx = _mock_crawl_context(
            status=200,
            resolved_url=final_url,
            redirect_hops=[(URL, 301)],
            hrefs=["https://example.com/x"],
            ids=["footer"],
        )
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.REDIRECT
        assert result.resolved_url == final_url
        assert links == ["https://example.com/x"]
        assert ids == {"footer"}


class TestCrawlPageClientSideRedirectIsNotFlagged:
    """linksanity-yvh: client-side redirects (meta-refresh, JS `location`
    changes) produce no `redirected_from` on the HTTP response, so they are
    deliberately reported as OK rather than REDIRECT — see the comment at
    crawl_page's `was_redirected` line for the reasoning. This pins that
    decision against a future "fix" that restores page.url comparison."""

    @pytest.mark.asyncio
    async def test_page_url_diverging_without_http_redirect_reports_ok(self) -> None:
        # Simulates a client-side redirect: the rendered page ends up at a
        # different page.url after JS/meta-refresh navigation, but the HTTP
        # response Playwright saw was never redirected (redirected_from=None).
        landed_url = "https://example.com/client-side-destination"
        ctx = _mock_crawl_context(status=200, resolved_url=landed_url, redirect_hops=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result, links, ids = await crawl_page(URL, "f", 1, LinkType.EXTERNAL)
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert result.redirect_chain is None
        assert result.redirect_codes is None
