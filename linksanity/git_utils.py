"""Git helpers for incremental (diff-aware) scanning."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path | None) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout.strip()


def repo_root(cwd: Path | None = None) -> Path | None:
    """Return the git repo's top-level directory, or None outside a repo."""
    out = _run(["rev-parse", "--show-toplevel"], cwd)
    return Path(out) if out else None


def current_head(cwd: Path | None = None) -> str | None:
    """Return the current commit SHA, or None outside a repo."""
    return _run(["rev-parse", "HEAD"], cwd)


def changed_files(since: str, cwd: Path | None = None) -> set[Path] | None:
    """Return absolute paths changed between `since` and HEAD, or None if unavailable."""
    out = _run(["diff", "--name-only", since, "HEAD"], cwd)
    if out is None:
        return None
    root = repo_root(cwd)
    if root is None:
        return None
    return {(root / line).resolve() for line in out.splitlines() if line.strip()}
