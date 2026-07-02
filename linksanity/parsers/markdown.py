"""Extract links from Markdown files using markdown-it-py."""

from __future__ import annotations

import warnings
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token


def parse_markdown_string(content: str) -> list[tuple[str, int]]:
    """Parse already-loaded Markdown content and extract (url, line) pairs.

    Links inside fenced code blocks and inline code spans are excluded.
    Parse errors propagate to the caller.
    """
    md = MarkdownIt().enable("linkify")
    tokens = md.parse(content)
    return _collect(tokens)


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from a Markdown file.

    Links inside fenced code blocks and inline code spans are excluded.
    Parse errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        return parse_markdown_string(content)
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] markdown parse error in {path}: {e}", stacklevel=2)
        return []


def _collect(tokens: list[Token]) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for token in tokens:
        # fence and code_block tokens are not inline — their content is code
        if token.type in ("fence", "code_block"):
            continue
        if token.type == "inline" and token.children:
            line = (token.map[0] + 1) if token.map else 1
            for child in token.children:
                if child.type == "link_open":
                    raw = child.attrGet("href")
                    href = str(raw) if isinstance(raw, str) else ""
                    if href and not href.startswith(("mailto:", "javascript:")):
                        results.append((href, line))
    return results
