"""Integration tests for checkers/playwright.py — requires playwright[browser]."""

from __future__ import annotations

import asyncio
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from linksanity.checkers.playwright import check, extract_links, scope_filter
from linksanity.queue import LinkStatus, LinkType

SITE_DIR = Path(__file__).parent.parent / "fixtures" / "site"
pytest.importorskip("playwright", reason="playwright not installed — skipping")


def _start_server(port: int) -> HTTPServer:
    handler = lambda *a, **kw: SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(SITE_DIR), **kw
    )
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # brief settle
    return server


@pytest.fixture(scope="module")
def site_url() -> str:  # type: ignore[return]
    server = _start_server(18432)
    yield "http://127.0.0.1:18432"
    server.shutdown()


class TestExtractLinks:
    @pytest.mark.asyncio
    async def test_extracts_internal_and_external(self, site_url: str) -> None:
        links = await extract_links(f"{site_url}/index.html")
        # Internal link resolved to absolute by browser
        assert any("page2.html" in link for link in links)
        # External link
        assert any("external.example.com" in link for link in links)

    @pytest.mark.asyncio
    async def test_excludes_mailto(self, site_url: str) -> None:
        links = await extract_links(f"{site_url}/index.html")
        assert not any(link.startswith("mailto:") for link in links)

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, site_url: str) -> None:
        sem = asyncio.Semaphore(1)
        tasks = [
            extract_links(f"{site_url}/index.html", semaphore=sem)
            for _ in range(2)
        ]
        results = await asyncio.gather(*tasks)
        assert all(isinstance(r, list) for r in results)


class TestScopeFilter:
    def test_keeps_same_domain(self) -> None:
        urls = ["http://a.com/page", "http://b.com/page", "http://a.com/other"]
        filtered = scope_filter(urls, "http://a.com/start")
        assert filtered == ["http://a.com/page", "http://a.com/other"]

    def test_empty_input(self) -> None:
        assert scope_filter([], "http://a.com") == []


class TestCheckLink:
    @pytest.mark.asyncio
    async def test_existing_page_is_ok(self, site_url: str) -> None:
        result = await check(
            f"{site_url}/index.html", "test", 1, LinkType.EXTERNAL, timeout=10
        )
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_missing_page_is_broken(self, site_url: str) -> None:
        result = await check(
            f"{site_url}/missing.html", "test", 1, LinkType.EXTERNAL, timeout=10
        )
        assert result.status == LinkStatus.BROKEN
        assert result.http_code == 404

    @pytest.mark.asyncio
    async def test_pdf_download_falls_back_to_http_check(self, site_url: str) -> None:
        """Canary for the unpinned "Download is starting" substring match.

        Chromium turns navigation to a PDF into a download and Playwright
        raises an untyped error containing that exact wording;
        `_is_download_abort` substring-matches it to fall back to
        `http.check()`. There is no typed Playwright exception for this, so
        this test is the only thing that would catch Playwright rewording
        that message and silently regressing every downloadable URL to
        LinkStatus.ERROR. If this test fails, check whether Playwright's
        download-abort error text changed and update the substring in
        `_is_download_abort` accordingly.

        The fixture is served from 127.0.0.1, so a successful fallback into
        `http.check()` resolves to LinkStatus.SKIPPED (its private/loopback
        host guard fires before any request) rather than OK — that SKIPPED
        result, with this specific error message, is only reachable through
        the download-abort branch, so it's still an unambiguous signal that
        the fallback fired. If `_is_download_abort` stops matching, `check()`
        takes the other branch instead and returns LinkStatus.ERROR.
        """
        result = await check(
            f"{site_url}/downloadable.pdf", "test", 1, LinkType.EXTERNAL, timeout=10
        )
        assert result.status == LinkStatus.SKIPPED
        assert result.error == "skipped: private/loopback address"


class TestImportError:
    def test_missing_playwright_raises_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "playwright":
                raise ImportError("no playwright")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        from linksanity.checkers.playwright import _require_playwright
        with pytest.raises(ImportError, match="pip install linksanity"):
            _require_playwright()
