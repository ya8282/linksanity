"""BFS crawl pipeline — Playwright for same-domain pages, httpx for external links."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from linksanity.checkers import http
from linksanity.checkers.playwright import ANALYTICS_DOMAINS, crawl_page, scope_filter
from linksanity.config import Config, url_is_skipped
from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType


async def run_crawl(start_url: str, config: Config) -> LinkQueue:
    """Crawl start_url and all same-domain pages; HTTP-check external links."""
    queue: LinkQueue = LinkQueue()
    visited: set[str] = set()
    frontier: list[str] = [_norm(start_url)]
    page_ids: dict[str, set[str]] = {}
    # (link_with_fragment, target_page, fragment, source_page) for same-domain
    # anchor links — deferred since the target page may not be crawled yet.
    anchor_refs: list[tuple[str, str, str, str]] = []

    pw_sem = asyncio.Semaphore(config.playwright_workers)
    http_sem = asyncio.Semaphore(config.workers)
    block_domains = ANALYTICS_DOMAINS if config.block_analytics else None
    # Merge analytics domains into the HTTP ignore set so they're skipped as external links too
    effective_ignore = (
        config.ignore_domains | ANALYTICS_DOMAINS if config.block_analytics else config.ignore_domains
    )

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

        outcomes: list[tuple[LinkResult, list[str], set[str]] | BaseException] = list(
            await asyncio.gather(
                *[
                    crawl_page(
                        url, start_url, 0, LinkType.EXTERNAL,
                        semaphore=pw_sem, timeout=config.timeout,
                        block_domains=block_domains,
                    )
                    for url in batch
                ],
                return_exceptions=True,
            )
        )

        for url, outcome in zip(batch, outcomes, strict=True):
            if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
                # Not a regular Exception (e.g. asyncio.CancelledError, KeyboardInterrupt) --
                # let it propagate instead of silently converting it to an ERROR result.
                raise outcome
            if isinstance(outcome, Exception):
                result: LinkResult = LinkResult(
                    source_file=start_url, line=0, url=url,
                    link_type=LinkType.EXTERNAL, status=LinkStatus.ERROR,
                    error=f"{type(outcome).__name__}: {outcome}",
                )
                links: list[str] = []
                ids: set[str] = set()
            else:
                result, links, ids = outcome

            queue.add(url, start_url, 0, LinkType.EXTERNAL)
            queue.record(result)
            page_ids[url] = ids

            same_domain = set(scope_filter(links, start_url))
            for link in links:
                if config.skip_urls and url_is_skipped(link, config.skip_urls):
                    queue.add(link, url, 0, LinkType.EXTERNAL)
                    queue.record(LinkResult(
                        source_file=url, line=0, url=link,
                        link_type=LinkType.EXTERNAL, status=LinkStatus.SKIPPED,
                    ))
                elif link in same_domain:
                    norm = _norm(link)
                    if config.check_anchors and "#" in link:
                        frag = link.split("#", 1)[1]
                        if frag:
                            anchor_refs.append((link, norm, frag, url))
                    if norm not in visited and norm not in frontier:
                        frontier.append(norm)
                else:
                    queue.add(link, url, 0, LinkType.EXTERNAL)

    # HTTP-check all external links (not crawled pages, not already skipped)
    external = [
        (url, src, line, lt)
        for url, src, line, lt, _cell in queue.pending()
        if url not in visited
        and not (config.skip_urls and url_is_skipped(url, config.skip_urls))
    ]
    if external:
        ext_results = await asyncio.gather(
            *[
                _http_check(url, src, ln, lt, config, http_sem, effective_ignore)
                for url, src, ln, lt in external
            ]
        )
        for r in ext_results:
            queue.record(r)

    # Validate same-domain anchor fragments against the target page's element ids.
    # Only pages actually crawled (within max_pages) can be validated.
    for link, target_page, frag, source_page in anchor_refs:
        if queue.add(link, source_page, 0, LinkType.EXTERNAL_ANCHOR):
            target_ids = page_ids.get(target_page)
            if target_ids is None:
                queue.record(LinkResult(
                    source_file=source_page, line=0, url=link,
                    link_type=LinkType.EXTERNAL_ANCHOR, status=LinkStatus.SKIPPED,
                    error=f"target page not crawled, cannot verify anchor: {target_page}",
                ))
            elif frag in target_ids:
                queue.record(LinkResult(
                    source_file=source_page, line=0, url=link,
                    link_type=LinkType.EXTERNAL_ANCHOR, status=LinkStatus.OK,
                ))
            else:
                queue.record(LinkResult(
                    source_file=source_page, line=0, url=link,
                    link_type=LinkType.EXTERNAL_ANCHOR, status=LinkStatus.BROKEN,
                    error=f"anchor '#{frag}' not found on {target_page}",
                ))

    return queue


async def _http_check(
    url: str,
    src: str,
    line: int,
    lt: LinkType,
    config: Config,
    sem: asyncio.Semaphore,
    ignore_domains: set[str],
) -> LinkResult:
    async with sem:
        return await http.check(
            url, src, line, lt,
            ignore_domains=ignore_domains,
            timeout=config.timeout,
            retries=config.retry,
            max_redirects=config.max_redirects,
        )


def _norm(url: str) -> str:
    """Strip fragment and trailing slash for frontier deduplication."""
    p = urlparse(url)
    return p._replace(fragment="").geturl().rstrip("/")
