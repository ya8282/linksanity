"""Tests for baseline.py — diffing a scan against a previous JSON report."""

from __future__ import annotations

import json
from pathlib import Path

from linksanity.baseline import load_baseline, only_new
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
    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        assert load_baseline(tmp_path / "missing.json") == set()

    def test_corrupt_file_returns_empty_set(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        assert load_baseline(p) == set()

    def test_only_notable_statuses_are_kept(self, tmp_path: Path) -> None:
        p = tmp_path / "report.json"
        _write_report(p, [
            {"source_file": "a.md", "line": 1, "url": "https://ok.com", "status": "ok"},
            {"source_file": "a.md", "line": 2, "url": "https://broken.com", "status": "broken"},
            {"source_file": "a.md", "line": 3, "url": "mailto:x@y.com", "status": "skipped"},
        ])
        assert load_baseline(p) == {("a.md", "https://broken.com")}

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
            ("a.md", "https://x1.com"),
            ("a.md", "https://x2.com"),
            ("a.md", "https://x3.com"),
            ("a.md", "https://x4.com"),
        }


class TestOnlyNew:
    def test_known_broken_link_is_dropped(self) -> None:
        r = _result()
        baseline = {(r.source_file, r.url)}
        assert only_new([r], baseline) == []

    def test_new_broken_link_is_kept(self) -> None:
        r = _result(url="https://new-broken.com")
        assert only_new([r], set()) == [r]

    def test_ok_results_always_kept(self) -> None:
        r = _result(status=LinkStatus.OK, http_code=200)
        baseline = {(r.source_file, r.url)}
        assert only_new([r], baseline) == [r]

    def test_line_number_drift_does_not_matter(self) -> None:
        baseline = {("docs/index.md", "https://example.com/broken")}
        r = _result(line=99)  # same file+url, different line than baseline recorded
        assert only_new([r], baseline) == []

    def test_different_file_same_url_is_new(self) -> None:
        baseline = {("other.md", "https://example.com/broken")}
        r = _result(source_file="docs/index.md")
        assert only_new([r], baseline) == [r]
