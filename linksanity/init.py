"""Detection of documentation directories to propose to `linksanity init`.

Pure, filesystem-read-only functions: no network, no prompts, no printing.
The `init` CLI command (a later bead) presents `DetectionResult` to the user
and turns the accepted selection into a `paths:` value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Same ten suffixes as scanner.py's _expand_paths (scanner.py:155-167).
# Keep this list in sync with that one.
_SUFFIXES = (
    ".md",
    ".rst",
    ".html",
    ".htm",
    ".adoc",
    ".asciidoc",
    ".mdx",
    ".ipynb",
    ".xml",
    ".dbk",
)

# ".xml" is deliberately excluded here: it is in _SUFFIXES so the scanner can
# check pom.xml/web.config, but treating it as "prose" would make an ordinary
# Java or .NET repo look documentation-heavy.
_PROSE_SUFFIXES = {".md", ".rst", ".adoc", ".mdx"}
_HTML_SUFFIXES = {".html", ".htm"}

_DENYLIST = {
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

# action.yml leaves $PATHS unquoted so it word-splits into argv entries; a
# component must contain no whitespace, "#", "*", or quotes, and must not
# start with "-" (which would word-split into a flag).
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class Proposal:
    """A directory or root-level file worth passing to `paths:`, and its file count."""

    path: str
    file_count: int


@dataclass(frozen=True)
class RefusedPath:
    """A candidate excluded because it cannot be represented as a `paths:` entry."""

    path: str
    reason: str


@dataclass(frozen=True)
class DetectionResult:
    """Everything `detect_paths` found, ranked and ready for the caller to present."""

    proposals: list[Proposal] = field(default_factory=list)
    refused: list[RefusedPath] = field(default_factory=list)
    used_html_fallback: bool = False


def _is_pruned_dir(name: str) -> bool:
    """True if a directory should not be descended into at all."""
    return name.startswith(".") or name.lower() in _DENYLIST


def _is_safe_name(name: str) -> bool:
    """True if `name` survives action.yml's unquoted `$PATHS` word-splitting."""
    return bool(_SAFE_COMPONENT.match(name)) and not name.startswith("-")


def _walk(root: Path) -> list[Path]:
    """Return every supported-suffix file under root, pruning denylisted dirs.

    Pruning means never descending into a matched directory, so nothing nested
    under it (however deep) can surface.
    """
    found: list[Path] = []

    def _recurse(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if _is_pruned_dir(entry.name):
                    continue
                _recurse(entry)
            elif entry.is_file() and entry.suffix.lower() in _SUFFIXES:
                found.append(entry)

    _recurse(root)
    return found


def _top_component(rel: Path) -> str | None:
    """First path component under root, or None if `rel` is a root-level file."""
    parts = rel.parts
    if len(parts) <= 1:
        return None
    return parts[0]


def _refusal_reason(name: str) -> str:
    if name.startswith("-"):
        return "starts with '-', which would word-split into a flag in the unquoted paths: value"
    return "contains a character unsafe for the unquoted paths: word-split (whitespace, #, *, or a quote)"


def _classify(name: str, file_count: int) -> Proposal | RefusedPath:
    bare = name.rstrip("/")
    if _is_safe_name(bare):
        return Proposal(path=name, file_count=file_count)
    return RefusedPath(path=name, reason=_refusal_reason(bare))


def detect_paths(root: Path) -> DetectionResult:
    """Walk `root` and propose documentation directories/files for `paths:`.

    Pure and filesystem-read-only: no network, no prompts, no printing.
    """
    files = _walk(root)

    root_files: list[Path] = []
    buckets: dict[str, list[Path]] = {}
    for f in files:
        rel = f.relative_to(root)
        top = _top_component(rel)
        if top is None:
            root_files.append(f)
        else:
            buckets.setdefault(top, []).append(f)

    has_prose = any(f.suffix.lower() in _PROSE_SUFFIXES for f in files)
    has_html = any(f.suffix.lower() in _HTML_SUFFIXES for f in files)
    used_html_fallback = not has_prose and has_html
    gate: set[str] = _PROSE_SUFFIXES if has_prose else (_HTML_SUFFIXES if used_html_fallback else set())

    classified: list[Proposal | RefusedPath] = []

    if gate:
        for f in sorted(root_files, key=lambda p: p.name):
            if f.suffix.lower() in gate:
                classified.append(_classify(f.name, 1))

        # Rollup stops at first-level directories: every file nested under a
        # top-level directory rolls up into a single proposal for it, never
        # split further and never emitted as the repo root itself (that
        # cannot happen here since `buckets` only ever holds non-root files,
        # so its keys are always a real first path component, never "." ).
        for name in sorted(buckets):
            bucket_files = buckets[name]
            if any(f.suffix.lower() in gate for f in bucket_files):
                classified.append(_classify(f"{name}/", len(bucket_files)))

    # Always include a root README.md, even if some future change to the gate
    # logic above would otherwise have excluded it.
    readme = root / "README.md"
    if readme.is_file() and not any(
        isinstance(c, Proposal) and c.path == "README.md" for c in classified
    ):
        classified.append(_classify("README.md", 1))

    proposals = [c for c in classified if isinstance(c, Proposal)]
    refused = [c for c in classified if isinstance(c, RefusedPath)]

    # Hard invariant: never propose the repo root. Guarded explicitly here
    # rather than relying on the rollup logic above never producing it.
    for p in proposals:
        if p.path in (".", "./", ""):
            raise AssertionError("detect_paths must never propose the repo root")

    proposals.sort(key=lambda p: p.file_count, reverse=True)

    return DetectionResult(
        proposals=proposals,
        refused=refused,
        used_html_fallback=used_html_fallback,
    )
