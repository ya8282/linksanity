"""Tests for parsers/markdown.py."""

import warnings
from pathlib import Path

import pytest

from linksanity.parsers.markdown import extract_links, parse_markdown_string

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

    def test_excludes_mailto(self) -> None:
        content = "Send [email](mailto:test@example.com) here."
        tmp = Path("/tmp/test_mailto.md")
        tmp.write_text(content)
        urls = [url for url, _ in extract_links(tmp)]
        assert not any(u.startswith("mailto:") for u in urls)

    def test_excludes_javascript(self) -> None:
        content = "Click [here](javascript:void(0))."
        tmp = Path("/tmp/test_js.md")
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

    def test_parse_error_warns_with_path_and_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import linksanity.parsers.markdown as markdown_module

        def boom(_content: str) -> list[tuple[str, int]]:
            raise ValueError("kaboom")

        monkeypatch.setattr(markdown_module, "parse_markdown_string", boom)
        f = tmp_path / "bad.md"
        f.write_text("some content")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(f)

        assert result == []
        assert len(w) == 1
        message = str(w[0].message)
        assert "markdown parse error" in message
        assert str(f) in message

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


class TestParseMarkdownString:
    def test_importable(self) -> None:
        """Verify parse_markdown_string is importable by other parsers."""
        assert callable(parse_markdown_string)

    def test_extracts_links_from_string(self) -> None:
        content = "[example](https://example.com)"
        pairs = parse_markdown_string(content)
        urls = [url for url, _ in pairs]
        assert "https://example.com" in urls

    def test_returns_line_numbers(self) -> None:
        content = "[first](https://first.com)\n\n[second](https://second.com)"
        pairs = parse_markdown_string(content)
        assert len(pairs) == 2
        assert pairs[0][1] == 1
        assert pairs[1][1] == 3

    def test_excludes_fenced_code_from_string(self) -> None:
        content = "```\n[nope](https://in-fence.com)\n```"
        pairs = parse_markdown_string(content)
        urls = [url for url, _ in pairs]
        assert "https://in-fence.com" not in urls

    def test_excludes_inline_code_from_string(self) -> None:
        content = "`[nope](https://in-code.com)`"
        pairs = parse_markdown_string(content)
        urls = [url for url, _ in pairs]
        assert "https://in-code.com" not in urls

    def test_empty_string_returns_empty(self) -> None:
        assert parse_markdown_string("") == []

    def test_no_links_returns_empty(self) -> None:
        content = "this is just text with no links"
        pairs = parse_markdown_string(content)
        assert pairs == []

    def test_parse_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import linksanity.parsers.markdown as markdown_module

        def boom(*_args: object, **_kwargs: object) -> list[object]:
            raise ValueError("kaboom")

        monkeypatch.setattr(markdown_module.MarkdownIt, "parse", boom)

        with pytest.raises(ValueError, match="kaboom"):
            parse_markdown_string("[a](https://a.com)")
