"""Tests for baseline.py — diffing a scan against a previous JSON report."""

from __future__ import annotations

import json
from pathlib import Path

from linksanity.baseline import _NOTABLE, _SEVERITY, load_baseline, only_new
from linksanity.queue import LinkResult, LinkStatus, LinkType


def _result(**overrides: object) -> LinkResult:
    defaults: dict[str, object] = {
        "source_file": "docs/index.md",
        "line": 5,
        "url": "https://example.com/broken",
        "link_type": LinkType.EXTERNAL,
        "status": LinkStatus.BROKEN,
        "http_code": 404,
    }
    defaults.update(overrides)
    return LinkResult(**defaults)  # type: ignore[arg-type]


def _write_report(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(entries))


class TestLoadBaseline:
    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert load_baseline(tmp_path / "missing.json") == {}

    def test_corrupt_file_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        assert load_baseline(p) == {}

    def test_only_notable_statuses_are_kept(self, tmp_path: Path) -> None:
        p = tmp_path / "report.json"
        _write_report(p, [
            {"source_file": "a.md", "line": 1, "url": "https://ok.com", "status": "ok"},
            {"source_file": "a.md", "line": 2, "url": "https://broken.com", "status": "broken"},
            {"source_file": "a.md", "line": 3, "url": "mailto:x@y.com", "status": "skipped"},
        ])
        assert load_baseline(p) == {("a.md", "https://broken.com"): LinkStatus.BROKEN}

    def test_all_notable_statuses_recognized(self, tmp_path: Path) -> None:
        p = tmp_path / "report.json"
        _write_report(p, [
            {"source_file": "a.md", "line": 1, "url": "https://x1.com", "status": "broken"},
            {"source_file": "a.md", "line": 2, "url": "https://x2.com", "status": "error"},
            {"source_file": "a.md", "line": 3, "url": "https://x3.com", "status": "redirect"},
            {"source_file": "a.md", "line": 4, "url": "https://x4.com", "status": "too_many_redirects"},
        ])
        keys = load_baseline(p)
        assert keys == {
            ("a.md", "https://x1.com"): LinkStatus.BROKEN,
            ("a.md", "https://x2.com"): LinkStatus.ERROR,
            ("a.md", "https://x3.com"): LinkStatus.REDIRECT,
            ("a.md", "https://x4.com"): LinkStatus.TOO_MANY_REDIRECTS,
        }

    def test_status_less_entry_maps_to_none(self, tmp_path: Path) -> None:
        # A baseline file written before status-aware comparison existed has
        # no "status" field at all. It must load, not crash.
        p = tmp_path / "legacy.json"
        _write_report(p, [
            {"source_file": "a.md", "line": 1, "url": "https://x1.com"},
        ])
        assert load_baseline(p) == {("a.md", "https://x1.com"): None}


class TestOnlyNew:
    def test_known_broken_link_is_dropped(self) -> None:
        r = _result()
        baseline = {(r.source_file, r.url): LinkStatus.BROKEN}
        assert only_new([r], baseline) == []

    def test_new_broken_link_is_kept(self) -> None:
        r = _result(url="https://new-broken.com")
        assert only_new([r], {}) == [r]

    def test_ok_results_always_kept(self) -> None:
        r = _result(status=LinkStatus.OK, http_code=200)
        baseline = {(r.source_file, r.url): LinkStatus.BROKEN}
        assert only_new([r], baseline) == [r]

    def test_line_number_drift_does_not_matter(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.BROKEN}
        r = _result(line=99)  # same file+url, different line than baseline recorded
        assert only_new([r], baseline) == []

    def test_different_file_same_url_is_new(self) -> None:
        baseline = {("other.md", "https://example.com/broken"): LinkStatus.BROKEN}
        r = _result(source_file="docs/index.md")
        assert only_new([r], baseline) == [r]

    def test_redirect_degrading_to_broken_refails(self) -> None:
        # This is the bug: a link baselined while merely a redirect must not
        # stay green once it degrades to broken at the same (file, url).
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.REDIRECT}
        r = _result(status=LinkStatus.BROKEN, http_code=404)
        assert only_new([r], baseline) == [r]

    def test_redirect_staying_redirect_is_suppressed(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.REDIRECT}
        r = _result(status=LinkStatus.REDIRECT, http_code=301)
        assert only_new([r], baseline) == []

    def test_broken_staying_broken_is_suppressed(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.BROKEN}
        r = _result(status=LinkStatus.BROKEN, http_code=500)
        assert only_new([r], baseline) == []

    def test_broken_improving_to_redirect_stays_suppressed(self) -> None:
        # Strictly-better transition: not the failure this feature guards
        # against, so it must not be forced back to red.
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.BROKEN}
        r = _result(status=LinkStatus.REDIRECT, http_code=301)
        assert only_new([r], baseline) == []

    def test_too_many_redirects_is_equal_tier_to_broken(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.BROKEN}
        r = _result(status=LinkStatus.TOO_MANY_REDIRECTS, http_code=None)
        assert only_new([r], baseline) == []

    def test_redirect_degrading_to_too_many_redirects_refails(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken"): LinkStatus.REDIRECT}
        r = _result(status=LinkStatus.TOO_MANY_REDIRECTS, http_code=None)
        assert only_new([r], baseline) == [r]

    def test_legacy_status_less_baseline_entry_suppresses_unconditionally(self) -> None:
        # A baseline file written before this change carries no status per
        # entry. It must keep suppressing, not silently re-fail an entire
        # repo's CI just because it wasn't regenerated.
        baseline = {("docs/index.md", "https://example.com/broken"): None}
        r = _result(status=LinkStatus.BROKEN, http_code=404)
        assert only_new([r], baseline) == []


def test_every_notable_status_has_an_explicit_severity_tier() -> None:
    # _severity() defaults an unmapped status to tier 0. If a status is ever
    # dropped from _SEVERITY (e.g. removed from queue.FAILING_STATUSES) while
    # staying in _NOTABLE, that default would silently swallow it instead of
    # erroring — so pin the mapping directly rather than through _severity().
    assert _SEVERITY.keys() >= _NOTABLE
