"""Tests for the public library API exported from linksanity/__init__.py."""

from __future__ import annotations

import asyncio
from pathlib import Path

from linksanity import Config, LinkResult, LinkStatus, scan_paths

FIXTURES = Path(__file__).parent.parent / "fixtures"
DOCS_DIR = FIXTURES / "docs"


class TestScanPaths:
    def test_broken_internal_link_detected(self) -> None:
        # Same fixture as tests/integration/test_scan_e2e.py's
        # test_broken_internal_link_exits_1: broken.md references a
        # nonexistent local file, which must surface as BROKEN.
        results = scan_paths([str(DOCS_DIR / "broken.md")])

        assert len(results) == 2
        broken = [r for r in results if r.status == LinkStatus.BROKEN]
        assert len(broken) == 1
        assert broken[0].url == "missing.md"

    def test_clean_docs_have_no_broken_links(self) -> None:
        # Same fixture as test_scan_e2e.py's test_clean_docs_exits_0:
        # index.md and guide.md reference each other, both exist.
        results = scan_paths([str(DOCS_DIR / "index.md")])

        assert results
        assert all(r.status != LinkStatus.BROKEN for r in results)

    def test_check_anchors_flag_is_applied(self) -> None:
        # broken.md's "#nonexistent-heading" anchor is only checked (and
        # flagged BROKEN) when check_anchors is enabled.
        results = scan_paths([str(DOCS_DIR / "broken.md")], check_anchors=True)

        broken_urls = {r.url for r in results if r.status == LinkStatus.BROKEN}
        assert "#nonexistent-heading" in broken_urls

    def test_accepts_explicit_config(self) -> None:
        config = Config(check_anchors=True)
        results = scan_paths([str(DOCS_DIR / "broken.md")], config=config)

        broken_urls = {r.url for r in results if r.status == LinkStatus.BROKEN}
        assert "#nonexistent-heading" in broken_urls

    def test_scan_paths_works_from_running_event_loop(self) -> None:
        # Regression test: scan_paths() must not raise RuntimeError when
        # called from code that is already inside a running event loop
        # (e.g. a Jupyter notebook cell or an async web handler). It should
        # fall back to running the scan in a separate thread with its own
        # event loop instead of crashing on asyncio.run().
        async def _call_from_loop() -> list[LinkResult]:
            return scan_paths([str(DOCS_DIR / "broken.md")])

        results = asyncio.run(_call_from_loop())

        assert len(results) == 2
        broken = [r for r in results if r.status == LinkStatus.BROKEN]
        assert len(broken) == 1
        assert broken[0].url == "missing.md"
