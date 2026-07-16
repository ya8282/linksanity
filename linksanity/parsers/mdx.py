"""Extract links from MDX files: CommonMark links plus JSX attributes.

MDX is CommonMark with embedded JSX. The CommonMark portion is delegated
to markdown.py's shared token walk; JSX href=/to= string-literal
attributes (which markdown-it treats as opaque raw HTML/JSX, not as
links) are picked up separately via a line-based regex scan.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from linksanity.parsers.markdown import parse_markdown_string

# Matches JSX string-literal href="..." or to="..." attributes. Requiring
# a quote immediately after `=` means expression attributes such as
# href={someVar} never match -- they're skipped, not guessed at.
_JSX_HREF = re.compile(r'''\b(?:href|to)=["']([^"'{}]+)["']''')

# A fenced code block opens/closes on a line consisting of (up to 3 leading
# spaces, per CommonMark) three-or-more backticks or tildes. Closing the
# same fence requires the same character and at least as many repeats as
# the opener -- matching how markdown-it-py (and CommonMark) resolve fences.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from an MDX file.

    Combines the shared CommonMark link walk (parse_markdown_string) with
    a line-based scan for JSX href=/to= string-literal attributes. JSX
    expression attributes (e.g. href={var}) are skipped without error.
    Read and parse errors emit a warning and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    try:
        results = parse_markdown_string(content)
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"[linksanity] mdx parse error in {path}: {e}", stacklevel=2)
        return []

    seen = set(results)
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

        for url in _JSX_HREF.findall(line):
            pair = (url, lineno)
            if pair not in seen:
                results.append(pair)
                seen.add(pair)

    return results
