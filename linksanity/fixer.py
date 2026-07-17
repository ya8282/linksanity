"""Fix proposals: compute repairs from scan results and apply them to source files."""

from __future__ import annotations

import asyncio
import difflib
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import quote

import httpx

from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType

# Suffixes whose recorded line numbers are file-level, and so safe to rewrite.
# .ipynb is deliberately absent: notebook results carry within-cell line
# numbers, so a file-level rewrite would corrupt an unrelated line.
REWRITABLE_SUFFIXES = frozenset({".md", ".rst", ".html", ".htm"})

# old_url must not be a prefix of a longer URL on the same line:
# http://old.example.com/x must not match inside http://old.example.com/x/deeper
_URL_BOUNDARY = r"(?![\w\-./%&=?#~])"


class FixKind(Enum):
    REDIRECT = "redirect"        # permanent redirect → rewrite to final URL
    MOVED_FILE = "moved_file"    # broken internal link → unique basename match
    WAYBACK = "wayback"          # dead external link → archive.org snapshot


@dataclass
class FixProposal:
    source_file: str
    line: int
    old_url: str
    new_url: str
    kind: FixKind
    auto_applicable: bool        # False = suggestion only, --write never touches it
    detail: str                  # human-readable rationale


def is_permanent_redirect(result: LinkResult) -> bool:
    """True iff every hop in the redirect chain was 301 or 308."""
    codes = result.redirect_codes
    if not codes:
        return False
    return all(c in (301, 308) for c in codes)


def _is_rewritable(source_file: str) -> bool:
    return Path(source_file).suffix.lower() in REWRITABLE_SUFFIXES


def build_redirect_proposals(
    results: list[LinkResult],
    queue: LinkQueue,
    *,
    all_redirects: bool = False,
) -> list[FixProposal]:
    """Propose rewrites for redirected URLs, one proposal per source occurrence."""
    proposals: list[FixProposal] = []
    for r in results:
        if r.status is not LinkStatus.REDIRECT or not r.resolved_url:
            continue
        codes = ",".join(str(c) for c in r.redirect_codes) if r.redirect_codes else "?"
        permanent = is_permanent_redirect(r)
        base = f"{codes} → {r.resolved_url}"

        for source_file, line in queue.sources(r.url):
            if not _is_rewritable(source_file):
                suffix = Path(source_file).suffix or "no suffix"
                auto, detail = False, f"{base} ({suffix} is not rewritable, suggestion only)"
            elif permanent:
                auto, detail = True, base
            elif all_redirects:
                auto, detail = True, f"{base} (temporary redirect, forced by --redirects all)"
            else:
                auto, detail = False, f"{base} (temporary redirect, use --redirects all to apply)"
            proposals.append(
                FixProposal(
                    source_file=source_file,
                    line=line,
                    old_url=r.url,
                    new_url=r.resolved_url,
                    kind=FixKind.REDIRECT,
                    auto_applicable=auto,
                    detail=detail,
                )
            )
    return proposals


# ── Moved-file resolver ───────────────────────────────────────────────────────


def _relative_url(target: Path, source_dir: Path) -> str:
    """Path from source_dir to target, as a forward-slash relative URL."""
    return Path(os.path.relpath(target, start=source_dir)).as_posix()


