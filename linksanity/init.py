"""Detection, estimate, and render helpers for `linksanity init`.

Pure functions only: no network, no prompts, no printing, no subprocess. The
`init` CLI command (a later bead) drives the actual scan, presents this
module's return values to the user, and writes files.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from linksanity._meta import VERSION
from linksanity.config import Config, load_config

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


def measuring_config(toml_path: Path | None = None) -> Config:
    """Build the `Config` used for `init`'s timed measuring scan.

    Starts from the project's own `load_config()` -- not a from-scratch
    `Config` -- so skip lists, timeouts, `js_domains`, and everything else in
    `linksanity.toml` match what the CI scan will actually use: CI runs
    `load_config()` in the checked-out repo and picks up the same file. A
    from-scratch `Config` would silently diverge the measured scan from the
    CI scan, corrupting both the estimate and the baseline's completeness.

    `cache_file` is then forced to `None`: a repo-local `linksanity.toml`
    setting `cache_file` would otherwise make the measured wall time
    meaningless (a warm cache finishes almost instantly). `output` and
    `report` are neutralized to `None` because `init` reads the scan's
    results from the returned queue, not from a file the scan writes.
    `baseline`, `incremental`, and `since` are neutralized to their
    no-filtering defaults (`None`, `False`, `None`) for the same reason as
    `cache_file`: any of the three would filter which URLs the measuring
    scan actually visits, shrinking both the measured wall time and the
    file/URL counts the baseline records -- corrupting both the estimate
    and the baseline's completeness (spec section 5).
    """
    cfg = load_config(toml_path)
    return replace(
        cfg,
        cache_file=None,
        output=None,
        report=None,
        baseline=None,
        incremental=False,
        since=None,
    )


# Fixed CI overhead added to the locally measured wall time before rounding
# up to a billed minute. Calibrated 2026-08-30 from ya8282/linksanity-action
# run 33317218474 ("Self-test", v1 == 1f1a4d3), averaging the full non-scan
# overhead across three representative jobs (99272756783, 99272756664,
# 99272756800): runner provisioning (~0.6-2.2s) + actions/checkout
# (~0.9-1.2s) + actions/setup-python (~0.16-0.19s) + pip install
# (~5.4-6.5s, the dominant and most variable term) + actions/upload-artifact
# (~0.7-1.3s). Per-job totals were 11.4s, 7.8s, and 8.9s; mean 9.36s,
# rounded to 9. All five billed components are included, not just the three
# named in the estimate's parenthetical, because provisioning and artifact
# upload are billed minutes too and excluding them would understate cost.
_CI_OVERHEAD_SECONDS = 9.0  # seconds

# Illustrative-only constants for the private-repo cost line. `init` never
# queries the GitHub API for a repo's actual PR volume.
_ILLUSTRATIVE_RUNS_PER_MONTH = 30
_FREE_MINUTES_PER_MONTH = 2000


def estimate_billed_minutes(
    measured_seconds: float, overhead_seconds: float = _CI_OVERHEAD_SECONDS
) -> int:
    """Billed minutes for one CI job: GitHub Actions rounds each job up to
    the next whole minute; `ubuntu-latest` carries a 1x multiplier.

    `overhead_seconds` is a parameter, not read from the module constant
    internally, so a test pinning its value keeps passing unchanged
    regardless of how `_CI_OVERHEAD_SECONDS` is calibrated.
    """
    return math.ceil((measured_seconds + overhead_seconds) / 60)


def _format_duration(seconds: float) -> str:
    """Render seconds as e.g. `"40s"` or `"1m 52s"`."""
    total = round(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def render_estimate(
    measured_seconds: float,
    unique_urls: int,
    unique_domains: int,
    overhead_seconds: float = _CI_OVERHEAD_SECONDS,
) -> list[str]:
    """Build the estimate output lines described in spec section 5.

    Returns the text as data (a list of lines): this module stays pure, it
    never prints. The measured wall time and the modelled CI overhead are
    reported as separate lines, never collapsed into one confident figure --
    local wall time is a biased proxy for runner wall time (different egress
    IP, cold DNS, different CPU; Assumption 11).
    """
    billed = estimate_billed_minutes(measured_seconds, overhead_seconds)
    monthly = billed * _ILLUSTRATIVE_RUNS_PER_MONTH
    return [
        f"Measured with linksanity {VERSION} locally; CI installs the latest release.",
        "",
        f"Measured locally:  {_format_duration(measured_seconds)}   "
        f"({unique_urls} unique URLs, {unique_domains} domains)",
        f"CI overhead:      ~{_format_duration(overhead_seconds)}      "
        "(runner setup, checkout, python, pip install, artifact upload)",
        f"Estimated billed: ~{billed} min/run   "
        "GitHub rounds each job up to a whole minute",
        "",
        "Public repo:  free",
        f"Private repo: ~{billed} min/run, so ~{monthly:,} min/mo at "
        f"{_ILLUSTRATIVE_RUNS_PER_MONTH} runs/mo (illustrative)",
        f"              against the {_FREE_MINUTES_PER_MONTH:,} min/mo free allowance",
    ]


def count_divergence_warning(detected_file_count: int, measured_file_count: int) -> str | None:
    """Warn when the measuring scan touched far more files than detection proposed.

    Detection prunes the denylist (`node_modules`, `vendor`, ...) but the
    real scan uses a bare `rglob` and does not (`scanner.py`). When the
    measured file count exceeds the detected count by more than 2x, the
    selected directories likely contain an undetected tree (often vendored)
    the scan will descend into, so the user can deselect before committing.

    Boundary: exactly 2x does **not** warn; only strictly greater than 2x
    does. A modest, plausible discrepancy should not nag on every run.

    Returns `None` (this module never prints) when there is nothing to say,
    including when `detected_file_count` is not positive -- the ratio is
    undefined there, and diagnosing "detection found nothing" is not this
    function's job.
    """
    if detected_file_count <= 0:
        return None
    if measured_file_count <= detected_file_count * 2:
        return None
    return (
        f"Measured scan touched {measured_file_count} files, more than 2x the "
        f"{detected_file_count} files detection proposed. The selected "
        "directories likely contain a tree the scan will descend into that "
        "detection did not (often vendored code) -- consider deselecting it "
        "before committing."
    )


def render_workflow(paths: list[str], baseline_path: str | None = None) -> str:
    """Render `.github/workflows/linkcheck.yml` per spec section 6.

    `baseline_path` is the value for the `baseline:` input; that line is
    emitted only when a baseline was written (pass `None` to omit it, e.g.
    no breakage was found or the user declined). Multiple paths render
    space-separated on a single `paths:` line -- the same word-split format
    `action.yml` expects.
    """
    if not paths:
        raise ValueError("render_workflow requires at least one path")
    lines = [
        "name: Link check",
        "on: [pull_request]",
        "permissions:",
        "  contents: read",
        "jobs:",
        "  linkcheck:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - uses: ya8282/linksanity-action@v1",
        "        with:",
        f"          paths: {' '.join(paths)}",
    ]
    if baseline_path is not None:
        lines.append(f"          baseline: {baseline_path}")
    return "\n".join(lines) + "\n"
