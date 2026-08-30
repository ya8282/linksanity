"""CLI entry point for linksanity."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.table import Table

from linksanity.config import Config, ConfigError, load_config
from linksanity.fixer import (
    FixProposal,
    apply_proposals,
    build_moved_file_proposals,
    build_redirect_proposals,
    build_wayback_proposals,
    render_diff,
)
from linksanity.init import (
    _DENYLIST,
    _SUFFIXES,
    DetectionResult,
    Proposal,
    _is_safe_name,
    _refusal_reason,
    count_divergence_warning,
    detect_paths,
    measuring_config,
    render_estimate,
    render_workflow,
)
from linksanity.queue import FAILING_STATUSES, LinkQueue, LinkResult
from linksanity.reporters import report
from linksanity.scanner import run_scan

app = typer.Typer(
    name="linksanity",
    help="Detect broken links in Markdown, reStructuredText, and HTML documentation.",
    no_args_is_help=True,
)


class OutputFormat(Enum):
    """The single definition of the valid --format / config.format strings.

    Config.format itself stays a plain str (linksanity.config.Config) --
    this enum only exists so the format strings aren't spelled out
    separately in each command's allow-list and error message.
    """

    CONSOLE = "console"
    JSON = "json"
    CSV = "csv"


# Per-command allow-lists, derived from OutputFormat so there is exactly one
# place that spells out the valid format strings.
_ALL_FORMATS: tuple[str, ...] = tuple(f.value for f in OutputFormat)
_CONSOLE_JSON_FORMATS: tuple[str, ...] = (OutputFormat.CONSOLE.value, OutputFormat.JSON.value)
_STRUCTURED_FORMATS: tuple[str, ...] = (OutputFormat.JSON.value, OutputFormat.CSV.value)


def _annotations_enabled(config: Config) -> bool:
    if config.annotations is not None:          # explicit --annotations/--no-annotations
        return config.annotations
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    # Assumption 6: never corrupt bare-stdout structured output
    return not (config.format in _STRUCTURED_FORMATS and not config.output)


def _run_annotations_reporter(results: list[LinkResult]) -> None:
    from linksanity.reporters.github_annotations import report as annotations_report  # noqa: I001
    annotations_report(results)


def _read_domains(path: str | None) -> set[str]:
    """Read a newline-delimited domain file; ignore blank lines and # comments."""
    if not path:
        return set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}
    except OSError as exc:
        typer.echo(f"[linksanity] cannot read domains file: {exc}", err=True)
        raise typer.Exit(2) from exc


def _discover_config() -> Path | None:
    """Walk from the cwd toward the filesystem root looking for linksanity.toml.

    Stops at (and includes) the first directory containing a `.git` entry,
    treating it as the project boundary -- a stray linksanity.toml sitting
    in an ancestor directory (e.g. a home directory) must not leak into an
    unrelated project. If no `.git` is found on the way up, the walk
    continues to the filesystem root.
    """
    directory = Path.cwd()
    while True:
        candidate = directory / "linksanity.toml"
        if candidate.exists():
            return candidate
        if (directory / ".git").exists():
            return None
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def _announce_config(path: Path | None, format: str, output: str | None) -> None:
    """Print one stderr line saying which linksanity.toml (if any) was used.

    Suppressed when the run emits bare structured output on stdout — format
    is json/csv and no --output file was given. That's the agent/script pipe
    case, where this line would be noise on every invocation.

    Note this is a noise choice, not a correctness one: the line goes to
    stderr, so it does not corrupt a `--format json | jq` pipeline either
    way. It is a weaker rule than _annotations_enabled's "Assumption 6",
    which guards genuine stdout corruption because the annotations reporter
    writes to stdout.

    Called after _load_config_or_exit with the *effective* config.format
    and config.output (linksanity-1pq) rather than the raw CLI flags, so
    the suppression decision is symmetric: `--format json` on the command
    line and `format = "json"` in linksanity.toml produce identical noise
    behaviour. Deferring this past config loading means it no longer prints
    ahead of a config-parse error, but ConfigError messages already name the
    offending path (see linksanity.config._error_suffix), so nothing is lost
    there. The "--config file not found" error is unaffected -- that still
    fires immediately from _resolve_config_path, before any config is
    loaded.
    """
    if format in _STRUCTURED_FORMATS and not output:
        return
    if path is None:
        typer.echo("[linksanity] no linksanity.toml found; using defaults", err=True)
    else:
        typer.echo(f"[linksanity] using config: {path}", err=True)


