"""Link classifier and checker dispatcher."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from linksanity.checkers import filesystem, http
from linksanity.config import Config, url_is_skipped
from linksanity.queue import LinkResult, LinkStatus, LinkType


def classify(url: str) -> LinkType:
    """Return the LinkType for a URL based on its structure.

    - '#fragment'         → ANCHOR
    - 'http(s)://…#frag' → EXTERNAL_ANCHOR
    - 'http(s)://…'      → EXTERNAL
    - anything else       → INTERNAL (relative path, may include a fragment)
    """
    if url.startswith("#"):
        return LinkType.ANCHOR

    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return LinkType.EXTERNAL_ANCHOR if parsed.fragment else LinkType.EXTERNAL

    return LinkType.INTERNAL


async def dispatch(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    config: Config,
    http_sem: asyncio.Semaphore,
    pw_sem: asyncio.Semaphore,
) -> LinkResult:
    """Route a link to the correct checker and return its result."""
    if link_type in (LinkType.ANCHOR, LinkType.INTERNAL):
        return filesystem.check(
            url, source_file, line, link_type,
            check_anchors=config.check_anchors,
        )

    if config.skip_urls and url_is_skipped(url, config.skip_urls):
        return LinkResult(
            source_file=source_file, line=line, url=url,
            link_type=link_type, status=LinkStatus.SKIPPED,
        )

    domain = urlparse(url).netloc.lower()
    if config.js_domains and _domain_match(domain, config.js_domains):
        from linksanity.checkers import playwright
        return await playwright.check(
            url, source_file, line, link_type,
            semaphore=pw_sem,
            timeout=config.timeout,
        )

    async with http_sem:
        return await http.check(
            url, source_file, line, link_type,
            ignore_domains=config.ignore_domains,
            timeout=config.timeout,
            retries=config.retry,
        )


def _domain_match(domain: str, js_set: set[str]) -> bool:
    return domain in js_set or any(domain.endswith("." + d) for d in js_set)
