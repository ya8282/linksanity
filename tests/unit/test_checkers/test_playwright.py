"""Unit tests for checkers/playwright.py check() — browser mocked, no real launch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linksanity.checkers.playwright import check
from linksanity.queue import LinkStatus, LinkType

URL = "https://example.com/page"


def _mock_playwright_context(status: int | None = 200, resolved_url: str = URL) -> AsyncMock:
    """Build a mock async_playwright() context returning a fake browser/page/response."""
    response: MagicMock | None
    if status is None:
        response = None
    else:
        response = MagicMock()
        response.status = status

    page = AsyncMock()
    page.goto = AsyncMock(return_value=response)
    page.url = resolved_url

    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = MagicMock()
    pw.chromium = chromium

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=pw)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestCheckCellForwarding:
    @pytest.mark.asyncio
    async def test_cell_set_on_ok_result(self) -> None:
        ctx = _mock_playwright_context(status=200, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=3)
        assert result.status == LinkStatus.OK
        assert result.cell == 3

    @pytest.mark.asyncio
    async def test_cell_set_on_no_response_result(self) -> None:
        ctx = _mock_playwright_context(status=None)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=7)
        assert result.status == LinkStatus.ERROR
        assert result.error == "no response"
        assert result.cell == 7

    @pytest.mark.asyncio
    async def test_cell_set_on_broken_result(self) -> None:
        ctx = _mock_playwright_context(status=404, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL, cell=5)
        assert result.status == LinkStatus.BROKEN
        assert result.cell == 5

    @pytest.mark.asyncio
    async def test_cell_defaults_to_none(self) -> None:
        ctx = _mock_playwright_context(status=200, resolved_url=URL)
        with (
            patch("linksanity.checkers.playwright._require_playwright"),
            patch("playwright.async_api.async_playwright", return_value=ctx),
        ):
            result = await check(URL, "f", 1, LinkType.EXTERNAL)
        assert result.cell is None
