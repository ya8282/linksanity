"""Rich console reporter — grouped, color-coded output."""

from __future__ import annotations

import sys
from itertools import groupby
from operator import attrgetter
from typing import IO

from rich.console import Console

from linksanity.queue import LinkResult, LinkStatus

# Only these statuses appear in the per-file output; OK/SKIPPED are silent
_NOTABLE = {
    LinkStatus.BROKEN,
    LinkStatus.ERROR,
    LinkStatus.REDIRECT,
    LinkStatus.TOO_MANY_REDIRECTS,
}

_LABEL: dict[LinkStatus, tuple[str, str]] = {
    LinkStatus.BROKEN: ("BROKEN  ", "bold red"),
    LinkStatus.ERROR: ("ERROR   ", "bold red"),
    LinkStatus.REDIRECT: ("REDIRECT", "yellow"),
    LinkStatus.TOO_MANY_REDIRECTS: ("TOOMANY ", "yellow"),
    LinkStatus.SKIPPED: ("SKIPPED ", "dim"),
    LinkStatus.OK: ("OK      ", "green"),
}


def report(results: list[LinkResult], *, file: IO[str] | None = None) -> None:
    # Write to file as plain text; write to terminal with color
    no_color = file is not None
    console = Console(file=file or sys.stdout, highlight=False, no_color=no_color)

    if not results:
        console.print("No links found.")
        return

    notable = [r for r in results if r.status in _NOTABLE]
    if notable:
        by_file = sorted(notable, key=attrgetter("source_file", "line"))
        for source_file, group_iter in groupby(by_file, key=attrgetter("source_file")):
            console.print()
            console.print(f"[bold]{source_file}[/bold]")
            for r in group_iter:
                label, style = _LABEL[r.status]
                if r.cell is not None:
                    line_col = f"cell {r.cell}, line {r.line:>4}"
                else:
                    line_col = f"line {r.line:>4}"
                detail = _detail(r)
                console.print(
                    f"  [{style}]{label}[/{style}]  {line_col}  {r.url}{detail}"
                )

    counts: dict[LinkStatus, int] = {s: 0 for s in LinkStatus}
    for r in results:
        counts[r.status] += 1

    ok = counts[LinkStatus.OK]
    broken = counts[LinkStatus.BROKEN] + counts[LinkStatus.ERROR]
    redirect = counts[LinkStatus.REDIRECT]
    too_many = counts[LinkStatus.TOO_MANY_REDIRECTS]
    skipped = counts[LinkStatus.SKIPPED]

    console.print()
    console.rule(style="dim")
    broken_style = "bold red" if broken else "dim"
    redirect_style = "yellow" if redirect else "dim"
    too_many_style = "yellow" if too_many else "dim"
    console.print(
        f"  [green]ok={ok}[/green]"
        f"   [{broken_style}]broken={broken}[/{broken_style}]"
        f"   [{redirect_style}]redirect={redirect}[/{redirect_style}]"
        f"   [{too_many_style}]too_many_redirects={too_many}[/{too_many_style}]"
        f"   [dim]skipped={skipped}[/dim]"
    )


def _detail(r: LinkResult) -> str:
    if r.status == LinkStatus.REDIRECT:
        suffix = f" [{r.http_code}]" if r.http_code else ""
        if r.redirect_chain:
            return f" → {' → '.join(r.redirect_chain)}{suffix}"
        return f" → {r.resolved_url}{suffix}"
    if r.status == LinkStatus.TOO_MANY_REDIRECTS:
        return f" — {r.error}"
    if r.http_code and r.http_code >= 400:
        return f" [{r.http_code}]"
    if r.error:
        return f" — {r.error}"
    return ""
