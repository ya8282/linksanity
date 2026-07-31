"""Local JSON cache of URL -> check result, so re-runs skip unchanged links.

ponytail: JSON file, not SQLite — a dict of URLs is small enough that a flat
file is simplest. Upgrade to SQLite if the cache grows large enough that a
full read/write per run becomes measurably slow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from linksanity.queue import LinkResult, LinkStatus, LinkType

# Bump this whenever a change alters how a LinkResult is *classified*
# (status, redirect_codes, http_code interpretation, etc — see linksanity-vid,
# linksanity-f8t, linksanity-9vj for examples). A payload written under an
# older version is treated as cold on load, so bumping this is what forces a
# warm cache to stop replaying pre-fix classifications instead of serving
# them for up to `cache_ttl` seconds.
_CACHE_VERSION = 1


class Cache:
    """Reads/writes a JSON file mapping URL -> last check result + timestamp."""

    def __init__(self, path: Path, ttl: int) -> None:
        self.path = path
        self.ttl = ttl
        self.last_commit: str | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        version = raw.get("version") if isinstance(raw, dict) else None
        version_matches = (
            isinstance(version, int)
            and not isinstance(version, bool)
            and version == _CACHE_VERSION
        )
        if not isinstance(raw, dict) or not version_matches:
            # Cold cache: missing/foreign/mismatched version. This also covers
            # every pre-versioning cache file, which has no "version" key at
            # all. Discard last_commit too, not just the entries -- otherwise
            # an --incremental run would trust a stale commit ref and skip
            # files whose links need re-checking under the new classification
            # rules. Leave the on-disk file untouched; the next save()
            # overwrites it naturally.
            return
        self._entries = raw.get("urls", {})
        self.last_commit = raw.get("last_commit")

    def get(self, url: str) -> LinkResult | None:
        """Return a cached LinkResult for `url` if present and not expired."""
        entry = self._entries.get(url)
        if entry is None:
            return None
        if time.time() - float(entry["checked_at"]) > self.ttl:
            return None
        return LinkResult(
            source_file=str(entry["source_file"]),
            line=int(entry["line"]),
            url=url,
            link_type=LinkType(entry["link_type"]),
            status=LinkStatus(entry["status"]),
            http_code=entry.get("http_code"),
            resolved_url=entry.get("resolved_url"),
            error=entry.get("error"),
            redirect_chain=entry.get("redirect_chain"),
            # .get() is defensive, not a compatibility shim: every version-1
            # entry is written by save(), which always emits this field, so
            # the fallback to None should be unreachable in practice. It reads
            # as "not known permanent" -- suggestion-only, never auto-applied.
            redirect_codes=entry.get("redirect_codes"),
        )

    def put(self, result: LinkResult) -> None:
        self._entries[result.url] = {
            "source_file": result.source_file,
            "line": result.line,
            "link_type": result.link_type.value,
            "status": result.status.value,
            "http_code": result.http_code,
            "resolved_url": result.resolved_url,
            "error": result.error,
            "redirect_chain": result.redirect_chain,
            "redirect_codes": result.redirect_codes,
            "checked_at": time.time(),
        }

    def save(self, *, last_commit: str | None = None) -> None:
        payload = {
            "version": _CACHE_VERSION,
            "urls": self._entries,
            "last_commit": last_commit if last_commit is not None else self.last_commit,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
