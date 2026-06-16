"""Reporter dispatcher — routes results to the configured output format."""

from __future__ import annotations

from typing import IO

from linksanity.config import Config
from linksanity.queue import LinkResult


def report(
    results: list[LinkResult],
    config: Config,
    *,
    file: IO[str] | None = None,
) -> None:
    fmt = config.format
    if fmt == "json":
        from linksanity.reporters.json_reporter import report as _r  # noqa: I001
        _r(results, file=file)
    elif fmt == "csv":
        from linksanity.reporters.csv_reporter import report as _r  # noqa: I001
        _r(results, file=file)
    else:
        from linksanity.reporters.console import report as _r
        _r(results, file=file)
