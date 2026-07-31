"""Tests for cache.py — JSON cache of URL -> check result with TTL expiry."""

from __future__ import annotations

import json
import time
from pathlib import Path

from linksanity import cache as cache_module
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


class TestRedirectCodes:
    def test_redirect_codes_round_trip_through_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.put(_result(status=LinkStatus.REDIRECT, redirect_codes=[301, 308]))
        cache.save()

        hit = Cache(path, ttl=3600).get("https://example.com/page")
        assert hit is not None
        assert hit.redirect_codes == [301, 308]


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

    def test_save_writes_version_key(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.save()
        data = json.loads(path.read_text())
        assert data["version"] == cache_module._CACHE_VERSION

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
            "version": cache_module._CACHE_VERSION,
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


class TestVersioning:
    """A cache file written under a different (or absent) version is cold:
    its entries and last_commit are ignored, and the file itself is left
    untouched until the next explicit save()."""

    def _no_version_payload(self) -> dict[str, object]:
        return {
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
                    "redirect_codes": None,
                    "checked_at": time.time(),
                }
            },
            "last_commit": "stale-commit-sha",
        }

    def test_missing_version_key_is_cold(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(json.dumps(self._no_version_payload()), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None

    def test_wrong_version_is_cold(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        payload = self._no_version_payload()
        payload["version"] = cache_module._CACHE_VERSION + 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None

    def test_current_version_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        cache = Cache(path, ttl=3600)
        cache.put(_result())
        cache.save(last_commit="abc123")

        reloaded = Cache(path, ttl=3600)
        hit = reloaded.get("https://example.com/page")
        assert hit is not None
        assert hit.status == LinkStatus.OK
        assert reloaded.last_commit == "abc123"

    def test_version_mismatch_discards_last_commit(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(json.dumps(self._no_version_payload()), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.last_commit is None

    def test_loading_mismatched_cache_does_not_modify_file(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        original_bytes = json.dumps(self._no_version_payload()).encode("utf-8")
        path.write_bytes(original_bytes)
        Cache(path, ttl=3600)
        assert path.read_bytes() == original_bytes

    def test_non_dict_payload_is_cold(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None
        assert cache.last_commit is None

    def test_pre_versioning_entry_is_cold_not_degraded(self, tmp_path: Path) -> None:
        # A pre-linksanity-u87 cache file has neither a "version" key nor a
        # redirect_codes field. Reading it must not raise, and -- since the
        # whole point of versioning is that an unversioned payload is a
        # different behaviour era -- it must not be replayed at all, rather
        # than partially degraded.
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "urls": {
                        "https://example.com/page": {
                            "source_file": "docs/index.md",
                            "line": 3,
                            "link_type": "external",
                            "status": "redirect",
                            "http_code": 301,
                            "resolved_url": "https://example.com/new",
                            "error": None,
                            "redirect_chain": ["https://example.com/page"],
                            "checked_at": time.time(),
                        }
                    },
                    "last_commit": None,
                }
            ),
            encoding="utf-8",
        )
        hit = Cache(path, ttl=3600).get("https://example.com/page")
        assert hit is None

    def test_version_as_float_is_cold(self, tmp_path: Path) -> None:
        # 1.0 == 1 in Python, but a float is not the int contract the version
        # gate promises -- it must not be treated as a match.
        path = tmp_path / "cache.json"
        payload = self._no_version_payload()
        payload["version"] = float(cache_module._CACHE_VERSION)
        path.write_text(json.dumps(payload), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None

    def test_version_as_bool_is_cold(self, tmp_path: Path) -> None:
        # True == 1 in Python, and isinstance(True, int) is True, so this
        # needs an explicit bool exclusion, not just an isinstance(int) check.
        path = tmp_path / "cache.json"
        payload = self._no_version_payload()
        payload["version"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        cache = Cache(path, ttl=3600)
        assert cache.get("https://example.com/page") is None
