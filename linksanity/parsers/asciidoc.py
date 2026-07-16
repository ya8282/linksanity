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

# Trailing punctuation trimmed off bare autolinks (see Bug 1 handling below).
# Known limitation: a URL whose canonical form legitimately ends in one of
# these characters (e.g. an unbalanced trailing paren) will be over-trimmed.
_TRAILING_URL_PUNCT = ".,;:!?)]}'\""

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
    listing_open_line = 0
    passthrough_open_line = 0
    # True before line 1 too, so a block delimiter on the first line of the
    # file still opens a block (matches AsciiDoc's own behavior).
    prev_blank = True

    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        if in_listing:
            if _LISTING_DELIM_RE.match(stripped):
                in_listing = False
            prev_blank = stripped == ""
            continue
        if in_passthrough:
            if _PASSTHROUGH_DELIM_RE.match(stripped):
                in_passthrough = False
            prev_blank = stripped == ""
            continue

        # A section heading's two-line ("setext") underline has the same
        # shape as a listing/passthrough delimiter but, unlike a real block
        # open, never has a blank line before it. Requiring a blank line
        # distinguishes the two for the common case. Known gap: a heading
        # that happens to be preceded by a blank line is still ambiguous
        # with a real block open; that's an accepted limitation.
        if prev_blank and _LISTING_DELIM_RE.match(stripped):
            in_listing = True
            listing_open_line = lineno
            prev_blank = stripped == ""
            continue
        if prev_blank and _PASSTHROUGH_DELIM_RE.match(stripped):
            in_passthrough = True
            passthrough_open_line = lineno
            prev_blank = stripped == ""
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
            url = match.group(0).rstrip(_TRAILING_URL_PUNCT)
            results.append((url, lineno))

        prev_blank = stripped == ""

    if in_listing:
        warnings.warn(
            f"[linksanity] unterminated listing block in {path}: "
            f"opened at line {listing_open_line}",
            stacklevel=2,
        )
    if in_passthrough:
        warnings.warn(
            f"[linksanity] unterminated passthrough block in {path}: "
            f"opened at line {passthrough_open_line}",
            stacklevel=2,
        )

    return results
