"""GitHub Actions annotations — emit ::error/::warning workflow commands."""

from __future__ import annotations

import sys
from typing import IO

from linksanity.queue import FAILING_STATUSES, LinkResult, LinkStatus

_MAX_PER_LEVEL = 10  # GitHub renders at most 10 annotations per level per step

# A redirect loop never resolves, so it's treated the same as BROKEN/ERROR
# here — see FAILING_STATUSES in queue.py, which is the single source of
# truth for what counts as a failure across the CLI's exit codes too.
_ERROR_STATUSES = FAILING_STATUSES
_WARNING_STATUSES = {LinkStatus.REDIRECT}


def _esc(value: str) -> str:
    """Escape a workflow-command message (%, CR, LF)."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(value: str) -> str:
    """Escape a workflow-command property (message rules plus , and :)."""
    return _esc(value).replace(",", "%2C").replace(":", "%3A")


def _line_for(result: LinkResult) -> str:
    detail = result.error or (f"HTTP {result.http_code}" if result.http_code else "unreachable")
    level = "error" if result.status in _ERROR_STATUSES else "warning"
    return (
        f"::{level} file={_esc_prop(result.source_file)},line={result.line},"
        f"title=linksanity::{_esc(f'{result.url} — {detail}')}"
    )


def _emit_level(results: list[LinkResult], level: str, out: IO[str]) -> None:
    for r in results[:_MAX_PER_LEVEL]:
        out.write(_line_for(r) + "\n")
    overflow = len(results) - _MAX_PER_LEVEL
    if overflow > 0:
        out.write(f"::notice::{overflow} additional {level}(s) not shown\n")


def report(results: list[LinkResult], *, file: IO[str] | None = None) -> None:
    out = file or sys.stdout
    errors = [r for r in results if r.status in _ERROR_STATUSES]
    warnings = [r for r in results if r.status in _WARNING_STATUSES]
    _emit_level(errors, "error", out)
    _emit_level(warnings, "warning", out)
