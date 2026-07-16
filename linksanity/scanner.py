"""Scan pipeline: walk files, classify links, dispatch to checkers."""

from __future__ import annotations

import asyncio
import glob as glob_module
import sys
from pathlib import Path

from linksanity import git_utils
from linksanity.cache import Cache
from linksanity.config import Config
from linksanity.parsers import html, markdown, rst
from linksanity.queue import LinkQueue, LinkResult, LinkType
from linksanity.router import classify, dispatch

# Only network-checked link types are worth caching — filesystem/anchor checks
# are already fast and can go stale the moment a local file changes.
_CACHEABLE = {LinkType.EXTERNAL, LinkType.EXTERNAL_ANCHOR}


async def run_scan(patterns: list[str], config: Config) -> LinkQueue:
    """Parse files matching patterns, check all links, return the populated queue."""
    queue = LinkQueue()
    cache = Cache(Path(config.cache_file), config.cache_ttl) if config.cache_file else None

    paths = _expand_paths(patterns)
    if config.incremental:
        paths = _filter_changed(paths, config, cache)

    for path in paths:
        for url, line in _parse(path, config.check_images):
            link_type = classify(url)
            queue.add(url, str(path), line, link_type)

    http_sem = asyncio.Semaphore(config.workers)
    pw_sem = asyncio.Semaphore(config.playwright_workers)

    to_check: list[tuple[str, str, int, LinkType, int | None]] = []
    for url, src, line, lt, cell in queue.pending():
        cached = cache.get(url) if cache and lt in _CACHEABLE else None
        if cached is not None:
            queue.record(
                LinkResult(
                    source_file=src,
                    line=line,
                    url=url,
                    link_type=lt,
                    status=cached.status,
                    http_code=cached.http_code,
                    resolved_url=cached.resolved_url,
                    error=cached.error,
                    redirect_chain=cached.redirect_chain,
                    cell=cell,
                )
            )
        else:
            to_check.append((url, src, line, lt, cell))

    results = await asyncio.gather(
        *[
            dispatch(url, src, line, lt, config, http_sem, pw_sem, cell=cell)
            for url, src, line, lt, cell in to_check
        ]
    )
    for result in results:
        queue.record(result)
        if cache and result.link_type in _CACHEABLE:
            cache.put(result)

    if cache:
        cache.save(last_commit=git_utils.current_head())

    return queue


def _filter_changed(paths: list[Path], config: Config, cache: Cache | None) -> list[Path]:
    """Keep only files changed since the baseline commit (git diff-aware)."""
    since = config.since or (cache.last_commit if cache else None)
    if not since:
        print(
            "[linksanity] --incremental: no previous run recorded, running full scan",
            file=sys.stderr,
        )
        return paths

    changed = git_utils.changed_files(since)
    if changed is None:
        print(
            f"[linksanity] --incremental: could not diff against {since!r}, running full scan",
            file=sys.stderr,
        )
        return paths

    return [p for p in paths if p.resolve() in changed]


def _expand_paths(patterns: list[str]) -> list[Path]:
    """Expand file paths, directories, and glob patterns to a deduplicated list."""
    seen: set[Path] = set()
    result: list[Path] = []

    for pattern in patterns:
        p = Path(pattern)
        if p.is_file():
            candidates: list[Path] = [p]
        elif p.is_dir():
            candidates = [
                c
                for suffix in (".md", ".rst", ".html", ".htm")
                for c in p.rglob(f"*{suffix}")
            ]
        else:
            candidates = [
                Path(m)
                for m in glob_module.glob(pattern, recursive=True)
                if Path(m).is_file()
            ]

        for c in candidates:
            if c not in seen:
                seen.add(c)
                result.append(c)

    return result


def _parse(path: Path, check_images: bool) -> list[tuple[str, int]]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return markdown.extract_links(path, include_images=check_images)
    if suffix == ".rst":
        return rst.extract_links(path, include_images=check_images)
    if suffix in (".html", ".htm"):
        return html.extract_links(path, include_images=check_images)
    return []