def build_moved_file_proposals(
    results: list[LinkResult],
    queue: LinkQueue,
    corpus_files: list[Path],
) -> list[FixProposal]:
    """Propose re-pointing broken internal links at corpus files matching by basename.

    Deliberately simple: exact basename, exactly one candidate → auto-fix.
    Anything ambiguous is suggested, never guessed. No git-rename archaeology.
    """
    index: dict[str, list[Path]] = {}
    for path in corpus_files:
        index.setdefault(path.name, []).append(path)

    proposals: list[FixProposal] = []
    for r in results:
        if r.status is not LinkStatus.BROKEN or r.link_type is not LinkType.INTERNAL:
            continue
        # DocBook xrefs are id lookups against the corpus, not file paths.
        if r.url.startswith("docbook-xref:"):
            continue
        path_part, _, fragment = r.url.partition("#")
        basename = Path(path_part).name
        suffix = f"#{fragment}" if fragment else ""

        for source_file, line in queue.sources(r.url):
            source_dir = Path(source_file).parent
            # If the target resolves from this source, the link broke for some
            # other reason (a missing anchor) — the file has not moved.
            if (source_dir / path_part).exists():
                continue

            # (target, auto_applicable, detail)
            candidates = index.get(basename, [])
            matches: list[tuple[Path, bool, str]]
            if len(candidates) == 1 and _is_rewritable(source_file):
                matches = [
                    (candidates[0], True, f"unique file named {basename!r} in the scanned corpus")
                ]
            elif len(candidates) == 1:
                fmt = Path(source_file).suffix or "no suffix"
                matches = [
                    (
                        candidates[0],
                        False,
                        f"unique file named {basename!r}, but {fmt} is not rewritable",
                    )
                ]
            elif candidates:
                matches = [
                    (c, False, f"{len(candidates)} files named {basename!r} — ambiguous, pick one")
                    for c in candidates
                ]
            else:
                matches = [
                    (c, False, f"no file named {basename!r}; closest match is {name!r}")
                    for name in difflib.get_close_matches(basename, list(index), n=3, cutoff=0.8)
                    for c in index[name]
                ]

            proposals.extend(
                FixProposal(
                    source_file=source_file,
                    line=line,
                    old_url=r.url,
                    new_url=_relative_url(target, source_dir) + suffix,
                    kind=FixKind.MOVED_FILE,
                    auto_applicable=auto,
                    detail=detail,
                )
                for target, auto, detail in matches
            )
    return proposals


# ── Wayback suggester ─────────────────────────────────────────────────────────

_WAYBACK_API = "https://archive.org/wayback/available"


def _wayback_eligible(result: LinkResult) -> bool:
    """True for external links dead enough to be worth an archive lookup."""
    if result.link_type is not LinkType.EXTERNAL:
        return False
    if result.status is LinkStatus.BROKEN:
        return result.http_code in (404, 410)
    # ponytail: any transport error counts, rather than sniffing error strings
    # for DNS specifically — the platform wording varies and the cost of a
    # false positive is one extra suggestion the human ignores.
    return result.status is LinkStatus.ERROR


async def _wayback_lookup(
    client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore
) -> str | None:
    """Return an archive.org snapshot URL, or None. Never raises."""
    async with sem:
        try:
            resp = await client.get(f"{_WAYBACK_API}?url={quote(url, safe='')}")
            closest = resp.json().get("archived_snapshots", {}).get("closest")
        except Exception as exc:  # noqa: BLE001 — an archive.org outage must never fail the run
            print(f"[linksanity] wayback lookup failed for {url}: {exc}", file=sys.stderr)
            return None
    if closest and closest.get("available") is True and closest.get("url"):
        return str(closest["url"])
    return None


async def build_wayback_proposals(
    results: list[LinkResult],
    queue: LinkQueue,
    *,
    timeout: int,
    workers: int = 8,
) -> list[FixProposal]:
    """Suggest archive.org snapshots for dead external links. Never auto-applied."""
    targets = [r for r in results if _wayback_eligible(r)]
    if not targets:
        return []

    sem = asyncio.Semaphore(workers)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(float(timeout)), follow_redirects=True
    ) as client:
        snapshots = await asyncio.gather(
            *[_wayback_lookup(client, r.url, sem) for r in targets]
        )

    proposals: list[FixProposal] = []
    for result, snapshot in zip(targets, snapshots, strict=True):
        if snapshot is None:
            continue
        reason = f"HTTP {result.http_code}" if result.http_code else (result.error or "unreachable")
        for source_file, line in queue.sources(result.url):
            proposals.append(
                FixProposal(
                    source_file=source_file,
                    line=line,
                    old_url=result.url,
                    new_url=snapshot,
                    kind=FixKind.WAYBACK,
                    auto_applicable=False,
                    detail=f"dead ({reason}); archive.org snapshot available — review before using",
                )
            )
    return proposals