def _resolve_config_path(config_file: str | None) -> Path | None:
    """Resolve the linksanity.toml to load, without announcing anything.

    An explicit --config path wins outright; if it does not exist that is
    an error, not a silent fallback to defaults. Otherwise, search upward
    from the cwd for the nearest linksanity.toml (see _discover_config).

    The announcement itself is made by _announce_config, called separately
    once the effective config (and therefore its effective format/output)
    is known (linksanity-1pq).
    """
    if config_file:
        explicit_path = Path(config_file)
        if not explicit_path.exists():
            typer.echo(f"[linksanity] --config file not found: {explicit_path}", err=True)
            raise typer.Exit(2)
        return explicit_path

    return _discover_config()


def _load_config_or_exit(config_path: Path | None, **overrides: object) -> Config:
    """Load linksanity.toml, turning a malformed or wrongly-typed file into
    a clean invocation error (exit 2) instead of a raw traceback. Mirrors
    the "--config file not found" error already raised by
    _resolve_config_path so both bad-input paths look and feel the same.
    """
    try:
        return load_config(config_path, **overrides)
    except ConfigError as exc:
        typer.echo(f"[linksanity] {exc}", err=True)
        raise typer.Exit(2) from exc


def _measuring_config_or_exit(config_path: Path | None) -> Config:
    """Build `init`'s measuring config, turning a malformed `linksanity.toml`
    into the same clean exit-2 as every other command instead of letting
    `measuring_config`'s underlying `load_config` raise `ConfigError`
    uncaught. Mirrors `_load_config_or_exit` rather than adding a second
    error-handling convention for `init` alone.
    """
    try:
        return measuring_config(config_path)
    except ConfigError as exc:
        typer.echo(f"[linksanity] {exc}", err=True)
        raise typer.Exit(2) from exc


def _load_and_validate(
    config_file: str | None, allowed: tuple[str, ...], **overrides: object
) -> Config:
    """Resolve, load, announce, and validate --format -- in that order.

    Announce happens after loading so the suppression decision keys off the
    *effective* format/output (from --format/--output or linksanity.toml,
    whichever won), not just the raw CLI flags (linksanity-1pq).
    """
    config_path = _resolve_config_path(config_file)
    config = _load_config_or_exit(config_path, **overrides)
    _announce_config(config_path, config.format, config.output)

    if config.format not in allowed:
        joined = ", ".join(allowed)
        typer.echo(
            f"[linksanity] --format must be one of: {joined} (got {config.format!r})",
            err=True,
        )
        raise typer.Exit(2)

    return config


