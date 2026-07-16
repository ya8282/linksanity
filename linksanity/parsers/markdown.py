"""Extract links from Markdown files using markdown-it-py."""

from __future__ import annotations

import warnings
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token


def parse_markdown_string(content: str, *, include_images: bool = False) -> list[tuple[str, int]]:
    """Parse already-loaded Markdown content and extract (url, line) pairs.

    Links inside fenced code blocks and inline code spans are excluded.
    When include_images is True, image ![]() targets are included too.
    Parse errors propagate to the caller.
    """
    md = MarkdownIt().enable("linkify")
    tokens = md.parse(content)
    return _collect(tokens, include_images=include_images)


def extract_links(path: Path, *, include_images: bool = False) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from a Markdown file.

    Links inside fenced code blocks and inline code spans are excluded.
    When include_images is True, image ![]() targets are included too.
    Parse errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        return parse_markdown_string(content, include_images=include_images)
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] markdown parse error in {path}: {e}", stacklevel=2)
        return []

def _collect(tokens: list[Token], *, include_images: bool = False) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    target_types = ("link_open", "image") if include_images else ("link_open",)
    for token in tokens:
        # fence and code_block tokens are not inline — their content is code
        if token.type in ("fence", "code_block"):
            continue
        if token.type == "inline" and token.children:
            line = (token.map[0] + 1) if token.map else 1
            for child in token.children:
                if child.type in target_types:
                    attr = "src" if child.type == "image" else "href"
                    raw = child.attrGet(attr)
                    href = str(raw) if isinstance(raw, str) else ""
                    if href:
                        results.append((href, line))
    return results
