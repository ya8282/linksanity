"""Smoke tests for scripts/bootstrap_linkcheck.py.

Placed under tests/unit (not scripts/) to mirror the existing convention
for scripts/case_study.py's test file (tests/unit/test_case_study.py).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap_linkcheck.py"

_spec = importlib.util.spec_from_file_location("bootstrap_linkcheck", SCRIPT)
assert _spec is not None and _spec.loader is not None
bootstrap_linkcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap_linkcheck)


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_yes_mode_writes_expected_workflow(tmp_path: Path) -> None:
    result = _run(["--repo", str(tmp_path), "--yes", "--url", "https://example.com"])
    assert result.returncode == 0, result.stderr

    workflow_path = tmp_path / ".github" / "workflows" / "linkcheck.yml"
    assert workflow_path.exists()

    text = workflow_path.read_text(encoding="utf-8")
    assert "https://example.com" in text
    assert "--max-pages 200" in text
    assert "--check-anchors" in text
    assert "--block-analytics" in text
    assert 'cron: "0 8 * * 1"' in text


def test_rerun_without_force_fails_and_does_not_modify(tmp_path: Path) -> None:
    first = _run(["--repo", str(tmp_path), "--yes", "--url", "https://example.com"])
    assert first.returncode == 0, first.stderr

    workflow_path = tmp_path / ".github" / "workflows" / "linkcheck.yml"
    original_text = workflow_path.read_text(encoding="utf-8")

    second = _run(["--repo", str(tmp_path), "--yes", "--url", "https://other.example.com"])
    assert second.returncode != 0
    assert workflow_path.read_text(encoding="utf-8") == original_text


def test_no_check_anchors_no_block_analytics_omits_flags() -> None:
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=False,
    )
    assert "--check-anchors" not in yaml_text
    assert "--block-analytics" not in yaml_text
    assert "linksanity crawl https://example.com" in yaml_text


def test_yes_requires_url(tmp_path: Path) -> None:
    result = _run(["--repo", str(tmp_path), "--yes"])
    assert result.returncode != 0
    assert "--url" in result.stderr
