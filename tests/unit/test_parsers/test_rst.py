"""Tests for parsers/rst.py."""

import warnings
from pathlib import Path

import pytest

from linksanity.parsers.rst import extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.rst"


class TestExtractLinks:
    def test_extracts_inline_reference(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://example.com" in urls

    def test_extracts_broken_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://broken.example.com/does-not-exist" in urls

    def test_extracts_hyperlink_target(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://target.example.com" in urls

    def test_extracts_anonymous_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://anonymous.example.com" in urls

    def test_excludes_literal_block_content(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://in-literal.example.com" not in urls

    def test_includes_mailto_for_reporting(self, tmp_path: Path) -> None:
        # mailto: links are extracted; router.classify() reports them as
        # skipped rather than silently dropping them (COV-04).
        content = "`Email <mailto:test@example.com>`_"
        tmp = tmp_path / "test_mailto.rst"
        tmp.write_text(content)
        urls = [url for url, _ in extract_links(tmp)]
        assert any(u.startswith("mailto:") for u in urls)

    def test_returns_line_numbers(self) -> None:
        # Exact lines, not just "is an int": docutils leaves node.line None on
        # inline references, so `or 0` reported every link as line 0 while
        # isinstance(line, int) still passed.
        assert set(extract_links(SAMPLE)) == {
            ("https://example.com", 4),
            ("https://broken.example.com/does-not-exist", 5),
            ("https://target.example.com", 9),
            ("https://anonymous.example.com", 11),
        }

    def test_inline_link_not_duplicated(self) -> None:
        # One inline hyperlink produces both a reference and a target node in
        # docutils; each link must still be reported once.
        pairs = extract_links(SAMPLE)
        assert len(pairs) == len(set(pairs))

    def test_links_in_one_paragraph_get_own_lines(self, tmp_path: Path) -> None:
        # Both links live in a single paragraph, so docutils reports the
        # paragraph's start line for both.
        f = tmp_path / "para.rst"
        f.write_text("Intro\n\nFirst `a <https://a.com>`_ here.\nSecond `b <https://b.com>`_ here.\n")
        assert set(extract_links(f)) == {("https://a.com", 3), ("https://b.com", 4)}

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.rst"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.rst"
        f.write_text("")
        assert extract_links(f) == []

    @pytest.mark.parametrize("content,expected_url", [
        ("`Link <https://a.com>`_", "https://a.com"),
        (".. _named: https://b.com", "https://b.com"),
        ("`Anon <https://c.com>`__", "https://c.com"),
    ])
    def test_rst_link_variants(self, tmp_path: Path, content: str, expected_url: str) -> None:
        f = tmp_path / "test.rst"
        f.write_text(content)
        urls = [url for url, _ in extract_links(f)]
        assert expected_url in urls


class TestExtractImages:
    def test_image_excluded_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "test.rst"
        f.write_text(".. image:: ./photo.png\n")
        urls = [url for url, _ in extract_links(f)]
        assert "./photo.png" not in urls

    def test_image_included_when_requested(self, tmp_path: Path) -> None:
        f = tmp_path / "test.rst"
        f.write_text(".. image:: ./photo.png\n")
        urls = [url for url, _ in extract_links(f, include_images=True)]
        assert "./photo.png" in urls
