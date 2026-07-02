"""Tests for parsers/asciidoc.py."""

import warnings
from pathlib import Path

from linksanity.parsers.asciidoc import extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.adoc"


class TestExtractLinks:
    def test_extracts_link_macro(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://example.com", 3) in pairs

    def test_extracts_broken_link_macro(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://broken.example.com/does-not-exist", 5) in pairs

    def test_extracts_xref_target(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("chapter2.adoc", 7) in pairs

    def test_extracts_bare_autolink(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://bare.example.com", 9) in pairs

    def test_extracts_link_after_listing_block(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("https://after-listing.example.com", 20) in pairs

    def test_extracts_xref_after_passthrough_block(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("chapter3.adoc", 31) in pairs

    def test_excludes_listing_block_link_macro(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://in-listing.example.com" not in urls

    def test_excludes_listing_block_bare_autolink(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://bare-in-listing.example.com" not in urls

    def test_excludes_passthrough_block_link_macro(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://in-passthrough.example.com" not in urls

    def test_excludes_passthrough_block_bare_autolink(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://bare-in-passthrough.example.com" not in urls

    def test_returns_line_numbers(self) -> None:
        pairs = extract_links(SAMPLE)
        assert len(pairs) > 0
        assert all(isinstance(line, int) and line >= 1 for _, line in pairs)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.adoc"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.adoc"
        f.write_text("")
        assert extract_links(f) == []

    def test_listing_block_closes_and_reopens(self, tmp_path: Path) -> None:
        content = (
            "----\n"
            "link:https://skip-one.example.com[Skip]\n"
            "----\n"
            "link:https://keep.example.com[Keep]\n"
            "----\n"
            "link:https://skip-two.example.com[Skip]\n"
            "----\n"
        )
        f = tmp_path / "reopen.adoc"
        f.write_text(content)
        urls = [url for url, _ in extract_links(f)]
        assert urls == ["https://keep.example.com"]

    def test_link_macro_line_number_accuracy(self, tmp_path: Path) -> None:
        content = "\n\n\nlink:https://third-line-down.example.com[Link]\n"
        f = tmp_path / "lines.adoc"
        f.write_text(content)
        pairs = extract_links(f)
        assert ("https://third-line-down.example.com", 4) in pairs
