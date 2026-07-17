"""Extract links from reStructuredText files using docutils."""

from __future__ import annotations

import warnings
from io import StringIO
from pathlib import Path

from docutils.core import publish_doctree
from docutils.nodes import Node, image, reference, target
from docutils.utils import Reporter

from linksanity.parsers._lines import find_line


def _hint(node: Node) -> int:
    """Best line docutils offers: inline nodes carry none, their block does."""
    own = node.line
    if own:
        return int(own)
    parent = node.parent
    return int(parent.line) if parent is not None and parent.line else 0


def extract_links(path: Path, *, include_images: bool = False) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from an RST file.

    When include_images is True, image :: directive uris are included too.
    Parse errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        document = publish_doctree(
            content,
            source_path=str(path),
            settings_overrides={
                "report_level": Reporter.SEVERE_LEVEL,
                "halt_level": Reporter.SEVERE_LEVEL,
                "warning_stream": StringIO(),
            },
        )
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] RST parse error in {path}: {e}", stacklevel=2)
        return []

    lines = content.split("\n")
    results: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    def add(uri: str, node: Node) -> None:
        # An inline hyperlink yields both a reference and a target node with
        # the same refuri, so the same (url, line) arrives twice.
        pair = (uri, find_line(lines, uri, _hint(node)))
        if pair not in seen:
            seen.add(pair)
            results.append(pair)

    for node in document.findall(reference):
        uri = node.get("refuri", "")
        if isinstance(uri, str) and uri:
            add(uri, node)

    for node in document.findall(target):
        uri = node.get("refuri", "")
        if isinstance(uri, str) and uri:
            add(uri, node)

    if include_images:
        for node in document.findall(image):
            uri = node.get("uri", "")
            if isinstance(uri, str) and uri:
                add(uri, node)

    return results
