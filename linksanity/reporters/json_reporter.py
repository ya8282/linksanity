"""JSON reporter — one JSON array of link result objects."""

from __future__ import annotations

import json
import sys
from typing import IO

from linksanity.queue import LinkResult


def report(results: list[LinkResult], *, file: IO[str] | None = None) -> None:
    out = file or sys.stdout
    data = [
        {
            "source_file": r.source_file,
            "line": r.line,
            "url": r.url,
            "link_type": r.link_type.value,
            "status": r.status.value,
            "http_code": r.http_code,
            "resolved_url": r.resolved_url,
            "error": r.error,
        }
        for r in results
    ]
    json.dump(data, out, indent=2, ensure_ascii=False)
    out.write("\n")
