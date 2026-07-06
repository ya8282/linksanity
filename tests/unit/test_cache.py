"""Tests for cache.py — JSON cache of URL -> check result with TTL expiry."""

from __future__ import annotations

import json
import time
from pathlib import Path

from linksanity.cache import Cache
from linksanity.queue import LinkResult, LinkStatus, LinkType


def _result(**overrides: object) -> LinkResult:
    defaults: dict[str, object] = {
        "source_file": "docs/index.md",
        "line": 3,
        "url": "https://example.com/page",
        "link_type": LinkType.EXTERNAL,
        "status": LinkStatus.OK,
        "http_code": 200,
    }
    defaults.update(overrides)
    return LinkResult(**defaults)  # type: ignore[arg-type]


class TestMissAndHit:
    def test_get_missing_url_returns_none(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "cache.json", ttl=3600)
        assert cache.get("https://never-cached.com") is None

    def test_put_then_get_returns_result(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "cache.json", ttl=3600)
        r = _result()
        cache.put(r)
        hit = cache.get(r.url)
        assert hit is not None
        assert hit.status == LinkStatus.OK
        assert hit.http_code == 200


class TestPersistence:
    def test_save_writes_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.put(_result())
        cache.save(last_commit="abc123")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["last_commit"] == "abc123"
        assert "https://example.com/page" in data["urls"]

    def test_reload_from_disk_returns_same_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.put(_result())
        cache.save()

        reloaded = Cache(path, ttl=3600)
        hit = reloaded.get("https://example.com/page")
        assert hit is not None
        assert hit.status == LinkStatus.OK

    def test_last_commit_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.save(last_commit="deadbeef")

        reloaded = Cache(path, ttl=3600)
        assert reloaded.last_commit == "deadbeef"

    def test_missing_file_starts_empty(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "does-not-exist.json", ttl=3600)
        assert cache.get("https://example.com") is None
        assert cache.last_commit is None

    def test_corrupt_file_starts_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text("not json{{{")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com") is None


class TestTtlExpiry:
    def test_fresh_entry_is_returned(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "cache.json", ttl=3600)
        cache.put(_result())
        assert cache.get("https://example.com/page") is not None

    def test_expired_entry_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        payload = {
            "urls": {
                "https://example.com/page": {
                    "source_file": "docs/index.md",
                    "line": 3,
                    "link_type": "external",
                    "status": "ok",
                    "http_code": 200,
                    "resolved_url": None,
                    "error": None,
                    "redirect_chain": None,
                    "checked_at": time.time() - 7200,
                }
            },
            "last_commit": None,
        }
        path.write_text(json.dumps(payload))
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None
