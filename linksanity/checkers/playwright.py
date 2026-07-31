"""Playwright-based link extractor and checker for JS-rendered pages."""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlparse

from linksanity.queue import LinkResult, LinkStatus, LinkType

_SKIP_SCHEMES = ("mailto:", "javascript:", "data:", "blob:")

# Well-known analytics and tracking domains. Requests to these are aborted
# when --block-analytics is set, speeding up crawls and suppressing false hits.
ANALYTICS_DOMAINS: frozenset[str] = frozenset({
    "google-analytics.com",
    "analytics.google.com",
    "googletagmanager.com",
    "googletagservices.com",
    "doubleclick.net",
    "hotjar.com",
    "segment.com",
    "cdn.segment.com",
    "api.segment.io",
    "mixpanel.com",
    "amplitude.com",
    "heap.io",
    "heapanalytics.com",
    "fullstory.com",
    "clarity.ms",
    "plausible.io",
    "intercom.io",
    "intercomcdn.com",
    "widget.intercom.io",
})


def _require_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise ImportError(
            "Playwright is not installed. "
            "Run: pip install linksanity[browser] && playwright install chromium"
        ) from None


async def extract_links(url: str, *, semaphore: asyncio.Semaphore | None = None) -> list[str]:
    """Launch a headless browser, render the page, and return all href values.

    Filters out mailto:, javascript:, data:, blob:, and empty hrefs.
    semaphore limits concurrent browser contexts.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    sem = semaphore or asyncio.Semaphore(2)
    async with sem, async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            hrefs: list[str] = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(h => h)",
            )
            return [
                h for h in hrefs
                if h and not any(h.startswith(s) for s in _SKIP_SCHEMES)
            ]
        finally:
            await browser.close()


async def check(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    *,
    semaphore: asyncio.Semaphore | None = None,
    timeout: int = 10,
    cell: int | None = None,
) -> LinkResult:
    """Check whether a URL is reachable using a headless browser.

    Uses Playwright's network response to determine status.
    """
    _require_playwright()
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    sem = semaphore or asyncio.Semaphore(2)
    async with sem, async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                )
                if response is None:
                    return LinkResult(
                        source_file=source_file, line=line, url=url,
                        link_type=link_type, status=LinkStatus.ERROR,
                        error="no response",
                        cell=cell,
                    )
                code = response.status
                resolved = page.url
                # `page.url` is the final navigated URL, which httpx-style string
                # comparison would flag as "redirected" on normalization alone
                # (host casing, scheme casing, dot-segments) even with zero HTTP
                # hops. `request.redirected_from` is Playwright's actual signal
                # for a real navigation-level redirect: non-None iff this
                # request replaced an earlier one that received a redirect
                # response.
                was_redirected = response.request.redirected_from is not None
                if code >= 400:
                    status = LinkStatus.BROKEN
                elif was_redirected:
                    status = LinkStatus.REDIRECT
                else:
                    status = LinkStatus.OK
                return LinkResult(
                    source_file=source_file, line=line, url=url,
                    link_type=link_type, status=status,
                    http_code=code,
                    resolved_url=resolved if was_redirected else None,
                    cell=cell,
                )
            except PlaywrightError as exc:
                return LinkResult(
                    source_file=source_file, line=line, url=url,
                    link_type=link_type, status=LinkStatus.ERROR,
                    error=str(exc),
                    cell=cell,
                )
        finally:
            await browser.close()


async def crawl_page(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    *,
    semaphore: asyncio.Semaphore | None = None,
    timeout: int = 10,
    block_domains: frozenset[str] | None = None,
) -> tuple[LinkResult, list[str], set[str]]:
    """Visit a page, check its reachability, and return (result, hrefs, element_ids).

    Combines check() and extract_links() into a single browser session.
    element_ids is the set of id="..." values on the rendered page, used to
    validate same-page anchor fragments (empty when the page isn't reachable).
    """
    _require_playwright()
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    sem = semaphore or asyncio.Semaphore(2)
    async with sem, async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            if block_domains:
                from playwright.async_api import Route

                async def _block(route: Route) -> None:
                    netloc = urlparse(route.request.url).netloc.lower()
                    if any(netloc == d or netloc.endswith("." + d) for d in block_domains):
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", _block)
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                )
                if response is None:
                    return LinkResult(
                        source_file=source_file, line=line, url=url,
                        link_type=link_type, status=LinkStatus.ERROR,
                        error="no response",
                    ), [], set()
                # Wait for JS to finish rendering navigation (SPAs build links client-side)
                with contextlib.suppress(PlaywrightError):
                    await page.wait_for_load_state("networkidle", timeout=5000)
                code = response.status
                resolved = page.url
                # See the matching comment in check() above: use Playwright's
                # actual redirect signal, not a string comparison of URLs.
                was_redirected = response.request.redirected_from is not None
                if code >= 400:
                    status = LinkStatus.BROKEN
                elif was_redirected:
                    status = LinkStatus.REDIRECT
                else:
                    status = LinkStatus.OK
                result = LinkResult(
                    source_file=source_file, line=line, url=url,
                    link_type=link_type, status=status,
                    http_code=code,
                    resolved_url=resolved if was_redirected else None,
                )
                # Extract links and element ids from any reachable page, including redirects
                if status in (LinkStatus.OK, LinkStatus.REDIRECT):
                    hrefs: list[str] = await page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(e => e.href).filter(h => h)",
                    )
                    links = [
                        h for h in hrefs
                        if h and not any(h.startswith(s) for s in _SKIP_SCHEMES)
                    ]
                    ids: list[str] = await page.eval_on_selector_all(
                        "[id]",
                        "els => els.map(e => e.id).filter(id => id)",
                    )
                    element_ids = set(ids)
                else:
                    links = []
                    element_ids = set()
                return result, links, element_ids
            except PlaywrightError as exc:
                return LinkResult(
                    source_file=source_file, line=line, url=url,
                    link_type=link_type, status=LinkStatus.ERROR,
                    error=str(exc),
                ), [], set()
        finally:
            await browser.close()


def scope_filter(urls: list[str], start_url: str) -> list[str]:
    """Keep only URLs on the same domain as start_url."""
    domain = urlparse(start_url).netloc.lower()
    return [u for u in urls if urlparse(u).netloc.lower() == domain]