@app.command()
def scan(
    paths: list[str] = typer.Argument(..., help="Files, directories, or glob patterns"),  # noqa: B008
    config_file: str | None = typer.Option(
        None, "--config", "-c", help="Path to linksanity.toml config file"
    ),
    workers: int | None = typer.Option(None, help="Max concurrent HTTP checks"),
    timeout: int | None = typer.Option(None, help="Per-request timeout in seconds"),
    retry: int | None = typer.Option(None, help="Number of retries on 429/503"),
    check_anchors: bool = typer.Option(False, help="Validate anchor fragments"),
    check_images: bool = typer.Option(
        False, help="Also validate <img src> / ![]() image targets, not just links"
    ),
    myst: bool = typer.Option(
        False, help="Also extract MyST {doc}/{ref} role targets from .md files"
    ),
    link_style: str | None = typer.Option(
        None, help="Relative-link resolution preset for built docs sites: mkdocs, docusaurus, sphinx"
    ),
    ignore_domains: str | None = typer.Option(
        None, help="File listing domains to skip (one per line)"
    ),
    js_domains: str | None = typer.Option(
        None, help="File listing domains that require a browser (Playwright)"
    ),
    skip_urls: str | None = typer.Option(
        None, help="File listing URLs or patterns to skip, e.g. auth-gated pages (one per line, * wildcards ok)"
    ),
    format: str | None = typer.Option(
        None, help="Output format: console, json, csv (default: console)"
    ),
    output: str | None = typer.Option(None, help="Write results to this file"),
    report_path: str | None = typer.Option(
        None, "--report", help="Write Markdown summary report to this file"
    ),
    github_issue: bool = typer.Option(
        False, help="Open a GitHub Issue for broken links"
    ),
    repo: str | None = typer.Option(
        None, help="GitHub repo in OWNER/REPO format (required with --github-issue)"
    ),
    max_redirects: int | None = typer.Option(
        None, help="Max redirect hops before flagging as too-many-redirects"
    ),
    cache: str | None = typer.Option(
        None, help="Path to a local cache file; re-runs skip unchanged links within --cache-ttl"
    ),
    cache_ttl: int | None = typer.Option(
        None, help="Seconds a cached link result stays valid (default 86400)"
    ),
    incremental: bool = typer.Option(
        False, help="Only scan files changed since the last run (git diff-aware)"
    ),
    since: str | None = typer.Option(
        None, help="Git ref to diff against for --incremental (default: last recorded run)"
    ),
    baseline: str | None = typer.Option(
        None, help="Previous JSON report to diff against; only new breakage is reported"
    ),
    annotations: bool | None = typer.Option(
        None,
        "--annotations/--no-annotations",
        help="Emit GitHub Actions ::error/::warning annotations (default: auto-detect CI)",
    ),
    offline: bool = typer.Option(
        False,
        help="Skip external HTTP checks (reported as SKIPPED); does not read or write the cache for them",
    ),
) -> None:
    """Scan local documentation files for broken links."""
    overrides: dict[str, object] = {}
    if workers is not None:
        overrides["workers"] = workers
    if timeout is not None:
        overrides["timeout"] = timeout
    if retry is not None:
        overrides["retry"] = retry
    if check_anchors:
        overrides["check_anchors"] = True
    if check_images:
        overrides["check_images"] = True
    if myst:
        overrides["myst"] = True
    if max_redirects is not None:
        overrides["max_redirects"] = max_redirects
    if cache:
        overrides["cache_file"] = cache
    if cache_ttl is not None:
        overrides["cache_ttl"] = cache_ttl
    if incremental:
        overrides["incremental"] = True
    if since:
        overrides["since"] = since
    if baseline:
        overrides["baseline"] = baseline
    if annotations is not None:
        overrides["annotations"] = annotations
    if offline:
        overrides["offline"] = True
    if link_style:
        if link_style not in ("mkdocs", "docusaurus", "sphinx"):
            typer.echo(
                f"[linksanity] --link-style must be one of: mkdocs, docusaurus, sphinx (got {link_style!r})",
                err=True,
            )
            raise typer.Exit(2)
        overrides["link_style"] = link_style
    if output:
        overrides["output"] = output
    if report_path:
        overrides["report"] = report_path
    if github_issue:
        overrides["github_issue"] = True
    if repo:
        overrides["github_repo"] = repo
    if format is not None:
        overrides["format"] = format

    # Load ignore/js domain files and skip URL file
    ignore_set = _read_domains(ignore_domains)
    js_set = _read_domains(js_domains)
    skip_set = _read_domains(skip_urls)
    if ignore_set:
        overrides["ignore_domains"] = ignore_set
    if js_set:
        overrides["js_domains"] = js_set
    if skip_set:
        overrides["skip_urls"] = skip_set

    config = _load_and_validate(config_file, _ALL_FORMATS, **overrides)

    if config.js_domains:
        try:
            import playwright  # noqa: F401
        except ImportError:
            typer.echo(
                "[linksanity] Playwright is required for --js-domains.\n"
                "Install it: pip install linksanity[browser] && playwright install chromium",
                err=True,
            )
            raise typer.Exit(2) from None

    if github_issue and not repo and not config.github_repo:
        typer.echo("[linksanity] --repo is required with --github-issue", err=True)
        raise typer.Exit(2)

    queue = asyncio.run(run_scan(paths, config))
    results = queue.results()

    if config.baseline:
        from linksanity.baseline import load_baseline, only_new  # noqa: I001
        results = only_new(results, load_baseline(Path(config.baseline)))

    if config.output:
        try:
            with open(config.output, "w", encoding="utf-8") as fh:
                report(results, config, file=fh)
        except OSError as exc:
            typer.echo(f"[linksanity] cannot write output: {exc}", err=True)
            raise typer.Exit(2) from exc
    else:
        report(results, config)

    if config.report:
        try:
            from linksanity.reporters.markdown_reporter import report as md_report  # noqa: I001
            with open(config.report, "w", encoding="utf-8") as fh:
                md_report(results, file=fh)
        except OSError as exc:
            typer.echo(f"[linksanity] cannot write report: {exc}", err=True)
            raise typer.Exit(2) from exc

    if config.github_issue:
        _run_github_reporter(results, config)

    if _annotations_enabled(config):
        _run_annotations_reporter(results)

    broken = sum(1 for r in results if r.status in FAILING_STATUSES)
    raise typer.Exit(1 if broken else 0)


def _run_github_reporter(results: list[LinkResult], config: Config) -> None:
    from linksanity.reporters.github_reporter import report as gh_report  # noqa: I001
    gh_report(results, config)


# ── fix ───────────────────────────────────────────────────────────────────────

_URL_ARG = re.compile(r"^https?://", re.IGNORECASE)


def _proposal_dict(p: FixProposal) -> dict[str, object]:
    """The public JSON proposal schema — agents parse this, keep it stable."""
    return {
        "source_file": p.source_file,
        "line": p.line,
        "old_url": p.old_url,
        "new_url": p.new_url,
        "kind": p.kind.value,
        "auto_applicable": p.auto_applicable,
        "detail": p.detail,
    }


def _render_suggestions(proposals: list[FixProposal]) -> list[str]:
    suggestions = [p for p in proposals if not p.auto_applicable]
    if not suggestions:
        return []
    lines = ["", "Suggestions (need a human decision, never applied automatically):"]
    for p in suggestions:
        lines.append(f"  {p.source_file}:{p.line} [{p.kind.value}] {p.old_url} → {p.new_url}")
        lines.append(f"    {p.detail}")
    return lines


