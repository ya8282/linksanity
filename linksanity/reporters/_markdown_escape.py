"""Shared Markdown escaping for free-text `LinkResult` fields.

Used by `markdown_reporter.py` and `github_reporter.py`, both of which
interpolate attacker-influenced text (URLs, error messages from
`str(exc)`) into GitHub Flavored Markdown tables.

Two contexts need two different treatments:

- `wrap_code_span()` — for fields rendered inside a `` `code span` ``
  (URLs, file paths). Code-span content is always literal, so it must not
  be escaped with backslashes (that would show up as literal doubled
  backslashes in, say, a Windows path); instead the delimiter fence itself
  is sized so the content's own backticks can't close it early.
- `escape_plain()` — for fields rendered with no surrounding code span
  (the `Detail` column when there's no HTTP-code badge). Backslash-escaping
  is the only tool available there, so Markdown's other structural
  characters are escaped directly.

Both still neutralise ``|`` (which splits a table row regardless of code
span state -- GFM's row-splitting pass runs before inline/code-span parsing)
and raw newlines (which end a row outright and corrupt the rest of the
document), rendering the latter as ``<br>``.
"""

from __future__ import annotations

# Markdown characters that can create structure (link/image syntax, raw
# HTML tags, code spans) when a free-text value has no code span protecting
# it. Order matters only in that this must run *after* backslash-doubling
# in escape_plain(), so the backslashes it inserts aren't re-escaped.
_STRUCTURAL_CHARS = "`[]()<"


def _normalize_newlines(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("\n", "<br>")


def wrap_code_span(text: str) -> str:
    """Wrap `text` in a Markdown code span that its own backticks can't close early.

    Per CommonMark's code-span rule, a run of N backticks only closes a span
    opened by a run of exactly N backticks. Choosing a fence one backtick
    longer than the longest backtick run already in `text` guarantees no
    substring of `text` can terminate it, so `` `[x](evil)` `` can't break
    out mid-cell and render as a live link. A single padding space is added
    on each side when `text` starts or ends with a backtick, so the fence
    doesn't visually merge with it (also per CommonMark).
    """
    text = text.replace("|", "\\|")
    text = _normalize_newlines(text)

    longest_run = 0
    current_run = 0
    for ch in text:
        if ch == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0

    fence = "`" * (longest_run + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def escape_plain(text: str) -> str:
    """Escape a free-text value for a Markdown table cell with no code span.

    Backslash-escapes every Markdown metacharacter that could otherwise
    build structure out of attacker-influenced text: ``[``/``]``/``(``/``)``
    (link and image syntax), `` ` `` (a premature code span), and ``<``
    (a raw HTML tag opener, e.g. ``<img src=x onerror=...>``). Existing
    backslashes are doubled first so the escapes this function inserts
    can't be misread as already having been present in the source text.
    Newline normalisation runs last so the literal ``<br>`` it inserts
    isn't itself caught by the ``<`` escaping above.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    for ch in _STRUCTURAL_CHARS:
        text = text.replace(ch, "\\" + ch)
    return _normalize_newlines(text)
