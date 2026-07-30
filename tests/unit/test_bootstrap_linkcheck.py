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
    assert "--block-analytics" in text
    assert 'cron: "0 8 * * 1"' in text

    # crawl --check-anchors only exists from 0.2.0; the default pin is older,
    # so the default workflow must not emit it.
    assert "--check-anchors" not in text

    # The install must be pinned, not floating on latest.
    assert (
        f'pip install "linksanity[browser]=={bootstrap_linkcheck.DEFAULT_LINKSANITY_VERSION}"'
        in text
    )

    # `cache: pip` makes setup-python fail in repos with no Python manifest,
    # which is most sites this workflow gets bootstrapped into.
    assert "cache: pip" not in text


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


def test_check_anchors_rejected_against_old_pin(tmp_path: Path) -> None:
    """The exact failure that broke the chrischo.org run: crawl --check-anchors
    emitted against a linksanity that has it on `scan` only."""
    result = _run(
        [
            "--repo",
            str(tmp_path),
            "--yes",
            "--url",
            "https://example.com",
            "--check-anchors",
            "--linksanity-version",
            "0.1.1",
        ]
    )
    assert result.returncode == 2
    assert "0.2.0" in result.stderr
    assert not (tmp_path / ".github" / "workflows" / "linkcheck.yml").exists()


def test_check_anchors_allowed_against_new_enough_pin(tmp_path: Path) -> None:
    result = _run(
        [
            "--repo",
            str(tmp_path),
            "--yes",
            "--url",
            "https://example.com",
            "--check-anchors",
            "--linksanity-version",
            "0.2.0",
        ]
    )
    assert result.returncode == 0, result.stderr
    text = (tmp_path / ".github" / "workflows" / "linkcheck.yml").read_text(encoding="utf-8")
    assert "--check-anchors" in text
    assert 'pip install "linksanity[browser]==0.2.0"' in text


def test_version_tuple_orders_releases() -> None:
    vt = bootstrap_linkcheck._version_tuple
    assert vt("0.1.1") < vt("0.2.0")
    assert vt("0.2.0") < vt("0.10.0")
    assert vt("0.2.0rc1") == vt("0.2.0")


def test_yes_requires_url(tmp_path: Path) -> None:
    result = _run(["--repo", str(tmp_path), "--yes"])
    assert result.returncode != 0
    assert "--url" in result.stderr