# ── Rewrite engine ────────────────────────────────────────────────────────────


def _substitute(line: str, old: str, new: str) -> str | None:
    """Replace every occurrence of `old` on `line`; None if `old` is not present."""
    pattern = re.escape(old) + _URL_BOUNDARY
    if not re.search(pattern, line):
        return None
    # Lambda replacement: a plain string would have \g, \1 etc. interpreted.
    return re.sub(pattern, lambda _: new, line)


def _read_lines(path: Path) -> list[str] | None:
    """Read a file split on newlines, or None if unreadable.

    Reads with newline="" so line endings are never translated, and splits on
    "\\n" only, so "\\n".join(lines) round-trips the original bytes exactly and
    line N is the same line the parsers numbered.
    """
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read().split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"[linksanity] skipped {path}: cannot read ({exc})", file=sys.stderr)
        return None


def _atomic_write(path: Path, content: str) -> None:
    """Write via a temp file in the same directory + os.replace, so a crash
    mid-fix can never leave a truncated source file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rewrite(lines: list[str], proposals: list[FixProposal], *, warn: bool) -> int:
    """Apply proposals to `lines` in place; returns the number applied."""
    applied = 0
    for p in proposals:
        idx = p.line - 1
        if idx < 0 or idx >= len(lines):
            if warn:
                print(
                    f"[linksanity] skipped {p.source_file}:{p.line} — line no longer "
                    f"exists (file changed since scan)",
                    file=sys.stderr,
                )
            continue
        replaced = _substitute(lines[idx], p.old_url, p.new_url)
        if replaced is None:
            if warn:
                print(
                    f"[linksanity] skipped {p.source_file}:{p.line} — {p.old_url} not "
                    f"found on that line (file changed since scan)",
                    file=sys.stderr,
                )
            continue
        lines[idx] = replaced
        applied += 1
    return applied


def _by_file(proposals: list[FixProposal]) -> dict[str, list[FixProposal]]:
    """Group auto-applicable proposals by source file, preserving order."""
    grouped: dict[str, list[FixProposal]] = {}
    for p in proposals:
        if p.auto_applicable:
            grouped.setdefault(p.source_file, []).append(p)
    return grouped


def apply_proposals(proposals: list[FixProposal]) -> tuple[int, list[str]]:
    """Apply auto-applicable proposals grouped by file.

    Returns (fixes written, modified paths). The count comes from the rewrite
    itself, never from the proposal list: a proposal whose line no longer holds
    its URL is skipped, and callers report this number to the user.
    """
    applied = 0
    modified: list[str] = []
    for source_file, file_proposals in _by_file(proposals).items():
        path = Path(source_file)
        lines = _read_lines(path)
        if lines is None:
            continue
        written = _rewrite(lines, file_proposals, warn=True)
        if written:
            _atomic_write(path, "\n".join(lines))
            applied += written
            modified.append(source_file)
    return applied, modified


def render_diff(proposals: list[FixProposal]) -> str:
    """Unified diff of what --write would change. Reads files, never writes."""
    chunks: list[str] = []
    for source_file, file_proposals in _by_file(proposals).items():
        path = Path(source_file)
        original = _read_lines(path)
        if original is None:
            continue
        updated = list(original)
        if not _rewrite(updated, file_proposals, warn=False):
            continue
        diff = difflib.unified_diff(
            original, updated, fromfile=source_file, tofile=source_file, lineterm=""
        )
        chunks.append("\n".join(diff))
    return "\n".join(chunks)
