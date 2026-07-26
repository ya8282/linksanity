"""Smoke tests for scripts/case_study.py, run as a subprocess against in-repo fixtures."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

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
