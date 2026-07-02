"""Async HTTP link checker using httpx with retry and fallback."""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx

from linksanity.queue import LinkResult, LinkStatus, LinkType

_RETRY_ON = {429, 503}
_FALLBACK_ON = {405}
_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {"User-Agent": "linksanity/0.1 link-checker (+https://github.com/linksanity)"}

# Hostnames that are always private regardless of DNS resolution
_PRIVATE_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname is a loopback, link-local, or private address."""
    if hostname.lower() in _PRIVATE_HOSTNAMES:
        return True
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_loopback or addr.is_link_local or addr.is_private
    except ValueError:
        return False


async def check(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    *,
    ignore_domains: set[str] | None = None,
    timeout: int = 10,
    retries: int = 2,
    cell: int | None = None,
) -> LinkResult:
    """Check an external URL and return a LinkResult.

    Strategy:
    1. HEAD request first (fast, low bandwidth).
    2. On 405 Method Not Allowed, retry with GET + stream (no body download).
    3. On 429/503, retry up to `retries` times with exponential backoff.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    hostname = parsed.hostname or ""

    if _is_private_host(hostname):
        return LinkResult(
            source_file=source_file, line=line, url=url,
            link_type=link_type, status=LinkStatus.SKIPPED,
            error="skipped: private/loopback address",
            cell=cell,
        )

    if ignore_domains and _domain_match(domain, ignore_domains):
        return LinkResult(
            source_file=source_file, line=line, url=url,
            link_type=link_type, status=LinkStatus.SKIPPED,
            cell=cell,
        )

    client_timeout = httpx.Timeout(float(timeout))
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=client_timeout,
            headers=_HEADERS,
        ) as client:
            return await _check_with_retry(
                client, url, source_file, line, link_type, retries, cell
            )
    except Exception as exc:
        return LinkResult(
            source_file=source_file, line=line, url=url,
            link_type=link_type, status=LinkStatus.ERROR,
            error=str(exc),
            cell=cell,
        )


async def _check_with_retry(
    client: httpx.AsyncClient,
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    retries: int,
    cell: int | None = None,
) -> LinkResult:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = await _try_head(client, url, source_file, line, link_type, cell)
            if result.http_code in _RETRY_ON and attempt < retries:
                await asyncio.sleep(2 ** attempt)
                continue
            return result
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(2 ** attempt)

    return LinkResult(
        source_file=source_file, line=line, url=url,
        link_type=link_type, status=LinkStatus.ERROR,
        error=str(last_exc),
        cell=cell,
    )


async def _try_head(
    client: httpx.AsyncClient,
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    cell: int | None = None,
) -> LinkResult:
    try:
        resp = await client.head(url)
    except httpx.HTTPError:
        raise

    if resp.status_code in _FALLBACK_ON:
        # Server doesn't support HEAD — try GET with streaming (no body)
        async with client.stream("GET", url) as stream_resp:
            code = stream_resp.status_code
            resolved = str(stream_resp.url)
    else:
        code = resp.status_code
        resolved = str(resp.url)

    return _make_result(url, source_file, line, link_type, code, resolved, cell)


def _make_result(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    code: int,
    resolved_url: str,
    cell: int | None = None,
) -> LinkResult:
    # With follow_redirects=True, httpx resolves the full chain.
    # A redirect is detected when the final URL differs from the original.
    was_redirected = resolved_url.rstrip("/") != url.rstrip("/")

    if code >= 400:
        status = LinkStatus.BROKEN
    elif was_redirected:
        status = LinkStatus.REDIRECT
    else:
        status = LinkStatus.OK

    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=link_type,
        status=status,
        http_code=code,
        resolved_url=resolved_url if was_redirected else None,
        cell=cell,
    )


def _domain_match(domain: str, ignore_set: set[str]) -> bool:
    """Return True if domain or any parent domain is in the ignore set."""
    return domain in ignore_set or any(
        domain.endswith("." + d) for d in ignore_set
    )
