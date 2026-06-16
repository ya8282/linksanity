"""BFS crawl pipeline — Playwright for same-domain pages, httpx for external links."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from linksanity.checkers import http
from linksanity.checkers.playwright import crawl_page, scope_filter
from linksanity.config import Config
from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType


async def run_crawl(start_url: str, config: Config) -> LinkQueue:
    """Crawl start_url and all same-domain pages; HTTP-check external links."""
    queue: LinkQueue = LinkQueue()
    visited: set[str] = set()
    frontier: list[str] = [_norm(start_url)]

    pw_sem = asyncio.Semaphore(config.playwright_workers)
    http_sem = asyncio.Semaphore(config.workers)

    # BFS: Playwright-crawl same-domain pages in batches
    while frontier and len(visited) < config.max_pages:
        remaining = config.max_pages - len(visited)
        batch: list[str] = []
        while frontier and len(batch) < min(config.playwright_workers, remaining):
            url = frontier.pop(0)
            if url not in visited:
                visited.add(url)
                batch.append(url)

        if not batch:
            break

        outcomes: list[tuple[LinkResult, list[str]] | BaseException] = list(
            await asyncio.gather(
                *[
                    crawl_page(
                        url, start_url, 0, LinkType.EXTERNAL,
                        semaphore=pw_sem, timeout=config.timeout,
                    )
                    for url in batch
                ],
                return_exceptions=True,
            )
        )

        for url, outcome in zip(batch, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                result: LinkResult = LinkResult(
                    source_file=start_url, line=0, url=url,
                    link_type=LinkType.EXTERNAL, status=LinkStatus.ERROR,
                    error=str(outcome),
                )
                links: list[str] = []
            else:
                result, links = outcome

            queue.add(url, start_url, 0, LinkType.EXTERNAL)
            queue.record(result)

            same_domain = set(scope_filter(links, start_url))
            for link in links:
                if link in same_domain:
                    norm = _norm(link)
                    if norm not in visited and norm not in frontier:
                        frontier.append(norm)
                else:
                    queue.add(link, url, 0, LinkType.EXTERNAL)

    # HTTP-check all external links (not crawled pages)
    external = [
        (url, src, line, lt)
        for url, src, line, lt in queue.pending()
        if url not in visited
    ]
    if external:
        ext_results = await asyncio.gather(
            *[_http_check(url, src, ln, lt, config, http_sem) for url, src, ln, lt in external]
        )
        for r in ext_results:
            queue.record(r)

    return queue


async def _http_check(
    url: str,
    src: str,
    line: int,
    lt: LinkType,
    config: Config,
    sem: asyncio.Semaphore,
) -> LinkResult:
    async with sem:
        return await http.check(
            url, src, line, lt,
            ignore_domains=config.ignore_domains,
            timeout=config.timeout,
            retries=config.retry,
        )


def _norm(url: str) -> str:
    """Strip fragment and trailing slash for frontier deduplication."""
    p = urlparse(url)
    return p._replace(fragment="").geturl().rstrip("/")
