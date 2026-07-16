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
            "\n"
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

    # -- Bug 1: bare autolink regex swallows trailing sentence punctuation --

    def test_bare_autolink_strips_trailing_period(self, tmp_path: Path) -> None:
        f = tmp_path / "period.adoc"
        f.write_text("See https://example.com. It works.\n")
        urls = [url for url, _ in extract_links(f)]
        assert urls == ["https://example.com"]

    def test_bare_autolink_strips_trailing_paren(self, tmp_path: Path) -> None:
        f = tmp_path / "paren.adoc"
        f.write_text("(see https://example.com)\n")
        urls = [url for url, _ in extract_links(f)]
        assert urls == ["https://example.com"]

    def test_bare_autolink_strips_trailing_period_mid_sentence(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "midsentence.adoc"
        f.write_text("Visit https://example.com. Then visit https://other.example.com.\n")
        urls = [url for url, _ in extract_links(f)]
        assert urls == ["https://example.com", "https://other.example.com"]

    def test_bare_autolink_preserves_meaningful_trailing_chars(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "query.adoc"
        f.write_text("See https://example.com/page?id=1 for details.\n")
        urls = [url for url, _ in extract_links(f)]
        assert urls == ["https://example.com/page?id=1"]

    # -- Bug 2: listing-block delimiter collides with two-line headings --

    def test_setext_heading_underline_not_treated_as_listing_open(
        self, tmp_path: Path
    ) -> None:
        content = (
            "My Heading\n"
            "----------\n"
            "\n"
            "link:https://after-heading.example.com[After]\n"
        )
        f = tmp_path / "heading.adoc"
        f.write_text(content)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            pairs = extract_links(f)
        assert ("https://after-heading.example.com", 4) in pairs
        assert len(w) == 0

    def test_setext_heading_like_passthrough_underline_not_treated_as_open(
        self, tmp_path: Path
    ) -> None:
        content = (
            "Some Title\n"
            "++++\n"
            "\n"
            "link:https://after-plus-heading.example.com[After]\n"
        )
        f = tmp_path / "plusheading.adoc"
        f.write_text(content)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            pairs = extract_links(f)
        assert ("https://after-plus-heading.example.com", 4) in pairs
        assert len(w) == 0

    def test_listing_block_still_skipped_when_blank_line_precedes_open(
        self, tmp_path: Path
    ) -> None:
        content = (
            "Intro text.\n"
            "\n"
            "----\n"
            "link:https://in-block.example.com[Skip]\n"
            "----\n"
        )
        f = tmp_path / "realblock.adoc"
        f.write_text(content)
        urls = [url for url, _ in extract_links(f)]
        assert "https://in-block.example.com" not in urls

    # -- Bug 3: unterminated block silently swallows to EOF with no warning --

    def test_unterminated_listing_block_warns(self, tmp_path: Path) -> None:
        content = "----\nlink:https://swallowed.example.com[Swallowed]\n"
        f = tmp_path / "unterminated_listing.adoc"
        f.write_text(content)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            pairs = extract_links(f)
        urls = [url for url, _ in pairs]
        assert "https://swallowed.example.com" not in urls
        assert len(w) == 1
        assert "unterminated" in str(w[0].message)
        assert "listing" in str(w[0].message)

    def test_unterminated_passthrough_block_warns(self, tmp_path: Path) -> None:
        content = "++++\nlink:https://swallowed-pt.example.com[Swallowed]\n"
        f = tmp_path / "unterminated_passthrough.adoc"
        f.write_text(content)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            pairs = extract_links(f)
        urls = [url for url, _ in pairs]
        assert "https://swallowed-pt.example.com" not in urls
        assert len(w) == 1
        assert "unterminated" in str(w[0].message)
        assert "passthrough" in str(w[0].message)
