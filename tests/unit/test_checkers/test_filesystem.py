"""Tests for checkers/filesystem.py."""

from pathlib import Path

import pytest

from linksanity.checkers.filesystem import (
    _gh_slug,
    _html_ids,
    _md_anchors,
    _rst_anchors,
    check,
)
from linksanity.queue import LinkStatus, LinkType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


# ── Helpers ──────────────────────────────────────────────────────────────────

class TestGhSlug:
    @pytest.mark.parametrize("text,expected", [
        ("Hello World", "hello-world"),
        ("Hello, World!", "hello-world"),
        ("My Section 2", "my-section-2"),
        ("  spaces  ", "spaces"),
        ("CamelCase", "camelcase"),
        ("with_underscore", "with_underscore"),
    ])
    def test_slug(self, text: str, expected: str) -> None:
        assert _gh_slug(text) == expected


class TestMdAnchors:
    def test_atx_headings(self) -> None:
        content = "# Heading One\n## Sub Heading\n### Level Three\n"
        anchors = _md_anchors(content)
        assert "heading-one" in anchors
        assert "sub-heading" in anchors
        assert "level-three" in anchors

    def test_ignores_non_headings(self) -> None:
        content = "Just a paragraph\n- list item\n"
        assert _md_anchors(content) == set()


class TestRstAnchors:
    def test_section_ids(self) -> None:
        content = "Hello World\n===========\n\nSub Section\n-----------\n"
        anchors = _rst_anchors(content)
        assert "hello-world" in anchors
        assert "sub-section" in anchors


# ── check() ──────────────────────────────────────────────────────────────────

