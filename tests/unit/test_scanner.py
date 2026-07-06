"""Tests for scanner.py — cache integration and incremental (git diff) filtering."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from linksanity.config import Config
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.scanner import run_scan


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _ok(url: str, src: str, line: int, lt: LinkType) -> LinkResult:
    return LinkResult(
        source_file=src, line=line, url=url, link_type=lt,
        status=LinkStatus.OK, http_code=200,
    )


def _mock_dispatch() -> AsyncMock:
    mock = AsyncMock()
    mock.side_effect = lambda url, src, line, lt, *a, **kw: _ok(url, src, line, lt)
    return mock


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_cache_miss_dispatches_and_persists(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1
        data = json.loads(cache_file.read_text())
        assert "https://example.com" in data["urls"]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_dispatch(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            await run_scan([str(doc)], config)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            queue = await run_scan([str(doc)], config)

        mock_dispatch.assert_not_awaited()
        assert queue.results()[0].status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_expired_cache_entry_is_rechecked(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({
            "urls": {
                "https://example.com": {
                    "source_file": str(doc), "line": 1, "link_type": "external",
                    "status": "ok", "http_code": 200, "resolved_url": None,
                    "error": None, "redirect_chain": None,
                    "checked_at": 0,
                }
            },
            "last_commit": None,
        }))
        config = Config(cache_file=str(cache_file), cache_ttl=3600)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1

    @pytest.mark.asyncio
    async def test_local_link_types_are_not_cached(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        (tmp_path / "other.md").write_text("# Other\n")
        doc.write_text("[link](other.md)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        await run_scan([str(doc)], config)

        data = json.loads(cache_file.read_text())
        assert data["urls"] == {}


class TestIncremental:
    @pytest.mark.asyncio
    async def test_no_baseline_runs_full_scan(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        config = Config(incremental=True)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1
        assert "no previous run recorded" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_since_filters_to_changed_files_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        unchanged = tmp_path / "unchanged.md"
        unchanged.write_text("[link](https://unchanged.com)\n")
        _git(tmp_path, "add", "unchanged.md")
        _git(tmp_path, "commit", "-q", "-m", "first")
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()

        changed = tmp_path / "changed.md"
        changed.write_text("[link](https://changed.com)\n")
        _git(tmp_path, "add", "changed.md")
        _git(tmp_path, "commit", "-q", "-m", "second")

        config = Config(incremental=True, since=baseline)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(tmp_path)], config)

        urls = {r.url for r in queue.results()}
        assert urls == {"https://changed.com"}

    @pytest.mark.asyncio
    async def test_bad_since_ref_falls_back_to_full_scan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        _git(tmp_path, "add", "index.md")
        _git(tmp_path, "commit", "-q", "-m", "first")

        config = Config(incremental=True, since="not-a-real-ref")

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(tmp_path)], config)

        assert mock_dispatch.await_count == 1
        assert "could not diff" in capsys.readouterr().err
