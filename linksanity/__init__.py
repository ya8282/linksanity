"""linksanity — detect broken links in Markdown, reStructuredText, and HTML documentation.

Most users interact with linksanity via the ``linksanity`` CLI (see ``cli.py``),
but the scan pipeline is also usable as a library. :func:`scan_paths` is a thin,
synchronous wrapper around :func:`linksanity.scanner.run_scan` for adopters who
want results in-process without shelling out or touching asyncio themselves.
"""

from __future__ import annotations

import asyncio
import dataclasses
from concurrent.futures import ThreadPoolExecutor

from linksanity.config import Config, load_config
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.scanner import run_scan

__version__ = "0.1.0"

__all__ = [
    "Config",
    "LinkResult",
    "LinkStatus",
    "LinkType",
    "load_config",
    "scan_paths",
]


def scan_paths(
    paths: list[str],
    *,
    check_anchors: bool = False,
    config: Config | None = None,
) -> list[LinkResult]:
    """Scan files, directories, or glob patterns for broken links.

    This wraps :func:`linksanity.scanner.run_scan` (async) in
    :func:`asyncio.run` so library adopters get a plain synchronous call. It
    returns the flat list of :class:`~linksanity.queue.LinkResult` records
    for the scan, the same data the ``linksanity scan`` CLI command reports.

    Safe to call even from within a running event loop (e.g. a Jupyter
    notebook cell or an async web handler such as a FastAPI route): in that
    case the scan runs in a separate worker thread with its own event loop,
    rather than raising ``RuntimeError`` for calling :func:`asyncio.run`
    while a loop is already running.

    Args:
        paths: Files, directories, or glob patterns to scan.
        check_anchors: Validate anchor fragments (``#section``) against
            headings in the target file. Ignored if ``config`` is given and
            already sets ``check_anchors``.
        config: An existing :class:`~linksanity.config.Config` to use
            instead of the default. If omitted, a default ``Config()`` is
            used with ``check_anchors`` applied on top of it.

    Returns:
        A list of ``LinkResult``, one per unique link found.

    Example:
        >>> from linksanity import scan_paths, LinkStatus
        >>> results = scan_paths(["docs/"])
        >>> broken = [r for r in results if r.status == LinkStatus.BROKEN]
    """
    cfg = config if config is not None else Config()
    if check_anchors and not cfg.check_anchors:
        cfg = dataclasses.replace(cfg, check_anchors=True)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running in this thread — safe to use asyncio.run
        # directly.
        queue = asyncio.run(run_scan(paths, cfg))
    else:
        # Already inside a running event loop (e.g. Jupyter, an async web
        # handler). asyncio.run() would raise RuntimeError here, so run the
        # scan in a separate thread that gets its own fresh event loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            queue = pool.submit(asyncio.run, run_scan(paths, cfg)).result()

    return queue.results()
