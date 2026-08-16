"""CLI entry point for linksanity."""

from __future__ import annotations

import asyncio
import json
import os
import re
from enum import Enum
from pathlib import Path

import typer

from linksanity.config import Config, ConfigError, load_config
from linksanity.fixer import (
    FixProposal,
    apply_proposals,
    build_moved_file_proposals,
    build_redirect_proposals,
    build_wayback_proposals,
    render_diff,
)
from linksanity.queue import FAILING_STATUSES, LinkResult
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
    return not (config.format in ("json", "csv") and not config.output)


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
    offending path (see linksanity.config._location), so nothing is lost
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
