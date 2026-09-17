"""Directory-pruning rule shared by local-scan walks.

`init.py`'s `detect_paths` and `scanner.py`'s directory expansion both walk the
local checkout and must prune the same vendored/build directories and
dot-directories -- otherwise a directory `init` proposes could still be
scanned in full by the real scan, descending into its vendored subtrees.
Defined once here and imported by both instead of duplicated, so the two
lists can't drift apart.
"""

from __future__ import annotations

from pathlib import Path

DENYLIST = {
    "node_modules",
    ".venv",
    "venv",
    "site-packages",
    "vendor",
    "target",
    "build",
    "dist",
    "_build",
    ".tox",
}


def is_pruned_dir(name: str) -> bool:
    """True if a directory should not be descended into at all.

    Applies to directories only, matched by name as encountered while
    walking -- callers must not apply this to a root/explicitly-requested
    path, only to entries found while recursing into one.
    """
    return name.startswith(".") or name.lower() in DENYLIST


def should_descend(entry: Path) -> bool:
    """True if a directory entry found while walking should be recursed into.

    False for a denylisted/dot-directory name (see `is_pruned_dir`) and for
    any directory *symlink* -- including a self-referential one. `iterdir`
    doesn't follow symlinks itself, but a walk that calls `is_dir()` and then
    recurses does, so without this a symlink loop would either be swallowed
    silently by the caller's `except OSError` (ELOOP) after inflating a
    file/dir count, or in a shallower loop just double-count real files.
    Only affects directory descent -- a symlinked *file* is still counted,
    matching how a real scan would read it.
    """
    return entry.is_dir() and not entry.is_symlink() and not is_pruned_dir(entry.name)
