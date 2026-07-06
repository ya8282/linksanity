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
            "checked_at": time.time(),
        }

    def save(self, *, last_commit: str | None = None) -> None:
        payload = {
            "urls": self._entries,
            "last_commit": last_commit if last_commit is not None else self.last_commit,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
