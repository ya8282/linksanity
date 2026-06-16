"""CLI entry point for linksanity."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from linksanity.config import Config, load_config
from linksanity.queue import LinkResult
from linksanity.reporters import report
from linksanity.scanner import run_scan

app = typer.Typer(
    name="linksanity",
    help="Detect broken links in Markdown, reStructuredText, and HTML documentation.",
    no_args_is_help=True,
)


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
    ignore_domains: str | None = typer.Option(
        None, help="File listing domains to skip (one per line)"
    ),
    js_domains: str | None = typer.Option(
        None, help="File listing domains that require a browser (Playwright)"
    ),
    format: str = typer.Option("console", help="Output format: console, json, csv"),
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
    if output:
        overrides["output"] = output
    if report_path:
        overrides["report"] = report_path
    if github_issue:
        overrides["github_issue"] = True
    if repo:
        overrides["github_repo"] = repo
    overrides["format"] = format

    # Load ignore/js domain files
    ignore_set = _read_domains(ignore_domains)
    js_set = _read_domains(js_domains)
    if ignore_set:
        overrides["ignore_domains"] = ignore_set
    if js_set:
        overrides["js_domains"] = js_set

    config_path = Path(config_file) if config_file else None
    if config_path is None:
        default = Path.cwd() / "linksanity.toml"
        if default.exists():
            config_path = default

    config = load_config(config_path, **overrides)

    if github_issue and not repo and not config.github_repo:
        typer.echo("[linksanity] --repo is required with --github-issue", err=True)
        raise typer.Exit(2)

    queue = asyncio.run(run_scan(paths, config))
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

    summary = queue.summary()
    broken = summary.get("broken", 0) + summary.get("error", 0)
    raise typer.Exit(1 if broken else 0)


def _run_github_reporter(results: list[LinkResult], config: Config) -> None:
    from linksanity.reporters.github_reporter import report as gh_report  # noqa: I001
    gh_report(results, config)


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
    ignore_domains: str | None = typer.Option(
        None, help="File listing domains to skip (one per line)"
    ),
    format: str = typer.Option("console", help="Output format: console, json, csv"),
    output: str | None = typer.Option(None, help="Write results to this file"),
    report_path: str | None = typer.Option(
        None, "--report", help="Write Markdown summary report to this file"
    ),
    github_issue: bool = typer.Option(False, help="Open a GitHub Issue for broken links"),
    repo: str | None = typer.Option(
        None, help="GitHub repo in OWNER/REPO format (required with --github-issue)"
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
    if output:
        overrides["output"] = output
    if report_path:
        overrides["report"] = report_path
    if github_issue:
        overrides["github_issue"] = True
    if repo:
        overrides["github_repo"] = repo
    overrides["format"] = format

    ignore_set = _read_domains(ignore_domains)
    if ignore_set:
        overrides["ignore_domains"] = ignore_set

    config_path = Path(config_file) if config_file else None
    if config_path is None:
        default = Path.cwd() / "linksanity.toml"
        if default.exists():
            config_path = default

    config = load_config(config_path, **overrides)

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

    summary = queue.summary()
    broken = summary.get("broken", 0) + summary.get("error", 0)
    raise typer.Exit(1 if broken else 0)