class TestCheckInternal:
    def test_existing_file_is_ok(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "other.md"
        src.write_text("# Index")
        target.write_text("# Other")

        result = check("./other.md", str(src), 1, LinkType.INTERNAL)
        assert result.status == LinkStatus.OK

    def test_missing_file_is_broken(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        src.write_text("# Index")

        result = check("./missing.md", str(src), 1, LinkType.INTERNAL)
        assert result.status == LinkStatus.BROKEN
        assert result.error is not None

    def test_parent_directory_traversal(self, tmp_path: Path) -> None:
        subdir = tmp_path / "docs"
        subdir.mkdir()
        src = subdir / "page.md"
        target = tmp_path / "README.md"
        src.write_text("# Page")
        target.write_text("# Root")

        result = check("../README.md", str(src), 1, LinkType.INTERNAL)
        assert result.status == LinkStatus.OK


class TestCheckAnchor:
    def test_valid_anchor_in_same_file(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.md"
        src.write_text("# Introduction\n\nSome text.\n")

        result = check("#introduction", str(src), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.OK

    def test_broken_anchor_in_same_file(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.md"
        src.write_text("# Introduction\n\nSome text.\n")

        result = check("#nonexistent", str(src), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.BROKEN
        assert result.error is not None

    def test_anchor_check_disabled_by_default(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.md"
        src.write_text("# Introduction\n")

        result = check("#nonexistent", str(src), 1, LinkType.ANCHOR, check_anchors=False)
        assert result.status == LinkStatus.OK

    def test_cross_file_anchor(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "other.md"
        src.write_text("# Index")
        target.write_text("# Real Section\n\nContent.\n")

        result = check(
            "./other.md#real-section", str(src), 1,
            LinkType.INTERNAL, check_anchors=True,
        )
        assert result.status == LinkStatus.OK

    def test_cross_file_broken_anchor(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "other.md"
        src.write_text("# Index")
        target.write_text("# Real Section\n")

        result = check(
            "./other.md#ghost-section", str(src), 1,
            LinkType.INTERNAL, check_anchors=True,
        )
        assert result.status == LinkStatus.BROKEN


class TestHtmlIds:
    def test_finds_id_attributes(self) -> None:
        content = '<div id="section-1"><p id="para">text</p></div>'
        ids = _html_ids(content)
        assert "section-1" in ids
        assert "para" in ids

    def test_ignores_class_attributes(self) -> None:
        assert _html_ids('<div class="intro">x</div>') == set()

    def test_empty_content(self) -> None:
        assert _html_ids("") == set()

    def test_single_quotes(self) -> None:
        assert "my-id" in _html_ids("<div id='my-id'>x</div>")


class TestRstAnchorsEdgeCases:
    def test_empty_string_returns_empty_set(self) -> None:
        assert isinstance(_rst_anchors(""), set)

    def test_hyperlink_target_id(self) -> None:
        content = ".. _my-target:\n\nSome text.\n"
        anchors = _rst_anchors(content)
        assert "my-target" in anchors


class TestAnchorExistsViaCheck:
    def test_rst_valid_anchor_is_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.rst"
        f.write_text("Section\n=======\n\nContent.\n")
        result = check("#section", str(f), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.OK

    def test_rst_broken_anchor_is_broken(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.rst"
        f.write_text("Section\n=======\n\nContent.\n")
        result = check("#ghost", str(f), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.BROKEN

    def test_html_valid_id_is_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "page.html"
        f.write_text('<html><body><section id="intro">x</section></body></html>')
        result = check("#intro", str(f), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.OK

    def test_html_broken_id_is_broken(self, tmp_path: Path) -> None:
        f = tmp_path / "page.html"
        f.write_text('<html><body><section id="intro">x</section></body></html>')
        result = check("#ghost", str(f), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.BROKEN

    def test_unknown_extension_anchor_is_broken(self, tmp_path: Path) -> None:
        # .txt has no anchor extractor → _anchor_exists returns False → BROKEN
        f = tmp_path / "notes.txt"
        f.write_text("some content")
        result = check("#section", str(f), 1, LinkType.ANCHOR, check_anchors=True)
        assert result.status == LinkStatus.BROKEN

    def test_unreadable_file_anchor_is_broken(self, tmp_path: Path) -> None:
        f = tmp_path / "locked.md"
        f.write_text("# Section\n")
        f.chmod(0o000)
        try:
            result = check("#section", str(f), 1, LinkType.ANCHOR, check_anchors=True)
            assert result.status == LinkStatus.BROKEN
        finally:
            f.chmod(0o644)


class TestLinkStylePresets:
    def test_mkdocs_extensionless_link_resolves(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "guide.md"
        src.write_text("# Index")
        target.write_text("# Guide")

        result = check("./guide", str(src), 1, LinkType.INTERNAL, link_style="mkdocs")
        assert result.status == LinkStatus.OK

    def test_mkdocs_directory_link_resolves_to_index(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        (tmp_path / "guide").mkdir()
        target = tmp_path / "guide" / "index.md"
        src.write_text("# Index")
        target.write_text("# Guide")

        result = check("./guide/", str(src), 1, LinkType.INTERNAL, link_style="mkdocs")
        assert result.status == LinkStatus.OK

    def test_docusaurus_extensionless_link_resolves(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "guide.mdx"
        src.write_text("# Index")
        target.write_text("# Guide")

        result = check("./guide", str(src), 1, LinkType.INTERNAL, link_style="docusaurus")
        assert result.status == LinkStatus.OK

    def test_sphinx_html_link_resolves_to_rst(self, tmp_path: Path) -> None:
        src = tmp_path / "index.rst"
        target = tmp_path / "guide.rst"
        src.write_text("Index\n=====\n")
        target.write_text("Guide\n=====\n")

        result = check("./guide.html", str(src), 1, LinkType.INTERNAL, link_style="sphinx")
        assert result.status == LinkStatus.OK

    def test_no_preset_still_broken(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        target = tmp_path / "guide.md"
        src.write_text("# Index")
        target.write_text("# Guide")

        result = check("./guide", str(src), 1, LinkType.INTERNAL)
        assert result.status == LinkStatus.BROKEN

    def test_preset_does_not_mask_truly_broken_link(self, tmp_path: Path) -> None:
        src = tmp_path / "index.md"
        src.write_text("# Index")

        result = check("./nowhere", str(src), 1, LinkType.INTERNAL, link_style="mkdocs")
        assert result.status == LinkStatus.BROKEN


class TestCheckResultFields:
    def test_result_preserves_source_and_line(self, tmp_path: Path) -> None:
        src = tmp_path / "a.md"
        src.write_text("")
        result = check("./missing.md", str(src), 42, LinkType.INTERNAL)
        assert result.source_file == str(src)
        assert result.line == 42
        assert result.url == "./missing.md"
