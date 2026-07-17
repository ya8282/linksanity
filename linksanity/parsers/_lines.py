"""Resolve a URL to the source line that actually contains it."""

from __future__ import annotations


def find_line(
    lines: list[str], url: str, hint: int, cursors: dict[str, int] | None = None
) -> int:
    """Return the 1-based line at or after `hint` whose text contains `url`.

    Both docutils and markdown-it number the enclosing block, not the link, so
    every link in a paragraph reports the paragraph's first line. The fixer
    rewrites whichever line it is handed, so the line holding the URL text is
    the one that has to be reported.

    `cursors` maps url -> next line to search, so a URL repeated across lines
    resolves to successive lines instead of collapsing onto the first. Pass
    None where one source link yields several parser nodes (docutils emits a
    reference and a target for the same hyperlink), since each node would
    otherwise advance the cursor past its sibling.

    Falls back to `hint` when the URL text is absent from the source, e.g. a
    link the parser resolved or entity-decoded.
    """
    start = max(hint, cursors.get(url, 0) if cursors else 0, 1)
    for i in range(start - 1, len(lines)):
        if url in lines[i]:
            if cursors is not None:
                cursors[url] = i + 2
            return i + 1
    return hint
