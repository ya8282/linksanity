"""Markdown summary reporter — writes a `--report` file with a human-readable summary."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from itertools import groupby
from operator import attrgetter
from typing import IO

from linksanity.queue import LinkResult, LinkStatus

_NOTABLE = {
    LinkStatus.BROKEN,
    LinkStatus.ERROR,
    LinkStatus.REDIRECT,
    LinkStatus.TOO_MANY_REDIRECTS,
}


def report(results: list[LinkResult], *, file: IO[str] | None = None) -> None:
    out = file or sys.stdout
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    _w(out, f"# linksanity scan report\n\n_Generated: {ts}_\n")

    counts: dict[LinkStatus, int] = {s: 0 for s in LinkStatus}
    for r in results:
        counts[r.status] += 1

    ok = counts[LinkStatus.OK]
    broken = counts[LinkStatus.BROKEN] + counts[LinkStatus.ERROR]
    redirect = counts[LinkStatus.REDIRECT]
    too_many = counts[LinkStatus.TOO_MANY_REDIRECTS]
    skipped = counts[LinkStatus.SKIPPED]
    total = len(results)

    _w(out, "\n## Summary\n")
    _w(out, "| Status | Count |\n|---|---|\n")
    _w(out, f"| ✅ ok | {ok} |\n")
    _w(out, f"| ❌ broken | {broken} |\n")
    _w(out, f"| ↗ redirect | {redirect} |\n")
    _w(out, f"| ⚠ too many redirects | {too_many} |\n")
    _w(out, f"| ⏭ skipped | {skipped} |\n")
    _w(out, f"| **total** | **{total}** |\n")

    notable = [r for r in results if r.status in _NOTABLE]
    if not notable:
        _w(out, "\n✅ No broken or redirected links found.\n")
        return

    _w(out, "\n## Details\n")
    by_file = sorted(notable, key=attrgetter("source_file", "line"))
    for source_file, group_iter in groupby(by_file, key=attrgetter("source_file")):
        _w(out, f"\n### `{source_file}`\n\n")
        _w(out, "| Line | Status | URL | Detail |\n|---|---|---|---|\n")
        for r in group_iter:
            status_icon = "❌" if r.status in (LinkStatus.BROKEN, LinkStatus.ERROR) else "↗"
            if r.status == LinkStatus.TOO_MANY_REDIRECTS:
                status_icon = "⚠"
            detail = _detail(r)
            _w(out, f"| {r.line} | {status_icon} {r.status.value} | `{r.url}` | {detail} |\n")


def _detail(r: LinkResult) -> str:
    if r.status == LinkStatus.REDIRECT:
        suffix = f" `[{r.http_code}]`" if r.http_code else ""
        if r.redirect_chain:
            return f"{' → '.join(f'`{u}`' for u in r.redirect_chain)}{suffix}"
        return f"→ `{r.resolved_url}`{suffix}"
    if r.status == LinkStatus.TOO_MANY_REDIRECTS:
        return r.error or ""
    if r.http_code and r.http_code >= 400:
        return f"`[{r.http_code}]`"
    if r.error:
        return r.error
    return ""


def _w(out: IO[str], text: str) -> None:
    out.write(text)
