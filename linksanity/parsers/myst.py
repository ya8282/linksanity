"""Extract MyST role targets from Markdown files: {doc}`target` / {ref}`target`.

MyST is a Sphinx-flavored extension of CommonMark. Roles use curly-brace
markup (`{rolename}`target`) that CommonMark parsing does not recognize at
all, so this is a second, independent regex pass over the raw file content --
conceptually the same pattern as mdx.py's JSX attribute pass on top of
parse_markdown_string(). Only run when the myst config flag / --myst CLI
flag is enabled; markdown.py's extraction path is untouched.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

# Matches genuine MyST role syntax only: {doc} or {ref} immediately followed
# by a backtick-quoted target, with no space between the closing brace and
# the opening backtick. This deliberately excludes prose that merely mentions
# curly braces or backticks separately (e.g. "the {ref} role" or "a `code`
# span") -- only the exact adjacent `{doc}`...`` / `{ref}`...`` shape matches.
_ROLE_RE = re.compile(r"\{(?:doc|ref)\}`([^`]+)`")

# A fenced code block opens/closes on a line consisting of (up to 3 leading
# spaces, per CommonMark) three-or-more backticks or tildes. Mirrors
# mdx.py's _FENCE_RE so role syntax shown as a code example isn't extracted.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def extract_roles(content: str) -> list[tuple[str, int]]:
    """Return (target, line) pairs for {doc}/{ref} role targets in content.

    Roles inside fenced code blocks are excluded.
    """
    results: list[tuple[str, int]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        fence_match = _FENCE_RE.match(line)

        if in_fence:
            if (
                fence_match
                and fence_match.group(1)[0] == fence_char
                and len(fence_match.group(1)) >= fence_len
            ):
                in_fence = False
            continue

        if fence_match:
            in_fence = True
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            continue

        for match in _ROLE_RE.finditer(line):
            results.append((match.group(1), lineno))

    return results


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (target, line) pairs of MyST role targets extracted from a file.

    Read errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    return extract_roles(content)
