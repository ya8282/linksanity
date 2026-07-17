"""Tests for parsers/html.py."""

import warnings
from pathlib import Path

import pytest

from linksanity.parsers.html import extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.html"


class TestExtractLinks:
    def test_extracts_external_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://example.com" in urls

    def test_extracts_broken_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://broken.example.com/does-not-exist" in urls

    def test_extracts_internal_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "./other.html" in urls

    def test_extracts_anchor_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "#section" in urls

    def test_includes_mailto_for_reporting(self) -> None:
        # mailto: links are extracted; router.classify() reports them as
        # skipped rather than silently dropping them (COV-04).
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert any(u.startswith("mailto:") for u in urls)

    def test_includes_javascript_for_reporting(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert any(u.startswith("javascript:") for u in urls)

    def test_excludes_empty_href(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "" not in urls

    def test_excludes_missing_href(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        # <a> with no href should not appear
        assert all(u for u in urls)

    def test_returns_line_numbers(self) -> None:
        # Exact lines, not just "is an int": line 0 is an int and satisfies
        # line >= 0, so a weaker assertion passes while every link is
        # misreported and the fixer silently skips the file.
        assert extract_links(SAMPLE) == [
            ("https://example.com", 5),
            ("https://broken.example.com/does-not-exist", 6),
            ("./other.html", 7),
            ("#section", 8),
            ("mailto:test@example.com", 9),
            ("javascript:void(0)", 10),
            ("https://in-code-tag.example.com", 13),
            ("https://line14.example.com", 14),
        ]

    def test_line_numbers_are_positive(self) -> None:
        pairs = extract_links(SAMPLE)
        assert all(line >= 1 for _, line in pairs)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.html"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.html"
        f.write_text("")
        assert extract_links(f) == []

    @pytest.mark.parametrize("href,expected_in_results", [
        ("https://good.com", True),
        ("#anchor", True),
        ("./relative.html", True),
        ("mailto:x@y.com", True),
        ("javascript:void(0)", True),
        ("", False),
    ])
    def test_href_filtering(
        self, tmp_path: Path, href: str, expected_in_results: bool
    ) -> None:
        f = tmp_path / "test.html"
        f.write_text(f'<html><body><a href="{href}">link</a></body></html>')
        urls = [url for url, _ in extract_links(f)]
        assert (href in urls) == expected_in_results


class TestExtractImages:
    def test_img_src_excluded_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "test.html"
        f.write_text('<html><body><img src="./photo.png"></body></html>')
        urls = [url for url, _ in extract_links(f)]
        assert "./photo.png" not in urls

    def test_img_src_included_when_requested(self, tmp_path: Path) -> None:
        f = tmp_path / "test.html"
        f.write_text('<html><body><img src="./photo.png"></body></html>')
        urls = [url for url, _ in extract_links(f, include_images=True)]
        assert "./photo.png" in urls

    def test_img_without_src_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "test.html"
        f.write_text('<html><body><img alt="no src"></body></html>')
        urls = [url for url, _ in extract_links(f, include_images=True)]
        assert urls == []
