"""Unit tests for crawler.py — Playwright and HTTP calls fully mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from linksanity.config import Config
from linksanity.crawler import _norm, run_crawl
from linksanity.queue import LinkResult, LinkStatus, LinkType

START = "http://example.com"


def _ok(url: str, links: list[str] | None = None) -> tuple[LinkResult, list[str]]:
    result = LinkResult(
        source_file=START, line=0, url=url,
        link_type=LinkType.EXTERNAL, status=LinkStatus.OK, http_code=200,
    )
    return result, links or []


def _broken(url: str) -> tuple[LinkResult, list[str]]:
    result = LinkResult(
        source_file=START, line=0, url=url,
        link_type=LinkType.EXTERNAL, status=LinkStatus.BROKEN, http_code=404,
    )
    return result, []


def _config(**kwargs: object) -> Config:
    defaults: dict[str, object] = {"timeout": 5, "retry": 0, "max_pages": 10}
    defaults.update(kwargs)
    return Config(**defaults)  # type: ignore[arg-type]


# ── Basic crawl ───────────────────────────────────────────────────────────────

class TestBasicCrawl:
    @pytest.mark.asyncio
    async def test_start_url_is_crawled(self) -> None:
        with patch("linksanity.crawler.crawl_page", new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = _ok(START)
            queue = await run_crawl(START, _config())
        results = queue.results()
        assert any(r.url == START for r in results)

    @pytest.mark.asyncio
    async def test_ok_page_recorded_as_ok(self) -> None:
        with patch("linksanity.crawler.crawl_page", new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = _ok(START)
            queue = await run_crawl(START, _config())
        assert queue.results()[0].status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_broken_page_recorded_as_broken(self) -> None:
        with patch("linksanity.crawler.crawl_page", new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = _broken(START)
            queue = await run_crawl(START, _config())
        assert queue.results()[0].status == LinkStatus.BROKEN


# ── BFS link discovery ─────────────────────────────────────────────────────────

class TestBFSDiscovery:
    @pytest.mark.asyncio
    async def test_same_domain_link_is_crawled(self) -> None:
        page2 = "http://example.com/page2"
        call_order: list[str] = []

        async def mock_crawl(url: str, *args: object, **kwargs: object) -> tuple[LinkResult, list[str]]:
            call_order.append(url)
            if url == START:
                return _ok(START, [page2])
            return _ok(page2)

        with patch("linksanity.crawler.crawl_page", side_effect=mock_crawl):
            await run_crawl(START, _config())

        assert page2 in call_order or any("page2" in u for u in call_order)

    @pytest.mark.asyncio
    async def test_external_link_not_crawled_via_playwright(self) -> None:
        external = "https://github.com/example"
        crawl_calls: list[str] = []

        async def mock_crawl(url: str, *args: object, **kwargs: object) -> tuple[LinkResult, list[str]]:
            crawl_calls.append(url)
            return _ok(START, [external])

        http_result = LinkResult(
            source_file=START, line=0, url=external,
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK, http_code=200,
        )
        with (
            patch("linksanity.crawler.crawl_page", side_effect=mock_crawl),
            patch("linksanity.crawler.http.check", new_callable=AsyncMock, return_value=http_result),
        ):
            await run_crawl(START, _config())

        assert external not in crawl_calls

    @pytest.mark.asyncio
    async def test_external_link_http_checked(self) -> None:
        external = "https://github.com/example"
        http_mock = AsyncMock(return_value=LinkResult(
            source_file=START, line=0, url=external,
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK, http_code=200,
        ))

        with (
            patch("linksanity.crawler.crawl_page", new_callable=AsyncMock,
                  return_value=_ok(START, [external])),
            patch("linksanity.crawler.http.check", http_mock),
        ):
            queue = await run_crawl(START, _config())

        http_mock.assert_called()
        assert any(r.url == external for r in queue.results())

    @pytest.mark.asyncio
    async def test_same_url_not_crawled_twice(self) -> None:
        page2 = "http://example.com/page2"
        call_count: dict[str, int] = {}

        async def mock_crawl(url: str, *args: object, **kwargs: object) -> tuple[LinkResult, list[str]]:
            call_count[url] = call_count.get(url, 0) + 1
            if url == START:
                return _ok(START, [page2, page2])  # duplicate link
            return _ok(page2, [START])  # links back

        with patch("linksanity.crawler.crawl_page", side_effect=mock_crawl):
            await run_crawl(START, _config())

        assert call_count.get(page2, 0) == 1


# ── max_pages limit ───────────────────────────────────────────────────────────

class TestMaxPages:
    @pytest.mark.asyncio
    async def test_max_pages_respected(self) -> None:
        visit_count = 0

        async def mock_crawl(url: str, *args: object, **kwargs: object) -> tuple[LinkResult, list[str]]:
            nonlocal visit_count
            visit_count += 1
            # Each page links to a new unique page
            next_page = f"http://example.com/page{visit_count}"
            return _ok(url, [next_page])

        with patch("linksanity.crawler.crawl_page", side_effect=mock_crawl):
            await run_crawl(START, _config(max_pages=3))

        assert visit_count <= 3


# ── Ignored domains ───────────────────────────────────────────────────────────

class TestIgnoreDomains:
    @pytest.mark.asyncio
    async def test_ignored_external_domain_skipped(self) -> None:
        external = "https://ignored.example.com/page"
        http_mock = AsyncMock(return_value=LinkResult(
            source_file=START, line=0, url=external,
            link_type=LinkType.EXTERNAL, status=LinkStatus.SKIPPED,
        ))

        with (
            patch("linksanity.crawler.crawl_page", new_callable=AsyncMock,
                  return_value=_ok(START, [external])),
            patch("linksanity.crawler.http.check", http_mock),
        ):
            queue = await run_crawl(START, _config(ignore_domains={"ignored.example.com"}))

        results = [r for r in queue.results() if r.url == external]
        assert results[0].status == LinkStatus.SKIPPED


# ── Exception handling ────────────────────────────────────────────────────────

class TestExceptionHandling:
    @pytest.mark.asyncio
    async def test_playwright_exception_recorded_as_error(self) -> None:
        with patch("linksanity.crawler.crawl_page", new_callable=AsyncMock,
                   side_effect=RuntimeError("browser crashed")):
            queue = await run_crawl(START, _config())
        assert queue.results()[0].status == LinkStatus.ERROR


# ── _norm helper ─────────────────────────────────────────────────────────────

class TestNorm:
    def test_strips_fragment(self) -> None:
        assert _norm("http://example.com/page#section") == "http://example.com/page"

    def test_strips_trailing_slash(self) -> None:
        assert _norm("http://example.com/page/") == "http://example.com/page"

    def test_preserves_path(self) -> None:
        assert "page" in _norm("http://example.com/page")
