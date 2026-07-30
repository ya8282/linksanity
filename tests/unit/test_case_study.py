"""Smoke tests for scripts/case_study.py, run as a subprocess against in-repo fixtures."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import case_study  # noqa: E402
from case_study import _render, _run_fix_dry_run  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "case_study.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "case_study"

_BROKEN_ROW = re.compile(r"\| Broken \| (\d+) \|")


def _run_case_study(tmp_path: Path, target_dir: Path, slug: str) -> tuple[subprocess.CompletedProcess, Path]:
    out_dir = tmp_path / "case-studies"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(target_dir), ".", slug, "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
    )
    return result, out_dir / f"{slug}.md"


def test_broken_fixture_produces_nonzero_broken_count(tmp_path: Path) -> None:
    result, md_path = _run_case_study(tmp_path, FIXTURES / "broken", "broken-fixture")

    assert result.returncode == 0, result.stderr
    assert md_path.exists()

    text = md_path.read_text(encoding="utf-8")
    match = _BROKEN_ROW.search(text)
    assert match is not None, text
    assert int(match.group(1)) > 0
    assert "missing.md" in text


def test_clean_fixture_produces_clean_site_study(tmp_path: Path) -> None:
    result, md_path = _run_case_study(tmp_path, FIXTURES / "clean", "clean-fixture")

    assert result.returncode == 0, result.stderr
    assert md_path.exists()

    text = md_path.read_text(encoding="utf-8")
    match = _BROKEN_ROW.search(text)
    assert match is not None, text
    assert int(match.group(1)) == 0
    assert "Clean site" in text


def _render_kwargs(**overrides: object) -> dict:
    base: dict = {
        "slug": "test",
        "target": "test-target",
        "commit": "abc123",
        "date": "2026-01-01",
        "stats": {
            "files_scanned": 1,
            "links_checked": 1,
            "ok": 1,
            "broken": 0,
            "redirect": 0,
            "skipped": 0,
        },
        "results": [],
        "auto_fixable": 0,
        "runtime_s": 0.1,
        "scan_cmd": "scan-cmd",
        "fix_cmd": "fix-cmd",
    }
    base.update(overrides)
    return base


def test_render_reports_unknown_when_auto_fixable_is_none() -> None:
    markdown = _render(**_render_kwargs(auto_fixable=None))

    assert "Could not determine how many links are auto-fixable" in markdown
    assert "link(s) could be auto-fixed" not in markdown


def test_render_reports_count_when_auto_fixable_is_int() -> None:
    markdown = _render(**_render_kwargs(auto_fixable=3))

    assert "3 link(s) could be auto-fixed by `linksanity fix --write`." in markdown
    assert "Could not determine" not in markdown


def _fake_run(returncode: int, stdout: str):
    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return _run


def test_run_fix_dry_run_unexpected_exit_code_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(case_study.subprocess, "run", _fake_run(2, "[]"))

    result = _run_fix_dry_run(Path("unused"))

    assert result is None


def test_run_fix_dry_run_empty_stdout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(case_study.subprocess, "run", _fake_run(0, "   "))

    result = _run_fix_dry_run(Path("unused"))

    assert result is None


def test_run_fix_dry_run_invalid_json_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(case_study.subprocess, "run", _fake_run(0, "not valid json"))

    result = _run_fix_dry_run(Path("unused"))

    assert result is None


def test_run_fix_dry_run_nothing_to_fix_is_genuine_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        case_study.subprocess, "run", _fake_run(0, "[linksanity] nothing to fix\n")
    )

    result = _run_fix_dry_run(Path("unused"))

    assert result is not None
    assert result == 0


def test_run_fix_dry_run_valid_json_returns_auto_applicable_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposals = [
        {"auto_applicable": True},
        {"auto_applicable": True},
        {"auto_applicable": False},
        {"auto_applicable": True},
    ]
    monkeypatch.setattr(case_study.subprocess, "run", _fake_run(0, json.dumps(proposals)))

    result = _run_fix_dry_run(Path("unused"))

    assert result is not None
    assert result == 3
