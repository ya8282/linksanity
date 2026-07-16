"""Extract links from Jupyter Notebook (.ipynb) markdown cells.

Only markdown cells are scanned. Code cells are never scanned for URLs --
even URL-looking strings in comments or string literals -- since that's
explicitly out of scope (high false-positive risk).

Unlike the other parsers in this package, extract_links here does not
return (url, line) pairs: it calls queue.add() directly per link, since
each link also carries a cell index that the shared parser interface
doesn't have room for.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from linksanity.parsers.markdown import parse_markdown_string
from linksanity.queue import LinkQueue
from linksanity.router import classify


def extract_links(path: Path, queue: LinkQueue) -> None:
    """Scan a notebook's markdown cells for links and register them on queue.

    Each markdown cell's source is run through parse_markdown_string()
    independently, so line numbers are relative to the start of that cell.
    Links are registered via queue.add(url, str(path), line, link_type,
    cell=cell_index) with a 1-based cell index (position in the notebook's
    top-level cells list). Code cells are skipped entirely.

    Malformed JSON or a notebook missing the top-level "cells" list emits a
    warning and adds nothing to the queue. Individual malformed cells are
    skipped rather than aborting the whole notebook.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=2)
        return

    try:
        notebook = json.loads(content)
    except json.JSONDecodeError as e:
        warnings.warn(f"[linksanity] invalid notebook JSON in {path}: {e}", stacklevel=2)
        return

    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        warnings.warn(f"[linksanity] {path} is not a valid notebook (missing cells)", stacklevel=2)
        return

    for cell_index, cell in enumerate(notebook["cells"], start=1):
        if not isinstance(cell, dict) or cell.get("cell_type") != "markdown":
            continue

        source = cell.get("source", "")
        if isinstance(source, list):
            cell_content = "".join(source)
        elif isinstance(source, str):
            cell_content = source
        else:
            continue

        try:
            links = parse_markdown_string(cell_content)
        except Exception as e:  # noqa: BLE001
            warnings.warn(
                f"[linksanity] markdown parse error in {path} cell {cell_index}: {e}",
                stacklevel=2,
            )
            continue

        for url, line in links:
            queue.add(url, str(path), line, classify(url), cell=cell_index)
