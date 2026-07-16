"""Tests for router.py — classification and dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from linksanity.config import Config
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.router import classify, dispatch

# ── classify() ────────────────────────────────────────────────────────────────

class TestClassify:
    @pytest.mark.parametrize("url,expected", [
        # Pure anchors
        ("#section", LinkType.ANCHOR),
        ("#top", LinkType.ANCHOR),
        # External without fragment
        ("https://example.com/page", LinkType.EXTERNAL),
        ("http://example.com", LinkType.EXTERNAL),
        ("https://example.com/a/b/c", LinkType.EXTERNAL),
        # External with fragment
        ("https://example.com/page#section", LinkType.EXTERNAL_ANCHOR),
        ("http://docs.example.com/api#method", LinkType.EXTERNAL_ANCHOR),
        # Internal — relative paths
        ("./other.md", LinkType.INTERNAL),
        ("../sibling.rst", LinkType.INTERNAL),
        ("subdir/page.html", LinkType.INTERNAL),
        ("page.md", LinkType.INTERNAL),
        # Internal with fragment — still INTERNAL (filesystem checker handles fragment)
        ("./page.md#heading", LinkType.INTERNAL),
        ("../other.rst#target", LinkType.INTERNAL),
        # Non-checkable schemes — reported as skipped, not silently dropped (COV-04)
        ("mailto:test@example.com", LinkType.NON_HTTP_SCHEME),
        ("tel:+15551234567", LinkType.NON_HTTP_SCHEME),
        ("javascript:void(0)", LinkType.NON_HTTP_SCHEME),
        ("data:text/plain;base64,SGVsbG8=", LinkType.NON_HTTP_SCHEME),
    ])
    def test_classify(self, url: str, expected: LinkType) -> None:
        assert classify(url) == expected


# ── dispatch() — filesystem routes ───────────────────────────────────────────

class TestDispatchFilesystem:
    @pytest.fixture
    def config(self) -> Config:
        return Config()

    @pytest.fixture
    def sems(self) -> tuple:
        import asyncio
        return asyncio.Semaphore(5), asyncio.Semaphore(2)

    @pytest.mark.asyncio
    async def test_anchor_routes_to_filesystem(
        self, tmp_path: Path, config: Config, sems: tuple
    ) -> None:
        f = tmp_path / "page.md"
        f.write_text("# Hello\n")
        result = await dispatch(
            "#hello", str(f), 1, LinkType.ANCHOR, config, *sems
        )
        # Anchor in same file — exists
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_internal_valid_routes_to_filesystem(
        self, tmp_path: Path, config: Config, sems: tuple
    ) -> None:
        source = tmp_path / "index.md"
        source.write_text("[link](other.md)\n")
        (tmp_path / "other.md").write_text("# Other\n")
        result = await dispatch(
            "other.md", str(source), 1, LinkType.INTERNAL, config, *sems
        )
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_internal_missing_is_broken(
        self, tmp_path: Path, config: Config, sems: tuple
    ) -> None:
        source = tmp_path / "index.md"
        source.write_text("[link](missing.md)\n")
        result = await dispatch(
            "missing.md", str(source), 1, LinkType.INTERNAL, config, *sems
        )
        assert result.status == LinkStatus.BROKEN


# ── dispatch() — HTTP routes ──────────────────────────────────────────────────

class TestDispatchHTTP:
    @pytest.fixture
    def config(self) -> Config:
        return Config(timeout=5, retry=0)

    @pytest.fixture
    def sems(self) -> tuple:
        import asyncio
        return asyncio.Semaphore(5), asyncio.Semaphore(2)

    @pytest.mark.asyncio
    async def test_external_routes_to_http(
        self, config: Config, sems: tuple
    ) -> None:
        ok_result = LinkResult(
            source_file="f", line=1, url="https://example.com",
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK,
        )
        with patch(
            "linksanity.router.http.check", new_callable=AsyncMock, return_value=ok_result
        ):
            result = await dispatch(
                "https://example.com", "f", 1, LinkType.EXTERNAL, config, *sems
            )
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_external_anchor_routes_to_http(
        self, config: Config, sems: tuple
    ) -> None:
        ok_result = LinkResult(
            source_file="f", line=1, url="https://example.com/page#s",
            link_type=LinkType.EXTERNAL_ANCHOR, status=LinkStatus.OK,
        )
        with patch(
            "linksanity.router.http.check", new_callable=AsyncMock, return_value=ok_result
        ):
            result = await dispatch(
                "https://example.com/page#s", "f", 1,
                LinkType.EXTERNAL_ANCHOR, config, *sems,
            )
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_ignored_domain_skipped(
        self, sems: tuple
    ) -> None:
        config = Config(ignore_domains={"example.com"}, retry=0, timeout=5)
        result = await dispatch(
            "https://example.com/page", "f", 1, LinkType.EXTERNAL, config, *sems
        )
        assert result.status == LinkStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skip_urls_pattern_skipped(
        self, sems: tuple
    ) -> None:
        config = Config(skip_urls={"https://example.com/private/*"}, retry=0, timeout=5)
        result = await dispatch(
            "https://example.com/private/page", "f", 1, LinkType.EXTERNAL, config, *sems
        )
        assert result.status == LinkStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skip_urls_exact_match_skipped(
        self, sems: tuple
    ) -> None:
        config = Config(skip_urls={"https://example.com/login"}, retry=0, timeout=5)
        result = await dispatch(
            "https://example.com/login", "f", 1, LinkType.EXTERNAL, config, *sems
        )
        assert result.status == LinkStatus.SKIPPED


# ── dispatch() — non-HTTP schemes ─────────────────────────────────────────────

class TestDispatchNonHttpScheme:
    @pytest.fixture
    def config(self) -> Config:
        return Config()

    @pytest.fixture
    def sems(self) -> tuple:
        import asyncio
        return asyncio.Semaphore(5), asyncio.Semaphore(2)

    @pytest.mark.asyncio
    async def test_mailto_is_skipped_with_reason(
        self, config: Config, sems: tuple
    ) -> None:
        result = await dispatch(
            "mailto:test@example.com", "f", 1, LinkType.NON_HTTP_SCHEME, config, *sems
        )
        assert result.status == LinkStatus.SKIPPED
        assert result.error is not None
        assert "mailto" in result.error

    @pytest.mark.asyncio
    async def test_tel_is_skipped_with_reason(
        self, config: Config, sems: tuple
    ) -> None:
        result = await dispatch(
            "tel:+15551234567", "f", 1, LinkType.NON_HTTP_SCHEME, config, *sems
        )
        assert result.status == LinkStatus.SKIPPED
        assert result.error is not None
        assert "tel" in result.error


# ── dispatch() — Playwright route ─────────────────────────────────────────────

class TestDispatchPlaywright:
    @pytest.mark.asyncio
    async def test_js_domain_routes_to_playwright(self) -> None:
        import asyncio
        config = Config(js_domains={"spa.example.com"}, timeout=5)
        sems = asyncio.Semaphore(5), asyncio.Semaphore(2)
        ok_result = LinkResult(
            source_file="f", line=1, url="https://spa.example.com/page",
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK,
        )
        with patch(
            "linksanity.checkers.playwright.check",
            new_callable=AsyncMock,
            return_value=ok_result,
        ):
            result = await dispatch(
                "https://spa.example.com/page", "f", 1,
                LinkType.EXTERNAL, config, *sems,
            )
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_subdomain_js_domain_routes_to_playwright(self) -> None:
        import asyncio
        config = Config(js_domains={"example.com"}, timeout=5)
        sems = asyncio.Semaphore(5), asyncio.Semaphore(2)
        ok_result = LinkResult(
            source_file="f", line=1, url="https://docs.example.com/api",
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK,
        )
        with patch(
            "linksanity.checkers.playwright.check",
            new_callable=AsyncMock,
            return_value=ok_result,
        ):
            result = await dispatch(
                "https://docs.example.com/api", "f", 1,
                LinkType.EXTERNAL, config, *sems,
            )
        assert result.status == LinkStatus.OK


# ── dispatch() — cell forwarding ─────────────────────────────────────────────

class TestDispatchCellForwarding:
    @pytest.fixture
    def sems(self) -> tuple:
        import asyncio
        return asyncio.Semaphore(5), asyncio.Semaphore(2)

    @pytest.mark.asyncio
    async def test_cell_forwarded_to_filesystem(
        self, tmp_path: Path, sems: tuple
    ) -> None:
        f = tmp_path / "page.md"
        f.write_text("# Hello\n")
        result = await dispatch(
            "#hello", str(f), 1, LinkType.ANCHOR, Config(), *sems, cell=4
        )
        assert result.cell == 4

    @pytest.mark.asyncio
    async def test_cell_forwarded_to_http(self, sems: tuple) -> None:
        ok_result = LinkResult(
            source_file="f", line=1, url="https://example.com",
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK,
        )
        mock_check = AsyncMock(return_value=ok_result)
        with patch("linksanity.router.http.check", mock_check):
            await dispatch(
                "https://example.com", "f", 1, LinkType.EXTERNAL,
                Config(timeout=5, retry=0), *sems, cell=2,
            )
        assert mock_check.call_args.kwargs["cell"] == 2

    @pytest.mark.asyncio
    async def test_cell_forwarded_to_playwright(self, sems: tuple) -> None:
        config = Config(js_domains={"spa.example.com"}, timeout=5)
        ok_result = LinkResult(
            source_file="f", line=1, url="https://spa.example.com/page",
            link_type=LinkType.EXTERNAL, status=LinkStatus.OK,
        )
        mock_check = AsyncMock(return_value=ok_result)
        with patch("linksanity.checkers.playwright.check", mock_check):
            await dispatch(
                "https://spa.example.com/page", "f", 1,
                LinkType.EXTERNAL, config, *sems, cell=9,
            )
        assert mock_check.call_args.kwargs["cell"] == 9

    @pytest.mark.asyncio
    async def test_cell_set_on_skipped_result(self, sems: tuple) -> None:
        config = Config(skip_urls={"https://example.com/private/*"}, retry=0, timeout=5)
        result = await dispatch(
            "https://example.com/private/page", "f", 1,
            LinkType.EXTERNAL, config, *sems, cell=6,
        )
        assert result.status == LinkStatus.SKIPPED
        assert result.cell == 6

    @pytest.mark.asyncio
    async def test_cell_defaults_to_none(self, tmp_path: Path, sems: tuple) -> None:
        f = tmp_path / "page.md"
        f.write_text("# Hello\n")
        result = await dispatch(
            "#hello", str(f), 1, LinkType.ANCHOR, Config(), *sems
        )
        assert result.cell is None
