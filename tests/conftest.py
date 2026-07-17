"""Shared fixtures."""

from __future__ import annotations

import pytest

# Any public address will do; the guard only asks whether it is private.
PUBLIC_ADDR = "93.184.216.34"


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the resolver.

    The private-host guard resolves hostnames to catch names that answer with a
    private address, so without this every test that checks a URL would issue a
    real DNS query. Resolve to a public address by default; tests that care
    about resolution patch _resolve themselves. IP literals skip _resolve
    entirely, so they stay covered by the real code path.
    """

    async def _fake_resolve(hostname: str) -> list[str]:
        return [PUBLIC_ADDR]

    monkeypatch.setattr("linksanity.checkers.http._resolve", _fake_resolve)
