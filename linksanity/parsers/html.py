"""Extract links from HTML files using BeautifulSoup + lxml."""

from __future__ import annotations

import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag

_SKIP_SCHEMES = ("mailto:", "javascript:")


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from an HTML file.

    Skips mailto:, javascript:, and empty href values.
    Parse errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        soup = BeautifulSoup(content, "lxml")
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] HTML parse error in {path}: {e}", stacklevel=2)
        return []

    results: list[tuple[str, int]] = []
    for tag in soup.find_all("a", href=True):
        if not isinstance(tag, Tag):
            continue
        href = str(tag.get("href", "")).strip()
        if not href or href.startswith(_SKIP_SCHEMES):
            continue
        # lxml exposes sourceline on the underlying element
        line: int = getattr(tag, "sourceline", 0) or 0
        results.append((href, line))

    return results
