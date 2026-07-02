"""Extract links from AsciiDoc files via a line-based regex scan.

This is a regex/line-scan extractor over raw AsciiDoc source, not a
render pipeline. Rendering first would collapse line-number fidelity,
which this project relies on for accurate diagnostics.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

_LINK_MACRO_RE = re.compile(r"link:(\S+?)\[")
_XREF_MACRO_RE = re.compile(r"xref:(\S+?)\[")
_BARE_URL_RE = re.compile(r"https?://\S+")

# A delimited block opens/closes on a line that is exactly the marker
# (four or more hyphens for listing blocks, or ++++ for passthrough).
_LISTING_DELIM_RE = re.compile(r"^-{4,}$")
_PASSTHROUGH_DELIM_RE = re.compile(r"^(\+\+\+\+|```)$")


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from an AsciiDoc file.

    Extracts `link:URL[...]` macros, `xref:TARGET[...]` macros, and bare
    `https?://` autolinks. Content inside `----` listing blocks and
    `++++`/``` passthrough blocks is skipped. Read errors emit a warning
    and return an empty list.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return []

    results: list[tuple[str, int]] = []
    in_listing = False
    in_passthrough = False

    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        if in_listing:
            if _LISTING_DELIM_RE.match(stripped):
                in_listing = False
            continue
        if in_passthrough:
            if _PASSTHROUGH_DELIM_RE.match(stripped):
                in_passthrough = False
            continue

        if _LISTING_DELIM_RE.match(stripped):
            in_listing = True
            continue
        if _PASSTHROUGH_DELIM_RE.match(stripped):
            in_passthrough = True
            continue

        link_matches = list(_LINK_MACRO_RE.finditer(line))
        xref_matches = list(_XREF_MACRO_RE.finditer(line))

        for match in link_matches:
            results.append((match.group(1), lineno))
        for match in xref_matches:
            results.append((match.group(1), lineno))

        macro_spans = [(m.start(), m.end()) for m in link_matches + xref_matches]
        for match in _BARE_URL_RE.finditer(line):
            if any(start <= match.start() < end for start, end in macro_spans):
                continue
            results.append((match.group(0), lineno))

    return results
