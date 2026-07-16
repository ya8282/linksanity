"""Tests for parsers/myst.py and the myst config flag / scanner wiring."""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from linksanity.config import Config
from linksanity.parsers.myst import extract_links, extract_roles
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.scanner import run_scan

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample-myst.md"


def _mock_dispatch() -> AsyncMock:
    mock = AsyncMock()
    mock.side_effect = lambda url, src, line, lt, *a, **kw: LinkResult(
        source_file=src, line=line, url=url, link_type=lt, status=LinkStatus.OK,
    )
    return mock


class TestExtractRoles:
    def test_extracts_doc_role(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("installation-guide", 5) in pairs

    def test_extracts_ref_role(self) -> None:
        pairs = extract_links(SAMPLE)
        assert ("quickstart-label", 7) in pairs

    def test_no_false_positives_on_prose(self) -> None:
        # sample-myst.md has a paragraph that names "doc" and "ref" roles,
        # a Python dict literal, and an unrelated code span -- none of that
        # is genuine role syntax and must not be extracted.
        pairs = extract_links(SAMPLE)
        assert len(pairs) == 3  # doc, ref, and the after-fence ref only

    def test_skips_role_syntax_inside_fenced_code_block(self) -> None:
        targets = [t for t, _ in extract_links(SAMPLE)]
        assert "fenced-example" not in targets

    def test_extracts_role_after_fenced_code_block(self) -> None:
        # Proves the fence-tracking state resets on close.
        pairs = extract_links(SAMPLE)
        assert ("after-fence-label", 17) in pairs

    def test_requires_no_space_between_brace_and_backtick(self) -> None:
        assert extract_roles("{doc} `spaced-target`\n") == []

    def test_only_doc_and_ref_role_names_match(self) -> None:
        assert extract_roles("{other}`not-a-role`\n") == []

    def test_missing_file_warns_and_returns_empty(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = extract_links(Path("/nonexistent/path.md"))
        assert result == []
        assert len(w) == 1
        assert "cannot read" in str(w[0].message)

    def test_empty_content_returns_empty(self) -> None:
        assert extract_roles("") == []


class TestConfigFlag:
    def test_myst_defaults_to_false(self) -> None:
        assert Config().myst is False

    def test_myst_toml_override(self, tmp_path: Path) -> None:
        from linksanity.config import load_config

        toml = tmp_path / "linksanity.toml"
        toml.write_text("myst = true\n")
        assert load_config(toml_path=toml).myst is True

    def test_myst_cli_override(self, tmp_path: Path) -> None:
        from linksanity.config import load_config

        cfg = load_config(toml_path=tmp_path / "none.toml", myst=True)
        assert cfg.myst is True


class TestScannerFlagThreading:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("myst_enabled", [True, False])
    async def test_role_target_extraction_follows_myst_flag(
        self, tmp_path: Path, myst_enabled: bool
    ) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("See {doc}`some-target` for details.\n")
        config = Config(myst=myst_enabled)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(doc)], config)

        urls = {r.url for r in queue.results()}
        assert ("some-target" in urls) is myst_enabled

    @pytest.mark.asyncio
    async def test_role_target_classified_internal_when_enabled(
        self, tmp_path: Path
    ) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("See {ref}`quickstart-label` for details.\n")
        config = Config(myst=True)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(doc)], config)

        matches = [r for r in queue.results() if r.url == "quickstart-label"]
        assert len(matches) == 1
        assert matches[0].link_type == LinkType.INTERNAL

    @pytest.mark.asyncio
    async def test_myst_off_by_default_leaves_md_scan_unchanged(
        self, tmp_path: Path
    ) -> None:
        # Default Config() has myst=False -- a .md file mixing a normal
        # CommonMark link with role-shaped text must extract only the
        # CommonMark link, proving the default .md path is a byte-for-byte
        # no-op regardless of role-like content in the file.
        doc = tmp_path / "index.md"
        doc.write_text(
            "[a link](https://example.com)\n\nSee {doc}`some-target` too.\n"
        )
        config = Config()

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(doc)], config)

        urls = {r.url for r in queue.results()}
        assert urls == {"https://example.com"}
