"""Scan pipeline: walk files, classify links, dispatch to checkers."""

from __future__ import annotations

import asyncio
import glob as glob_module
import os
import sys
from pathlib import Path

from linksanity import git_utils
from linksanity.cache import Cache
from linksanity.config import Config
from linksanity.parsers import asciidoc, docbook, html, markdown, mdx, notebook, rst
from linksanity.parsers import myst as myst_parser
from linksanity.pathwalk import should_descend
from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType
from linksanity.router import classify, dispatch

# Only network-checked link types are worth caching — filesystem/anchor checks
# are already fast and can go stale the moment a local file changes.
_CACHEABLE = {LinkType.EXTERNAL, LinkType.EXTERNAL_ANCHOR}

# Same ten suffixes as init.py's detect_paths (init.py:_SUFFIXES).
_SUFFIXES = (
    ".md",
    ".rst",
    ".html",
    ".htm",
    ".adoc",
    ".asciidoc",
    ".mdx",
    ".ipynb",
    ".xml",
    ".dbk",
)


async def run_scan(patterns: list[str], config: Config) -> LinkQueue:
    """Parse files matching patterns, check all links, return the populated queue."""
    queue = LinkQueue()
    cache = Cache(Path(config.cache_file), config.cache_ttl) if config.cache_file else None

    paths = _expand_paths(patterns)
    # Root-relative links (leading "/") resolve against the scan root, not
    # source_path.parent -- computed once from the original patterns (not
    # the expanded per-file list), same corpus-wide-value pattern as
    # docbook_ids below.
    root = _scan_root(patterns)
    # Record the full corpus before any incremental filtering: the fixer's
    # moved-file resolver needs every candidate target, not just changed files.
    queue.corpus_files = list(paths)
    if config.incremental:
        paths = _filter_changed(paths, config, cache)

    docbook_ids = _collect_docbook_ids(paths)

    for path in paths:
        if path.suffix.lower() == ".ipynb":
            notebook.extract_links(path, queue)
            continue
        for url, line in _parse(path, config.check_images, config.myst):
            link_type = classify(url)
            queue.add(url, str(path), line, link_type)

    http_sem = asyncio.Semaphore(config.workers)
    pw_sem = asyncio.Semaphore(config.playwright_workers)

    to_check: list[tuple[str, str, int, LinkType, int | None]] = []
    for url, src, line, lt, cell in queue.pending():
        cached = cache.get(url) if cache and not config.offline and lt in _CACHEABLE else None
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
                    redirect_codes=cached.redirect_codes,
                    cell=cell,
                )
            )
        else:
            to_check.append((url, src, line, lt, cell))

    outcomes = await asyncio.gather(
        *[
            dispatch(
                url, src, line, lt, config, http_sem, pw_sem,
                cell=cell, docbook_ids=docbook_ids, root=root,
            )
            for url, src, line, lt, cell in to_check
        ],
        return_exceptions=True,
    )
    for (url, src, line, lt, cell), outcome in zip(to_check, outcomes, strict=True):
        if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
            # Not a regular Exception (e.g. asyncio.CancelledError, KeyboardInterrupt) --
            # let it propagate instead of silently converting it to an ERROR result.
            raise outcome
        if isinstance(outcome, Exception):
            result = LinkResult(
                source_file=src, line=line, url=url, link_type=lt,
                status=LinkStatus.ERROR,
                error=f"{type(outcome).__name__}: {outcome}",
                cell=cell,
            )
        else:
            result = outcome
        queue.record(result)
        if cache and not config.offline and result.link_type in _CACHEABLE:
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


