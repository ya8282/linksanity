"""Tests for parsers/notebook.py."""

import json
import warnings
from pathlib import Path
from unittest.mock import patch

from linksanity.parsers.markdown import parse_markdown_string
from linksanity.parsers.notebook import extract_links
from linksanity.queue import LinkQueue

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.ipynb"


def _pending_by_url(queue: LinkQueue) -> dict:
    return {url: (source, line, link_type, cell) for url, source, line, link_type, cell in queue.pending()}


class TestExtractLinks:
    def test_extracts_link_from_markdown_cell(self) -> None:
        queue = LinkQueue()
        extract_links(SAMPLE, queue)
        pending = _pending_by_url(queue)
        assert "https://example.com/docs" in pending

    def test_code_cell_never_scanned(self) -> None:
        queue = LinkQueue()
        extract_links(SAMPLE, queue)
        pending = _pending_by_url(queue)
        assert "https://code-comment.example.com/should-not-be-scanned" not in pending
        assert "https://code-string.example.com/also-not-scanned" not in pending

    def test_cell_index_is_one_based_and_correct(self) -> None:
        queue = LinkQueue()
        extract_links(SAMPLE, queue)
        pending = _pending_by_url(queue)
        # first markdown cell is cell 1 (code cell in between is cell 2, not scanned)
        _, _, _, cell = pending["https://example.com/docs"]
        assert cell == 1
        # second markdown cell is cell 3
        _, _, _, cell = pending["https://broken.example.com/does-not-exist"]
        assert cell == 3

    def test_line_number_is_within_cell(self) -> None:
        queue = LinkQueue()
        extract_links(SAMPLE, queue)
        pending = _pending_by_url(queue)
        # "See the [docs](...)" is line 3 within its own cell's source
        _, line, _, _ = pending["https://example.com/docs"]
        assert line == 3
        # broken link is on line 7 within its cell (non-trivial position)
        _, line, _, _ = pending["https://broken.example.com/does-not-exist"]
        assert line == 7

    def test_source_as_single_string(self, tmp_path: Path) -> None:
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": "line one\n\n[a link](https://single-string.example.com)\n",
                }
            ],
        }
        f = tmp_path / "single_string.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()
        extract_links(f, queue)
        pending = _pending_by_url(queue)
        assert "https://single-string.example.com" in pending
        _, line, _, cell = pending["https://single-string.example.com"]
        assert line == 3
        assert cell == 1

    def test_source_as_list_of_strings(self, tmp_path: Path) -> None:
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["line one\n", "\n", "[a link](https://list-string.example.com)\n"],
                }
            ],
        }
        f = tmp_path / "list_string.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()
        extract_links(f, queue)
        pending = _pending_by_url(queue)
        assert "https://list-string.example.com" in pending
        _, line, _, cell = pending["https://list-string.example.com"]
        assert line == 3

    def test_malformed_json_warns_and_adds_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.ipynb"
        f.write_text("{not valid json")
        queue = LinkQueue()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            extract_links(f, queue)
        assert queue.pending() == []
        assert len(w) == 1
        assert "invalid notebook JSON" in str(w[0].message)

    def test_missing_cells_key_warns_and_adds_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "no_cells.ipynb"
        f.write_text(json.dumps({"nbformat": 4}))
        queue = LinkQueue()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            extract_links(f, queue)
        assert queue.pending() == []
        assert len(w) == 1
        assert "not a valid notebook" in str(w[0].message)

    def test_missing_file_warns_and_adds_nothing(self) -> None:
        queue = LinkQueue()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            extract_links(Path("/nonexistent/path.ipynb"), queue)
        assert queue.pending() == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_no_markdown_cells_adds_nothing(self, tmp_path: Path) -> None:
        notebook = {
            "cells": [
                {"cell_type": "code", "source": ["x = 1\n"]},
            ],
        }
        f = tmp_path / "code_only.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()
        extract_links(f, queue)
        assert queue.pending() == []

    def test_does_not_raise_on_malformed_cell(self, tmp_path: Path) -> None:
        notebook = {
            "cells": [
                "not a dict",
                {"cell_type": "markdown", "source": "[ok](https://after-malformed.example.com)\n"},
            ],
        }
        f = tmp_path / "malformed_cell.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()
        extract_links(f, queue)
        pending = _pending_by_url(queue)
        assert "https://after-malformed.example.com" in pending

    def test_source_field_wrong_type_skips_cell_not_whole_notebook(
        self, tmp_path: Path
    ) -> None:
        # A markdown cell whose "source" is neither a list nor a str (e.g. a
        # malformed int or null) is skipped via the `else: continue` branch,
        # while later valid cells still get scanned.
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": 123},
                {"cell_type": "markdown", "source": None},
                {
                    "cell_type": "markdown",
                    "source": "[ok](https://after-bad-source.example.com)\n",
                },
            ],
        }
        f = tmp_path / "bad_source_type.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            extract_links(f, queue)
        pending = _pending_by_url(queue)
        assert "https://after-bad-source.example.com" in pending
        assert len(pending) == 1
        assert len(w) == 0  # skipping a malformed source is silent, not a warning

    def test_per_cell_parse_error_skips_only_that_cell(self, tmp_path: Path) -> None:
        # parse_markdown_string() raising for one cell must not abort the
        # whole notebook -- forced via a mock, since real markdown content
        # is unlikely to trigger this defensive `except Exception` branch
        # naturally.
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": "[first](https://first.example.com)\n",
                },
                {
                    "cell_type": "markdown",
                    "source": "[second](https://second.example.com)\n",
                },
            ],
        }
        f = tmp_path / "per_cell_error.ipynb"
        f.write_text(json.dumps(notebook))
        queue = LinkQueue()

        def _fail_on_first_cell(content: str) -> list[tuple[str, int]]:
            if "first" in content:
                raise RuntimeError("boom")
            return parse_markdown_string(content)

        with (
            patch(
                "linksanity.parsers.notebook.parse_markdown_string",
                side_effect=_fail_on_first_cell,
            ),
            warnings.catch_warnings(record=True) as w,
        ):
            warnings.simplefilter("always")
            extract_links(f, queue)

        pending = _pending_by_url(queue)
        assert "https://first.example.com" not in pending
        assert "https://second.example.com" in pending
        assert len(w) == 1
        assert "markdown parse error" in str(w[0].message)
        assert "cell 1" in str(w[0].message)
