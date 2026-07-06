"""Tests for parsers/markdown.py."""

import warnings
from pathlib import Path

import pytest

from linksanity.parsers.markdown import extract_links

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample.md"


class TestExtractLinks:
    def test_extracts_inline_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://example.com" in urls

    def test_extracts_broken_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://broken.example.com/does-not-exist" in urls

    def test_extracts_internal_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "./other.md" in urls

    def test_extracts_anchor_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "#section" in urls

    def test_extracts_reference_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://reference.example.com" in urls

    def test_extracts_blockquote_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://blockquote.example.com" in urls

    def test_extracts_list_link(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://list.example.com" in urls

    def test_excludes_fenced_code_block(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://in-fence.example.com" not in urls

    def test_excludes_inline_code_span(self) -> None:
        urls = [url for url, _ in extract_links(SAMPLE)]
        assert "https://in-code-span.example.com" not in urls

    def test_includes_mailto_for_reporting(self, tmp_path: Path) -> None:
        # mailto: links are extracted; router.classify() reports them as
        # skipped rather than silently dropping them (COV-04).
        content = "Send [email](mailto:test@example.com) here."
        tmp = tmp_path / "test_mailto.md"
        tmp.write_text(content)
        urls = [url for url, _ in extract_links(tmp)]
        assert any(u.startswith("mailto:") for u in urls)

    def test_javascript_scheme_rejected_by_markdown_it(self, tmp_path: Path) -> None:
        # markdown-it-py's validateLink refuses javascript: as an XSS-safety
        # default — it never becomes a link token, so there's nothing to
        # report. This is intentionally left as-is (COV-04 only concerns
        # schemes the parser does surface, e.g. mailto:/tel:).
        content = "Click [here](javascript:void(0))."
        tmp = tmp_path / "test_js.md"
        tmp.write_text(content)
        urls = [url for url, _ in extract_links(tmp)]
        assert not any(u.startswith("javascript:") for u in urls)

    def test_returns_line_numbers(self) -> None:
        pairs = extract_links(SAMPLE)
        lines = [line for _, line in pairs]
        assert all(isinstance(line, int) and line >= 1 for line in lines)

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.md"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("")
        assert extract_links(f) == []

    @pytest.mark.parametrize("content,expected_url", [
        ("[a](https://a.com)", "https://a.com"),
        ("[b](https://b.com 'title')", "https://b.com"),
        ("<https://autolink.com>", "https://autolink.com"),
    ])
    def test_link_variants(self, tmp_path: Path, content: str, expected_url: str) -> None:
        f = tmp_path / "test.md"
        f.write_text(content)
        urls = [url for url, _ in extract_links(f)]
        assert expected_url in urls


class TestExtractImages:
    def test_image_excluded_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("![alt text](./photo.png)")
        urls = [url for url, _ in extract_links(f)]
        assert "./photo.png" not in urls

    def test_image_included_when_requested(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("![alt text](./photo.png)")
        urls = [url for url, _ in extract_links(f, include_images=True)]
        assert "./photo.png" in urls
