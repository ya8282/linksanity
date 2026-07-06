"""Extract links from reStructuredText files using docutils."""

from __future__ import annotations

import warnings
from io import StringIO
from pathlib import Path

from docutils.core import publish_doctree
from docutils.nodes import image, reference, target
from docutils.utils import Reporter


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

    results: list[tuple[str, int]] = []

    for node in document.findall(reference):
        uri = node.get("refuri", "")
        if isinstance(uri, str) and uri:
            line: int = node.line or 0
            results.append((uri, line))

    for node in document.findall(target):
        uri = node.get("refuri", "")
        if isinstance(uri, str) and uri:
            line = node.line or 0
            results.append((uri, line))

    if include_images:
        for node in document.findall(image):
            uri = node.get("uri", "")
            if isinstance(uri, str) and uri:
                line = node.line or 0
                results.append((uri, line))

    return results