def _collect_docbook_ids(paths: list[Path]) -> set[str]:
    """Walk every .xml/.dbk file once, merging all ids into one corpus-wide set.

    DocBook's <xref linkend="foo"> can point to an id defined in a different
    file than the one containing the xref (books are commonly split across
    files via XInclude), so this is a single global namespace with no
    per-file keying -- matching DocBook's own linkend semantics.

    Skips the walk entirely (never calls docbook.extract_ids) when no
    .xml/.dbk files are present, so non-DocBook repos pay zero overhead.
    """
    docbook_ids: set[str] = set()
    for path in paths:
        if path.suffix.lower() in (".xml", ".dbk"):
            docbook_ids |= docbook.extract_ids(path)
    return docbook_ids


def _scan_root(patterns: list[str]) -> Path:
    """Return the directory root-relative links (leading '/') resolve against.

    A single directory target is its own root; a single file target's root
    is its parent directory (matches init.py's docs-root == scan-root
    default, e.g. `linksanity scan website/docs`). Multiple targets, or a
    glob pattern that isn't itself an existing file/dir, fall back to the
    common ancestor of every resolved candidate, or the current directory
    when there's nothing to anchor on at all.
    """
    roots: list[Path] = []
    for pattern in patterns:
        p = Path(pattern)
        if p.is_dir():
            roots.append(p.resolve())
        elif p.is_file():
            roots.append(p.resolve().parent)
        else:
            matches = [
                Path(m) for m in glob_module.glob(pattern, recursive=True) if Path(m).is_file()
            ]
            if matches:
                roots.append(Path(os.path.commonpath([str(m.resolve().parent) for m in matches])))

    if not roots:
        return Path.cwd()
    if len(roots) == 1:
        return roots[0]
    try:
        return Path(os.path.commonpath([str(r) for r in roots]))
    except ValueError:
        # No common path (e.g. different drives on Windows) -- nothing
        # sensible to anchor root-relative links to.
        return Path.cwd()


def _walk_pruned(root: Path) -> list[Path]:
    """Return every supported-suffix file under root, pruning vendored/hidden dirs.

    Mirrors init.py's `detect_paths` walk (both use
    `linksanity.pathwalk.should_descend`), so a directory init proposes isn't
    then scanned in full by CI including its vendored subtrees. Pruning
    means never descending into a matched directory -- nothing nested under
    it, however deep, can surface -- but it only applies to directories
    encountered while walking; `root` itself is never checked against the
    denylist, so an explicitly-requested denylisted directory (or a file
    inside one) is still scanned in full. Dot-directories are pruned the
    same way; dot-files are not (a root-level `.hidden.md` is still found) --
    matching init.py's detection walk, which makes the same choice for the
    same reason (only dot-*directories* are spec-mandated to prune).

    Directory *symlinks* (including a self-referential one) are never
    descended into either, via the same `should_descend` guard init uses --
    a symlinked file is still counted, only directory descent is guarded.
    """
    found: list[Path] = []

    def _recurse(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if should_descend(entry):
                    _recurse(entry)
            elif entry.is_file() and entry.suffix.lower() in _SUFFIXES:
                found.append(entry)

    _recurse(root)
    return found


def _expand_paths(patterns: list[str]) -> list[Path]:
    """Expand file paths, directories, and glob patterns to a deduplicated list."""
    seen: set[Path] = set()
    result: list[Path] = []

    for pattern in patterns:
        p = Path(pattern)
        if p.is_file():
            candidates: list[Path] = [p]
        elif p.is_dir():
            candidates = _walk_pruned(p)
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


def _parse(path: Path, check_images: bool, myst: bool = False) -> list[tuple[str, int]]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        links = markdown.extract_links(path, include_images=check_images)
        if myst:
            links = links + myst_parser.extract_links(path)
        return links
    if suffix == ".rst":
        return rst.extract_links(path, include_images=check_images)
    if suffix in (".html", ".htm"):
        return html.extract_links(path, include_images=check_images)
    if suffix in (".adoc", ".asciidoc"):
        return asciidoc.extract_links(path)
    if suffix == ".mdx":
        return mdx.extract_links(path)
    if suffix in (".xml", ".dbk"):
        return docbook.extract_links(path)
    return []
