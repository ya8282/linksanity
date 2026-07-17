"""Extract links from HTML files using BeautifulSoup + html.parser.

html.parser rather than lxml: bs4 leaves sourceline None on every lxml-built
tag, which reported all links as line 0 and made the fixer skip HTML entirely.
Same trade docbook.py makes -- the backend that yields real line numbers wins.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag


def extract_links(path: Path, *, include_images: bool = False) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from an HTML file.

    Skips empty href/src values. When include_images is True, <img src>
    targets are included too. Parse errors emit a warning and return an
    empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] HTML parse error in {path}: {e}", stacklevel=2)
        return []

    results: list[tuple[str, int]] = []
    for tag in soup.find_all("a", href=True):
        if not isinstance(tag, Tag):
            continue
        href = str(tag.get("href", "")).strip()
        if not href:
            continue
        line: int = getattr(tag, "sourceline", 0) or 0
        results.append((href, line))

    if include_images:
        for tag in soup.find_all("img", src=True):
            if not isinstance(tag, Tag):
                continue
            src = str(tag.get("src", "")).strip()
            if not src:
                continue
            line = getattr(tag, "sourceline", 0) or 0
            results.append((src, line))

    return results
