"""Baseline diffing — compare a scan against a previous JSON report.

Lets CI fail only on *new* breakage instead of re-flagging known, pre-existing
broken links on every run.
"""

from __future__ import annotations

import json
from pathlib import Path

from linksanity.queue import LinkResult, LinkStatus

_NOTABLE = {
    LinkStatus.BROKEN,
    LinkStatus.ERROR,
    LinkStatus.REDIRECT,
    LinkStatus.TOO_MANY_REDIRECTS,
}
_NOTABLE_VALUES = {s.value for s in _NOTABLE}


def _key(source_file: str, url: str) -> tuple[str, str]:
    # Keyed on (file, url), not line — an unrelated edit shifting line numbers
    # shouldn't make an already-known-broken link look "new".
    return (source_file, url)


def load_baseline(path: Path) -> set[tuple[str, str]]:
    """Return identity keys of every notable (non-OK/skipped) link in a prior JSON report."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        _key(r["source_file"], r["url"])
        for r in data
        if r.get("status") in _NOTABLE_VALUES
    }


def only_new(results: list[LinkResult], baseline: set[tuple[str, str]]) -> list[LinkResult]:
    """Drop notable results that already existed in the baseline; keep everything else."""
    return [
        r
        for r in results
        if r.status not in _NOTABLE or _key(r.source_file, r.url) not in baseline
    ]
