"""Tests for parsers/docbook.py."""

import warnings
from pathlib import Path

from linksanity.parsers.docbook import extract_ids, extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample-docbook.xml"
NONDOCBOOK = FIXTURES / "sample-nondocbook.xml"


class TestExtractLinks:
    def test_extracts_ulink(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://example.com/docs" in urls

    def test_extracts_link_xlink_href(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://example.com/other" in urls

    def test_extracts_xref_as_sentinel(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "docbook-xref:setup-section" in urls

    def test_ulink_line_number(self) -> None:
        pairs = extract_links(SAMPLE)
        line = dict((url, line) for url, line in pairs)["https://example.com/docs"]
        assert line == 10

    def test_link_line_number(self) -> None:
        pairs = extract_links(SAMPLE)
        line = dict((url, line) for url, line in pairs)["https://example.com/other"]
        assert line == 13

    def test_xref_line_number(self) -> None:
        pairs = extract_links(SAMPLE)
        line = dict((url, line) for url, line in pairs)["docbook-xref:setup-section"]
        assert line == 16

    def test_returns_line_numbers(self) -> None:
        pairs = extract_links(SAMPLE)
        assert len(pairs) > 0
        assert all(isinstance(line, int) and line >= 1 for _, line in pairs)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.xml"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_nondocbook_root_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(NONDOCBOOK)
        assert result == []
        assert len(w) == 1
        message = str(w[0].message)
        assert "[linksanity]" in message
        assert "not a DocBook" in message

    def test_malformed_xml_warns_and_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "malformed.xml"
        f.write_text("<article><unclosed>")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(f)
        assert result == []
        assert len(w) == 1
        message = str(w[0].message)
        assert "[linksanity]" in message
        assert "parse error" in message

    def test_empty_file_warns_and_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.xml"
        f.write_text("")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(f)
        assert result == []
        assert len(w) == 1


class TestExtractIds:
    def test_collects_xml_id(self) -> None:
        ids = extract_ids(SAMPLE)
        assert "intro" in ids

    def test_collects_id(self) -> None:
        ids = extract_ids(SAMPLE)
        assert "setup-section" in ids

    def test_returns_set(self) -> None:
        assert isinstance(extract_ids(SAMPLE), set)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_ids(Path("/nonexistent/path.xml"))
        assert result == set()
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_nondocbook_root_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_ids(NONDOCBOOK)
        assert result == set()
        assert len(w) == 1
        message = str(w[0].message)
        assert "not a DocBook" in message

    def test_malformed_xml_warns_and_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "malformed.xml"
        f.write_text("<book><unclosed>")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_ids(f)
        assert result == set()
        assert len(w) == 1
        assert "parse error" in str(w[0].message)
