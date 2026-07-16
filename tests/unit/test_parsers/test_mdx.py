"""Tests for parsers/mdx.py."""

import warnings
from pathlib import Path

from linksanity.parsers.mdx import extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.mdx"


class TestExtractLinks:
    def test_extracts_inline_markdown_link(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://example.com", 3) in pairs

    def test_extracts_broken_markdown_link(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://broken.example.com/does-not-exist", 5) in pairs

    def test_extracts_jsx_to_attribute(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("/docs/getting-started", 7) in pairs

    def test_extracts_jsx_href_attribute(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://jsx-anchor.example.com", 9) in pairs

    def test_skips_jsx_expression_attribute(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert not any("dynamicUrl" in url for url in urls)
        assert "{dynamicUrl}" not in urls

    def test_returns_line_numbers(self) -> None:
        pairs = extract_links(SAMPLE)
        assert len(pairs) > 0
        assert all(isinstance(line, int) and line >= 1 for _, line in pairs)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.mdx"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.mdx"
        f.write_text("")
        assert extract_links(f) == []

    def test_jsx_href_double_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "test.mdx"
        f.write_text('<a href="https://double-quoted.example.com">Link</a>\n')
        urls = [url for url, _ in extract_links(f)]
        assert "https://double-quoted.example.com" in urls

    def test_jsx_to_single_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "test.mdx"
        f.write_text("<Link to='/single-quoted'>Link</Link>\n")
        urls = [url for url, _ in extract_links(f)]
        assert "/single-quoted" in urls

    def test_jsx_expression_attribute_skipped_without_error(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.mdx"
        f.write_text("<Link href={someVar}>Link</Link>\n")
        pairs = extract_links(f)
        assert pairs == []

    def test_no_double_count_when_both_mechanisms_match_same_line(
        self, tmp_path: Path
    ) -> None:
        # A CommonMark link and a JSX attribute pointing at the same URL
        # on the same line must be reported only once.
        f = tmp_path / "test.mdx"
        f.write_text(
            '[link](https://dup.example.com) <Something href="https://dup.example.com">\n'
        )
        pairs = extract_links(f)
        matches = [p for p in pairs if p == ("https://dup.example.com", 1)]
        assert len(matches) == 1

    def test_jsx_and_markdown_links_together(self, tmp_path: Path) -> None:
        content = (
            "[md link](https://md.example.com)\n"
            '<Nav to="https://jsx.example.com">Nav</Nav>\n'
        )
        f = tmp_path / "test.mdx"
        f.write_text(content)
        pairs = extract_links(f)
        assert ("https://md.example.com", 1) in pairs
        assert ("https://jsx.example.com", 2) in pairs
