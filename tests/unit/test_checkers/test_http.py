"""Tests for checkers/http.py — all network calls mocked via respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from linksanity.checkers.http import _domain_match, check
from linksanity.queue import LinkStatus, LinkType

SOURCE = "docs/index.md"
LINE = 5
URL = "https://example.com/page"


def make_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_file": SOURCE,
        "line": LINE,
        "link_type": LinkType.EXTERNAL,
        "timeout": 5,
        "retries": 0,
    }
    base.update(overrides)
    return base


# ── Status classification ─────────────────────────────────────────────────────

class TestStatusClassification:
    @pytest.mark.asyncio
    @respx.mock
    async def test_200_is_ok(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.OK
        assert result.http_code == 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_redirect_detected_by_final_url(self) -> None:
        # Simulate a redirect: original URL resolves to a different final URL
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(
            301, headers={"location": final_url}
        ))
        respx.head(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.REDIRECT
        assert result.resolved_url == final_url

    @pytest.mark.asyncio
    @respx.mock
    async def test_redirect_chain_includes_all_hops(self) -> None:
        mid_url = "https://example.com/mid"
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(301, headers={"location": mid_url}))
        respx.head(mid_url).mock(return_value=httpx.Response(302, headers={"location": final_url}))
        respx.head(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.REDIRECT
        assert result.redirect_chain == [URL, mid_url, final_url]

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_is_broken(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(404))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.BROKEN
        assert result.http_code == 404

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_is_broken(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(500))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.BROKEN


# ── GET fallback on 405 ───────────────────────────────────────────────────────

class TestGetFallback:
    @pytest.mark.asyncio
    @respx.mock
    async def test_405_falls_back_to_get(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(405))
        respx.get(URL).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.OK
        assert result.http_code == 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_405_get_returns_404(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(405))
        respx.get(URL).mock(return_value=httpx.Response(404))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.BROKEN


# ── Retry on 429 / 503 ───────────────────────────────────────────────────────

class TestRetry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_429_retries_and_succeeds(self) -> None:
        respx.head(URL).mock(side_effect=[
            httpx.Response(429),
            httpx.Response(200),
        ])
        result = await check(URL, **make_kwargs(retries=1))  # type: ignore[arg-type]
        assert result.status == LinkStatus.OK

    @pytest.mark.asyncio
    @respx.mock
    async def test_503_exhausts_retries(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(503))
        result = await check(URL, **make_kwargs(retries=1))  # type: ignore[arg-type]
        assert result.status == LinkStatus.BROKEN
        assert result.http_code == 503


# ── Too many redirects ────────────────────────────────────────────────────────

class TestTooManyRedirects:
    @pytest.mark.asyncio
    @respx.mock
    async def test_redirect_loop_flagged_distinct_from_broken(self) -> None:
        a, b = "https://example.com/a", "https://example.com/b"
        respx.head(URL).mock(return_value=httpx.Response(301, headers={"location": a}))
        respx.head(a).mock(return_value=httpx.Response(301, headers={"location": b}))
        respx.head(b).mock(return_value=httpx.Response(301, headers={"location": a}))
        result = await check(URL, **make_kwargs(max_redirects=2))  # type: ignore[arg-type]
        assert result.status == LinkStatus.TOO_MANY_REDIRECTS
        assert result.status != LinkStatus.BROKEN
        assert result.error is not None and "2" in result.error


# ── Ignore domains ────────────────────────────────────────────────────────────

class TestIgnoreDomains:
    @pytest.mark.asyncio
    async def test_ignored_domain_is_skipped(self) -> None:
        result = await check(
            URL, **make_kwargs(ignore_domains={"example.com"})  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_subdomain_is_matched(self) -> None:
        result = await check(
            "https://sub.example.com/path",
            **make_kwargs(ignore_domains={"example.com"})  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.SKIPPED

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_ignored_domain_is_checked(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(
            URL, **make_kwargs(ignore_domains={"other.com"})  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.OK


# ── Network errors ────────────────────────────────────────────────────────────

class TestNetworkErrors:
    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error_is_error_status(self) -> None:
        respx.head(URL).mock(side_effect=httpx.ConnectError("refused"))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.status == LinkStatus.ERROR
        assert result.error is not None


# ── Domain matching helper ────────────────────────────────────────────────────

class TestCellForwarding:
    @pytest.mark.asyncio
    @respx.mock
    async def test_cell_set_on_ok_result(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs(cell=3))  # type: ignore[arg-type]
        assert result.cell == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_cell_set_on_broken_result(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(404))
        result = await check(URL, **make_kwargs(cell=8))  # type: ignore[arg-type]
        assert result.cell == 8

    @pytest.mark.asyncio
    async def test_cell_set_on_skipped_result(self) -> None:
        result = await check(
            URL, **make_kwargs(ignore_domains={"example.com"}, cell=1)  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.SKIPPED
        assert result.cell == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_cell_set_on_network_error_result(self) -> None:
        respx.head(URL).mock(side_effect=httpx.ConnectError("refused"))
        result = await check(URL, **make_kwargs(cell=4))  # type: ignore[arg-type]
        assert result.status == LinkStatus.ERROR
        assert result.cell == 4

    @pytest.mark.asyncio
    async def test_cell_defaults_to_none(self) -> None:
        result = await check(
            URL, **make_kwargs(ignore_domains={"example.com"})  # type: ignore[arg-type]
        )
        assert result.cell is None


class TestDomainMatch:
    @pytest.mark.parametrize("domain,ignore_set,expected", [
        ("example.com", {"example.com"}, True),
        ("sub.example.com", {"example.com"}, True),
        ("deep.sub.example.com", {"example.com"}, True),
        ("notexample.com", {"example.com"}, False),
        ("example.org", {"example.com"}, False),
        ("example.com", set(), False),
    ])
    def test_domain_match(
        self, domain: str, ignore_set: set[str], expected: bool
    ) -> None:
        assert _domain_match(domain, ignore_set) == expected