def _render_fix_output(proposals: list[FixProposal], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(
            [_proposal_dict(p) for p in proposals], indent=2, ensure_ascii=False
        ) + "\n"

    lines: list[str] = []
    diff = render_diff(proposals)
    if diff:
        lines.append("Proposed fixes (dry run — rerun with --write to apply):")
        lines.append(diff)
    lines.extend(_render_suggestions(proposals))
    return "\n".join(lines) + "\n"


def _emit(text: str, output: str | None) -> None:
    if not output:
        typer.echo(text, nl=False)
        return
    try:
        Path(output).write_text(text, encoding="utf-8")
    except OSError as exc:
        typer.echo(f"[linksanity] cannot write output: {exc}", err=True)
        raise typer.Exit(2) from exc


def _check_clean_tree(proposals: list[FixProposal], force: bool) -> None:
    """Refuse to rewrite files with uncommitted changes unless forced."""
    from linksanity import git_utils  # noqa: I001

    targets = sorted({p.source_file for p in proposals if p.auto_applicable})
    if not targets:
        return
    # Resolve first: source_file is relative to the invocation cwd, but git runs
    # from the target's own directory, which would resolve a relative pathspec
    # against the wrong base and silently report a dirty tree as clean.
    resolved = [Path(t).resolve() for t in targets]
    dirty = git_utils.is_dirty(resolved, cwd=resolved[0].parent)
    if dirty is None:
        typer.echo(
            "[linksanity] not a git repository — writing without a dirty-tree check",
            err=True,
        )
    elif dirty and not force:
        typer.echo(
            "[linksanity] refusing to write: the files to fix have uncommitted "
            "changes, which --write could clobber.\n"
            "  Commit or stash them first, or rerun with --force to write anyway.",
            err=True,
        )
        raise typer.Exit(2)


@app.command()
def fix(
    paths: list[str] = typer.Argument(..., help="Files, directories, or glob patterns"),  # noqa: B008
    config_file: str | None = typer.Option(
        None, "--config", "-c", help="Path to linksanity.toml config file"
    ),
    workers: int | None = typer.Option(None, help="Max concurrent HTTP checks"),
    timeout: int | None = typer.Option(None, help="Per-request timeout in seconds"),
    retry: int | None = typer.Option(None, help="Number of retries on 429/503"),
    check_anchors: bool = typer.Option(False, help="Validate anchor fragments"),
    check_images: bool = typer.Option(
        False, help="Also validate <img src> / ![]() image targets, not just links"
    ),
    link_style: str | None = typer.Option(
        None, help="Relative-link resolution preset for built docs sites: mkdocs, docusaurus, sphinx"
    ),
    ignore_domains: str | None = typer.Option(
        None, help="File listing domains to skip (one per line)"
    ),
    skip_urls: str | None = typer.Option(
        None, help="File listing URLs or patterns to skip (one per line, * wildcards ok)"
    ),
    cache: str | None = typer.Option(None, help="Path to a local cache file"),
    cache_ttl: int | None = typer.Option(
        None, help="Seconds a cached link result stays valid (default 86400)"
    ),
    write: bool = typer.Option(
        False, "--write", help="Apply auto-applicable fixes to source files (default: dry run)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Apply even when the files to fix have uncommitted changes"
    ),
    redirects: str = typer.Option(
        "permanent",
        help="Which redirects to auto-apply: permanent (301/308 only) or all (also 302/307)",
    ),
    wayback: bool = typer.Option(
        False, help="Also suggest archive.org snapshots for dead external links"
    ),
    format: str | None = typer.Option(
        None, help="Output format: console, json (default: console)"
    ),
    output: str | None = typer.Option(None, help="Write proposals to this file"),
) -> None:
    """Propose fixes for broken and redirected links, and optionally apply them."""
    urls = [p for p in paths if _URL_ARG.match(p)]
    if urls:
        typer.echo(
            f"[linksanity] fix works on local source files, not URLs (got {urls[0]!r}).\n"
            "  It rewrites the files a link lives in, which a crawl cannot do.\n"
            "  Use 'linksanity scan' on the source files, or 'linksanity crawl' to check a live site.",
            err=True,
        )
        raise typer.Exit(2)
    if redirects not in ("permanent", "all"):
        typer.echo(
            f"[linksanity] --redirects must be one of: permanent, all (got {redirects!r})",
            err=True,
        )
        raise typer.Exit(2)
    if link_style is not None and link_style not in ("mkdocs", "docusaurus", "sphinx"):
        typer.echo(
            f"[linksanity] --link-style must be one of: mkdocs, docusaurus, sphinx "
            f"(got {link_style!r})",
            err=True,
        )
        raise typer.Exit(2)

    overrides: dict[str, object] = {}
    if workers is not None:
        overrides["workers"] = workers
    if timeout is not None:
        overrides["timeout"] = timeout
    if retry is not None:
        overrides["retry"] = retry
    if check_anchors:
        overrides["check_anchors"] = True
    if check_images:
        overrides["check_images"] = True
    if link_style:
        overrides["link_style"] = link_style
    if cache:
        overrides["cache_file"] = cache
    if cache_ttl is not None:
        overrides["cache_ttl"] = cache_ttl
    if format is not None:
        overrides["format"] = format
    if output:
        overrides["output"] = output

    ignore_set = _read_domains(ignore_domains)
    skip_set = _read_domains(skip_urls)
    if ignore_set:
        overrides["ignore_domains"] = ignore_set
    if skip_set:
        overrides["skip_urls"] = skip_set

    config = _load_and_validate(config_file, _CONSOLE_JSON_FORMATS, **overrides)

    if config.js_domains:
        try:
            import playwright  # noqa: F401
        except ImportError:
            typer.echo(
                "[linksanity] Playwright is required for --js-domains.\n"
                "Install it: pip install linksanity[browser] && playwright install chromium",
                err=True,
            )
            raise typer.Exit(2) from None

    proposals = asyncio.run(_collect_proposals(paths, config, redirects, wayback))

    if not proposals:
        typer.echo("[linksanity] nothing to fix", err=True)
        if config.format == "json":
            # Keep --format json structurally identical whether or not there are
            # proposals: an empty array, not silence, so a parser downstream
            # doesn't have to special-case "no output at all".
            _emit(_render_fix_output(proposals, config.format), config.output)
        raise typer.Exit(0)

    if not write:
        _emit(_render_fix_output(proposals, config.format), config.output)
        raise typer.Exit(1)

    _check_clean_tree(proposals, force)
    applied, modified = apply_proposals(proposals)

    if config.format == "json":
        _emit(_render_fix_output(proposals, config.format), config.output)
    else:
        lines = (
            [f"Applied {applied} fix(es) across {len(modified)} file(s):"]
            + [f"  {m}" for m in modified]
            if modified
            else ["No auto-applicable fixes to write."]
        )
        lines.extend(_render_suggestions(proposals))
        _emit("\n".join(lines) + "\n", config.output)

    raise typer.Exit(1)


async def _collect_proposals(
    paths: list[str], config: Config, redirects: str, wayback: bool
) -> list[FixProposal]:
    """Run the scan once and turn its results into every class of proposal."""
    queue = await run_scan(paths, config)
    results = queue.results()

    proposals = build_redirect_proposals(results, queue, all_redirects=redirects == "all")
    proposals += build_moved_file_proposals(results, queue, queue.corpus_files)
    if wayback:
        proposals += await build_wayback_proposals(
            results, queue, timeout=config.timeout, workers=config.workers
        )
    return proposals


@app.command()
def crawl(
    url: str = typer.Argument(..., help="Start URL to crawl"),  # noqa: B008
    config_file: str | None = typer.Option(
        None, "--config", "-c", help="Path to linksanity.toml config file"
    ),
    workers: int | None = typer.Option(None, help="Max concurrent HTTP checks"),
    playwright_workers: int | None = typer.Option(None, help="Max concurrent browser sessions"),
    timeout: int | None = typer.Option(None, help="Per-request timeout in seconds"),
    retry: int | None = typer.Option(None, help="Number of retries on 429/503"),
    max_pages: int | None = typer.Option(None, help="Max pages to crawl (default 500)"),
    check_anchors: bool = typer.Option(
        False, help="Validate same-page anchor fragments against crawled pages"
    ),
    ignore_domains: str | None = typer.Option(
        None, help="File listing domains to skip (one per line)"
    ),
    skip_urls: str | None = typer.Option(
        None, help="File listing URLs or patterns to skip, e.g. auth-gated pages (one per line, * wildcards ok)"
    ),
    block_analytics: bool = typer.Option(
        False, help="Block and ignore requests to common analytics/tracking domains"
    ),
    format: str | None = typer.Option(
        None, help="Output format: console, json, csv (default: console)"
    ),
    output: str | None = typer.Option(None, help="Write results to this file"),
    report_path: str | None = typer.Option(
        None, "--report", help="Write Markdown summary report to this file"
    ),
    github_issue: bool = typer.Option(False, help="Open a GitHub Issue for broken links"),
    repo: str | None = typer.Option(
        None, help="GitHub repo in OWNER/REPO format (required with --github-issue)"
    ),
    max_redirects: int | None = typer.Option(
        None, help="Max redirect hops before flagging as too-many-redirects"
    ),
    annotations: bool | None = typer.Option(
        None,
        "--annotations/--no-annotations",
        help="Emit GitHub Actions ::error/::warning annotations (default: auto-detect CI)",
    ),
) -> None:
    """Crawl a live site and check all links."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        typer.echo(
            "[linksanity] Playwright is required for crawl mode.\n"
            "Install it: pip install linksanity[browser] && playwright install chromium",
            err=True,
        )
        raise typer.Exit(2) from None

    overrides: dict[str, object] = {}
    if workers is not None:
        overrides["workers"] = workers
    if playwright_workers is not None:
        overrides["playwright_workers"] = playwright_workers
    if timeout is not None:
        overrides["timeout"] = timeout
    if retry is not None:
        overrides["retry"] = retry
    if max_pages is not None:
        overrides["max_pages"] = max_pages
    if check_anchors:
        overrides["check_anchors"] = True
    if output:
        overrides["output"] = output
    if report_path:
        overrides["report"] = report_path
    if github_issue:
        overrides["github_issue"] = True
    if repo:
        overrides["github_repo"] = repo
    if max_redirects is not None:
        overrides["max_redirects"] = max_redirects
    if annotations is not None:
        overrides["annotations"] = annotations
    if format is not None:
        overrides["format"] = format

    ignore_set = _read_domains(ignore_domains)
    skip_set = _read_domains(skip_urls)
    if ignore_set:
        overrides["ignore_domains"] = ignore_set
    if skip_set:
        overrides["skip_urls"] = skip_set
    if block_analytics:
        overrides["block_analytics"] = True

    config = _load_and_validate(config_file, _ALL_FORMATS, **overrides)

    if github_issue and not repo and not config.github_repo:
        typer.echo("[linksanity] --repo is required with --github-issue", err=True)
        raise typer.Exit(2)

    from linksanity.crawler import run_crawl  # noqa: I001
    queue = asyncio.run(run_crawl(url, config))
    results = queue.results()

    if config.output:
        try:
            with open(config.output, "w", encoding="utf-8") as fh:
                report(results, config, file=fh)
        except OSError as exc:
            typer.echo(f"[linksanity] cannot write output: {exc}", err=True)
            raise typer.Exit(2) from exc
    else:
        report(results, config)

    if config.report:
        try:
            from linksanity.reporters.markdown_reporter import report as md_report  # noqa: I001
            with open(config.report, "w", encoding="utf-8") as fh:
                md_report(results, file=fh)
        except OSError as exc:
            typer.echo(f"[linksanity] cannot write report: {exc}", err=True)
            raise typer.Exit(2) from exc

    if config.github_issue:
        _run_github_reporter(results, config)

    if _annotations_enabled(config):
        _run_annotations_reporter(results)

    summary = queue.summary()
    broken = sum(summary.get(s.value, 0) for s in FAILING_STATUSES)
    raise typer.Exit(1 if broken else 0)


# ── init ─────────────────────────────────────────────────────────────────────

_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.ya?ml$")
_COMPETING_CHECKERS = ("lychee", "markdown-link-check", "linkinator")


def _stdin_is_tty() -> bool:
    """Whether stdin is a real terminal.

    A thin, separately-named wrapper around `sys.stdin.isatty()` so tests can
    monkeypatch `linksanity.cli._stdin_is_tty` to simulate an interactive
    terminal — `typer.testing.CliRunner` always replaces stdin with a
    non-terminal stream, so without this seam none of the interactive prompt
    flows could be exercised in tests.

    A closed stdin (e.g. `python -m linksanity init 0<&-`) makes `sys.stdin`
    `None`, and some non-terminal stream objects raise (rather than return
    `False`) from `isatty()`. Both are treated as "not a tty" so the caller
    falls into the existing exit-2-with-guidance branch instead of dying on
    an uncaught `AttributeError`/`ValueError`.
    """
    stdin = sys.stdin
    if stdin is None:
        return False
    try:
        return stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _validate_workflow_name(name: str) -> None:
    """Reject anything that is not a bare `*.yml`/`*.yaml` filename.

    Path separators are rejected here (the regex has none in its character
    class) so the generated file can never escape `.github/workflows/`.
    """
    if not _WORKFLOW_NAME_RE.match(name):
        typer.echo(
            "[linksanity] --workflow-name must be a bare filename matching "
            f"[A-Za-z0-9._-]+.ya?ml, with no path separators (got {name!r})",
            err=True,
        )
        raise typer.Exit(2)


def _validate_path_values(values: list[str]) -> None:
    """Refuse any --paths value that action.yml's unquoted word-split can't represent.

    Reuses init.py's own `_is_safe_name`/`_refusal_reason` rather than
    retyping the `[A-Za-z0-9._/-]+` rule a second time.
    """
    for value in values:
        bare = value.rstrip("/")
        if not _is_safe_name(bare):
            typer.echo(
                f"[linksanity] cannot use --paths {value!r}: {_refusal_reason(bare)}",
                err=True,
            )
            raise typer.Exit(2)


def _detect_competing_checkers(root: Path) -> list[str]:
    """Return the names of any competing link checkers configured in .github/workflows/."""
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    found: set[str] = set()
    for pattern in ("*.yml", "*.yaml"):
        for wf in workflows_dir.glob(pattern):
            try:
                text = wf.read_text(encoding="utf-8").lower()
            except OSError:
                continue
            for tool in _COMPETING_CHECKERS:
                if tool in text:
                    found.add(tool)
    return sorted(found)


def _print_detection_notes(console: Console, detection: DetectionResult) -> None:
    """Surface refused candidates and the HTML-fallback note, so nothing is silently dropped."""
    if detection.refused:
        console.print("[yellow]Excluded (cannot be represented in a paths: value):[/yellow]")
        for r in detection.refused:
            console.print(f"  {r.path} — {r.reason}")
    if detection.used_html_fallback:
        console.print(
            "[dim]No Markdown/RST/AsciiDoc/MDX docs found; proposing HTML-only "
            "documentation directories instead.[/dim]"
        )


def _select_paths(console: Console, proposals: list[Proposal]) -> list[str]:
    """Show the detected proposals in a table, preselected, and let the user edit the selection."""
    table = Table(title="Detected documentation paths")
    table.add_column("#", justify="right")
    table.add_column("Path")
    table.add_column("Files", justify="right")
    for i, p in enumerate(proposals, start=1):
        table.add_row(str(i), p.path, str(p.file_count))
    console.print(table)

    default_selection = ",".join(str(i) for i in range(1, len(proposals) + 1))
    answer = typer.prompt(
        "Paths to include (comma-separated numbers, or 'none' to select nothing)",
        default=default_selection,
    )
    if answer.strip().lower() == "none":
        return []

    indices: list[int] = []
    for token in answer.split(","):
        token = token.strip()
        if token.isdigit() and 1 <= int(token) <= len(proposals):
            indices.append(int(token))
    return [proposals[i - 1].path for i in dict.fromkeys(indices)]


def _prompt_manual_path(console: Console) -> str | None:
    """Ask for a path to scan when detection found nothing. Returns None on decline."""
    console.print(
        "No documentation directories detected. Searched for "
        f"{', '.join(_SUFFIXES)} files, pruning dot-directories and "
        f"{', '.join(sorted(_DENYLIST))} (case-insensitive)."
    )
    answer = typer.prompt("Path to scan (leave blank to cancel)", default="")
    answer = answer.strip()
    return answer or None


async def _timed_scan(patterns: list[str], config: Config) -> tuple[LinkQueue, float]:
    """Run `run_scan()` behind a rich.status spinner showing elapsed time.

    `run_scan` is already async, so it is driven with a plain
    `asyncio.create_task` + polling loop rather than a background thread.
    That is the whole point: if the process receives Ctrl-C while this
    coroutine is running, `asyncio.run()` (in the caller) cancels this
    coroutine's still-pending task on shutdown, and cancellation propagates
    into `run_scan`, letting it close its aiohttp/httpx session cleanly. A
    background thread running its own `asyncio.run()` cannot be cancelled
    like that -- it would keep the session open past the interrupted
    process, which is exactly the failure mode this rewrite removes.
    """
    console = Console()
    start = time.monotonic()
    task = asyncio.create_task(run_scan(patterns, config))
    with console.status("Measuring...") as status:
        while not task.done():
            await asyncio.wait([task], timeout=0.2)
            status.update(f"Measuring... {int(time.monotonic() - start)}s")
    elapsed = time.monotonic() - start

    return await task, elapsed


@app.command(name="init")
def init_cmd(
    yes: bool = typer.Option(
        False, "--yes", help="Run non-interactively; requires --paths"
    ),
    paths: list[str] | None = typer.Option(  # noqa: B008
        None, "--paths", help="Paths to scan for `paths:` (skips detection)"
    ),
    no_baseline: bool = typer.Option(
        False, "--no-baseline", help="Skip baseline generation even if breakage is found"
    ),
    no_measure: bool = typer.Option(
        False,
        "--no-measure",
        help="Skip the timed scan entirely: no estimate, no baseline (offline/air-gapped use)",
    ),
    workflow_name: str = typer.Option(
        "linkcheck.yml",
        "--workflow-name",
        help="Filename for the generated workflow: a bare name, no path separators",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the generated files; write nothing"
    ),
) -> None:
    """Detect documentation paths, measure a link check, and write a CI workflow."""
    console = Console()

    _validate_workflow_name(workflow_name)

    if yes and not paths:
        typer.echo(
            "[linksanity] --yes requires --paths (a non-interactive run must state "
            "what to scan)",
            err=True,
        )
        raise typer.Exit(2)

    if not yes and not _stdin_is_tty():
        typer.echo(
            "[linksanity] stdin is not a TTY, so interactive prompts would hang; "
            "rerun with --yes --paths <dir> for a non-interactive run",
            err=True,
        )
        raise typer.Exit(2)

    root = Path.cwd()
    detection: DetectionResult | None = None

    if paths:
        _validate_path_values(paths)
        selected = list(paths)
    else:
        detection = detect_paths(root)
        _print_detection_notes(console, detection)
        if not detection.proposals:
            manual = _prompt_manual_path(console)
            if manual is None:
                typer.echo("[linksanity] no path given; nothing to scan", err=True)
                raise typer.Exit(2)
            _validate_path_values([manual])
            selected = [manual]
        else:
            selected = _select_paths(console, detection.proposals)
            if not selected:
                typer.echo("[linksanity] no paths selected; nothing to scan", err=True)
                raise typer.Exit(2)

    competing = _detect_competing_checkers(root)
    if competing:
        names = ", ".join(competing)
        if yes:
            typer.echo(
                f"[linksanity] warning: competing link checker(s) already configured: "
                f"{names}",
                err=True,
            )
        elif not typer.confirm(
            f"Found competing link checker(s) already configured in .github/workflows/: "
            f"{names}. Continue anyway?",
            default=False,
        ):
            raise typer.Exit(2)

    workflow_path = Path(".github") / "workflows" / workflow_name
    if workflow_path.exists():
        if yes:
            typer.echo(
                f"[linksanity] {workflow_path} already exists; refusing to overwrite "
                "under --yes",
                err=True,
            )
            raise typer.Exit(2)
        if not typer.confirm(f"{workflow_path} already exists. Overwrite it?", default=False):
            raise typer.Exit(2)

    results: list[LinkResult] = []
    breakage = False

    if no_measure:
        typer.echo("[linksanity] --no-measure: skipping the scan, estimate, and baseline")
    else:
        config_path = _resolve_config_path(None)
        config = _measuring_config_or_exit(config_path)
        try:
            queue, elapsed = asyncio.run(_timed_scan(selected, config))
        except Exception as exc:
            typer.echo(f"[linksanity] measuring scan failed: {exc}", err=True)
            raise typer.Exit(2) from exc

        results = queue.results()
        unique_urls = len(results)
        unique_domains = len({urlparse(r.url).netloc for r in results if r.url})
        for line in render_estimate(elapsed, unique_urls, unique_domains):
            typer.echo(line)

        if detection is not None:
            detected_total = sum(
                p.file_count for p in detection.proposals if p.path in selected
            )
            warning = count_divergence_warning(detected_total, len(queue.corpus_files))
            if warning:
                typer.echo("")
                typer.echo(f"[linksanity] {warning}", err=True)

        breakage = any(r.status in FAILING_STATUSES for r in results)

    write_baseline = False
    if breakage and not no_baseline:
        broken_count = sum(1 for r in results if r.status in FAILING_STATUSES)
        if yes:
            write_baseline = True
        else:
            write_baseline = typer.confirm(
                f"The measuring scan found {broken_count} pre-existing broken link(s). "
                "Write a baseline so CI only fails on new breakage?",
                default=True,
            )

    baseline_path = Path(".linksanity-baseline.json")
    if write_baseline and baseline_path.exists():
        if yes:
            typer.echo(
                f"[linksanity] {baseline_path} already exists; refusing to overwrite "
                "under --yes",
                err=True,
            )
            raise typer.Exit(2)
        if not typer.confirm(f"{baseline_path} already exists. Overwrite it?", default=False):
            write_baseline = False

    workflow_text = render_workflow(
        selected, baseline_path=str(baseline_path) if write_baseline else None
    )

    if dry_run:
        typer.echo(workflow_text, nl=False)
        if write_baseline:
            broken_count = sum(1 for r in results if r.status in FAILING_STATUSES)
            typer.echo(f"Baseline: {broken_count} known-broken link(s) -> {baseline_path}")
        raise typer.Exit(0)

    try:
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(workflow_text, encoding="utf-8")
    except OSError as exc:
        typer.echo(f"[linksanity] cannot write {workflow_path}: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Wrote {workflow_path}")

    targets = [str(workflow_path)]
    if write_baseline:
        from linksanity.reporters.json_reporter import report as _json_report  # noqa: I001

        try:
            with open(baseline_path, "w", encoding="utf-8") as fh:
                _json_report(results, file=fh)
        except OSError as exc:
            typer.echo(f"[linksanity] cannot write {baseline_path}: {exc}", err=True)
            raise typer.Exit(2) from exc
        broken_count = sum(1 for r in results if r.status in FAILING_STATUSES)
        typer.echo(f"Wrote {baseline_path}  ({broken_count} known-broken links)")
        targets.append(str(baseline_path))

    typer.echo("")
    typer.echo("  git add " + " ".join(targets))
    typer.echo('  git commit -m "Add linksanity link checking"')

    raise typer.Exit(0)
