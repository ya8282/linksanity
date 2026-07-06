"""CSV reporter — RFC 4180 CSV with a header row."""

from __future__ import annotations

import csv
import sys
from typing import IO

from linksanity.queue import LinkResult

_FIELDS = [
    "source_file",
    "line",
    "url",
    "link_type",
    "status",
    "http_code",
    "resolved_url",
    "error",
    "redirect_chain",
]


def report(results: list[LinkResult], *, file: IO[str] | None = None) -> None:
    out = file or sys.stdout
    writer = csv.DictWriter(out, fieldnames=_FIELDS, lineterminator="\n")
    writer.writeheader()
    for r in results:
        writer.writerow(
            {
                "source_file": r.source_file,
                "line": r.line,
                "url": r.url,
                "link_type": r.link_type.value,
                "status": r.status.value,
                "http_code": r.http_code if r.http_code is not None else "",
                "resolved_url": r.resolved_url or "",
                "error": r.error or "",
                "redirect_chain": " -> ".join(r.redirect_chain) if r.redirect_chain else "",
            }
        )
