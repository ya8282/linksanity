"""Scan pipeline: walk files, classify links, dispatch to checkers."""

from __future__ import annotations

import asyncio
import glob as glob_module
from pathlib import Path

from linksanity.config import Config
from linksanity.parsers import html, markdown, rst
from linksanity.queue import LinkQueue
from linksanity.router import classify, dispatch


async def run_scan(patterns: list[str], config: Config) -> LinkQueue:
    """Parse files matching patterns, check all links, return the populated queue."""
    queue = LinkQueue()

    for path in _expand_paths(patterns):
        for url, line in _parse(path):
            link_type = classify(url)
            queue.add(url, str(path), line, link_type)

    http_sem = asyncio.Semaphore(config.workers)
    pw_sem = asyncio.Semaphore(config.playwright_workers)

    results = await asyncio.gather(
        *[
            dispatch(url, src, line, lt, config, http_sem, pw_sem, cell=cell)
            for url, src, line, lt, cell in queue.pending()
        ]
    )
    for result in results:
        queue.record(result)

    return queue


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


def _parse(path: Path) -> list[tuple[str, int]]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return markdown.extract_links(path)
    if suffix == ".rst":
        return rst.extract_links(path)
    if suffix in (".html", ".htm"):
        return html.extract_links(path)
    return []
