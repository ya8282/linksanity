"""Tests for checkers/http.py — all network calls mocked via respx."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from linksanity.checkers.http import _domain_match, _is_private_host, _resolve, check
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


# ── Normalization-only differences (no real HTTP hop) ─────────────────────────
# httpx normalizes the request URL (host casing, scheme casing, dot-segments)
# before it ever hits the wire. `resolved_url` reflects that normalized form
# even when zero redirect responses were received, so redirect detection must
# not compare `resolved_url` against `url` as strings — see `history` below.

class TestNormalizationOnlyDifference:
    @pytest.mark.asyncio
    @respx.mock
    async def test_uppercase_host_is_not_a_redirect(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(
            "https://EXAMPLE.com/page", **make_kwargs()  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert result.redirect_chain is None
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_uppercase_scheme_is_not_a_redirect(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(
            "HTTPS://example.com/page", **make_kwargs()  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert result.redirect_chain is None
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_dot_segment_path_is_not_a_redirect(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(
            "https://example.com/docs/../page", **make_kwargs()  # type: ignore[arg-type]
        )
        assert result.status == LinkStatus.OK
        assert result.resolved_url is None
        assert result.redirect_chain is None
        assert result.redirect_codes is None


# ── Redirect status codes ─────────────────────────────────────────────────────

class TestRedirectCodes:
    @pytest.mark.asyncio
    @respx.mock
    async def test_permanent_chain_captures_both_301s(self) -> None:
        mid_url = "https://example.com/mid"
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(301, headers={"location": mid_url}))
        respx.head(mid_url).mock(return_value=httpx.Response(301, headers={"location": final_url}))
        respx.head(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.redirect_codes == [301, 301]

    @pytest.mark.asyncio
    @respx.mock
    async def test_mixed_chain_preserves_hop_order(self) -> None:
        mid_url = "https://example.com/mid"
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(301, headers={"location": mid_url}))
        respx.head(mid_url).mock(return_value=httpx.Response(302, headers={"location": final_url}))
        respx.head(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.redirect_codes == [301, 302]

    @pytest.mark.asyncio
    @respx.mock
    async def test_single_308(self) -> None:
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(308, headers={"location": final_url}))
        respx.head(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.redirect_codes == [308]

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_redirect_leaves_codes_none(self) -> None:
        respx.head(URL).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.redirect_codes is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_codes_parallel_chain_on_get_fallback_path(self) -> None:
        # 405 on HEAD sends us down the streaming-GET branch, which builds
        # history separately — it must capture codes too.
        final_url = "https://example.com/canonical"
        respx.head(URL).mock(return_value=httpx.Response(405))
        respx.get(URL).mock(return_value=httpx.Response(301, headers={"location": final_url}))
        respx.get(final_url).mock(return_value=httpx.Response(200))
        result = await check(URL, **make_kwargs())  # type: ignore[arg-type]
        assert result.redirect_chain == [URL, final_url]
        assert result.redirect_codes == [301]


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


class TestPrivateHostGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("host", ["localhost", "LocalHost", "metadata.google.internal"])
    async def test_known_private_hostnames_are_blocked(self, host: str) -> None:
        assert await _is_private_host(host) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("host", [
        "127.0.0.1",        # loopback
        "10.0.0.1",         # private
        "192.168.1.1",      # private
        "172.16.0.1",       # private
        "169.254.169.254",  # link-local: cloud metadata
        "::1",              # ipv6 loopback
        "fe80::1",          # ipv6 link-local
    ])
    async def test_private_ip_literals_are_blocked(self, host: str) -> None:
        assert await _is_private_host(host) is True

    @pytest.mark.asyncio
    async def test_public_ip_literal_is_allowed(self) -> None:
        assert await _is_private_host("93.184.216.34") is False

    @pytest.mark.asyncio
    async def test_hostname_resolving_to_loopback_is_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The bypass this guard exists to stop: a public name (localtest.me,
        # *.nip.io) that answers with a loopback address.
        async def resolve(_host: str) -> list[str]:
            return ["127.0.0.1"]

        monkeypatch.setattr("linksanity.checkers.http._resolve", resolve)
        assert await _is_private_host("localtest.me") is True

    @pytest.mark.asyncio
    async def test_hostname_resolving_to_metadata_address_is_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def resolve(_host: str) -> list[str]:
            return ["169.254.169.254"]

        monkeypatch.setattr("linksanity.checkers.http._resolve", resolve)
        assert await _is_private_host("metadata.example.com") is True

    @pytest.mark.asyncio
    async def test_any_private_address_in_the_answer_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A name answering with both a public and a private address is still
        # a way into the private one.
        async def resolve(_host: str) -> list[str]:
            return ["93.184.216.34", "10.0.0.5"]

        monkeypatch.setattr("linksanity.checkers.http._resolve", resolve)
        assert await _is_private_host("split.example.com") is True

    @pytest.mark.asyncio
    async def test_public_hostname_is_allowed(self) -> None:
        assert await _is_private_host("example.com") is False

    @pytest.mark.asyncio
    async def test_unresolvable_hostname_is_allowed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Nothing to connect to: let the request fail and report the real error
        # rather than mislabelling it as private.
        async def resolve(_host: str) -> list[str]:
            return []

        monkeypatch.setattr("linksanity.checkers.http._resolve", resolve)
        assert await _is_private_host("no-such-host.invalid") is False

    @pytest.mark.asyncio
    async def test_check_skips_a_url_whose_host_resolves_to_private(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def resolve(_host: str) -> list[str]:
            return ["127.0.0.1"]

        monkeypatch.setattr("linksanity.checkers.http._resolve", resolve)
        result = await check("https://localtest.me/x", **make_kwargs())  # type: ignore[arg-type]
        assert result.status is LinkStatus.SKIPPED
        assert result.error == "skipped: private/loopback address"


class TestResolve:
    @pytest.mark.asyncio
    async def test_resolution_failure_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _resolve is stubbed suite-wide, so exercise the real one here.
        monkeypatch.undo()

        async def boom(*_a: object, **_k: object) -> list[object]:
            raise OSError("name or service not known")

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", boom)
        assert await _resolve("no-such-host.invalid") == []


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
