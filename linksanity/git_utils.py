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


def is_dirty(paths: list[Path], cwd: Path | None = None) -> bool | None:
    """True if any of `paths` has uncommitted changes; None when not in a repo.

    Used as the --write safety rail: rewriting a file with unstaged edits could
    clobber them and makes the resulting diff unreviewable.
    """
    if repo_root(cwd) is None:
        return None
    out = _run(["status", "--porcelain", "--", *(str(p) for p in paths)], cwd)
    if out is None:
        return None
    return bool(out)


def changed_files(since: str, cwd: Path | None = None) -> set[Path] | None:
    """Return absolute paths changed between `since` and HEAD, or None if unavailable."""
    out = _run(["diff", "--name-only", since, "HEAD"], cwd)
    if out is None:
        return None
    root = repo_root(cwd)
    if root is None:
        return None
    return {(root / line).resolve() for line in out.splitlines() if line.strip()}
