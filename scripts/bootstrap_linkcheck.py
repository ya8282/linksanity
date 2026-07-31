#!/usr/bin/env python3
"""Generate a GitHub Actions link-check workflow file for a target repo.

Usage:
    python scripts/bootstrap_linkcheck.py --url https://example.com [options]
    python scripts/bootstrap_linkcheck.py --repo ../some-other-repo --yes \\
        --url https://example.com --schedule "0 8 * * 1" --max-pages 200

Writes a `.github/workflows/<name>.yml` file into --repo (default: the
current directory) that runs `linksanity crawl <url>` on a schedule via
GitHub Actions, following the same pattern as the hand-written workflow
originally committed to ya8282/resume for https://chrischo.org.

Without --yes, prompts interactively via input() for any option not
supplied on the command line, showing the default in brackets. Pass --yes
to skip all prompting and use CLI values or defaults; --url then becomes
required since it has no sensible default.

stdlib only; no third-party dependencies.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_SCHEDULE = "0 8 * * 1"
DEFAULT_MAX_PAGES = 200
DEFAULT_WORKFLOW_NAME = "linkcheck.yml"

# Latest linksanity release on PyPI. The generated workflow pins this rather
# than floating on latest: this script renders flags from the dev tree, so an
# unpinned install silently drifts into "No such option" failures whenever the
# CLI gains or renames a flag. Bump on release.
DEFAULT_LINKSANITY_VERSION = "0.2.0"

# `crawl --check-anchors` did not exist until 0.2.0 -- it was scan-only before
# that. Emitting it against an older pin fails the job with "No such option".
CHECK_ANCHORS_MIN_VERSION = "0.2.0"

# The `.status` values (from the stable results JSON schema) that count as a
# failure in the generated workflow's own jq-based reporting. This must NOT
# import linksanity.queue.FAILING_STATUSES: the rendered workflow installs a
# pinned PyPI release (DEFAULT_LINKSANITY_VERSION), not this dev tree, so the
# generated YAML has to key off the stable JSON string values rather than a
# dev-tree Python constant. Single-sourced here so the jq filters in
# render_workflow's report_step (count, annotations, summary table) cannot
# drift from each other again.
FAILING_STATUS_VALUES: tuple[str, ...] = ("broken", "error", "too_many_redirects")


def _jq_status_select() -> str:
    """Build the jq boolean expression selecting failing statuses.

    e.g. '.status=="broken" or .status=="error" or .status=="too_many_redirects"'
    """
    return " or ".join(f'.status=="{status}"' for status in FAILING_STATUS_VALUES)

_TRUTHY = {"y", "yes", "true", "1"}


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' into a comparable tuple, ignoring any suffix on each part.

    ponytail: leading-digits parse, correct for the X.Y.Z and X.Y.Zrc1 forms
    linksanity actually publishes. Swap in packaging.version if pre-release
    ordering ever has to be exact.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def ask(prompt: str, default: str) -> str:
    """Prompt via input(), returning `default` on an empty (Enter-only) response."""
    response = input(f"{prompt} [{default}]: ").strip()
    return response if response else default


def render_workflow(
    *,
    url: str,
    schedule: str,
    max_pages: int,
    check_anchors: bool,
    block_analytics: bool,
    version: str = DEFAULT_LINKSANITY_VERSION,
) -> str:
    """Render the GitHub Actions workflow YAML as a plain string.

    No YAML library is used -- this file's structure is fixed and simple
    enough that an f-string is clearer and dependency-free.
    """
    crawl_lines = [f"          linksanity crawl {url} \\"]
    if check_anchors:
        crawl_lines.append("            --check-anchors \\")
    if block_analytics:
        crawl_lines.append("            --block-analytics \\")
    crawl_lines.append(f"            --max-pages {max_pages} \\")
    crawl_lines.append("            --format json \\")
    crawl_lines.append("            --output crawl-results.json")
    crawl_step = "\n".join(crawl_lines)

    # Report failing links ourselves from the JSON results via jq rather than
    # relying on linksanity's --annotations flag: the JSON schema is stable
    # across releases, so this keeps working no matter which version the pin
    # names, and it also produces a $GITHUB_STEP_SUMMARY table that
    # --annotations does not. One inline ::error:: annotation per failing link
    # (see FAILING_STATUS_VALUES for what counts as failing) plus that table.
    # In crawl mode `source_file` is the page URL a link was found on, not a
    # repo path, so (unlike the scan action) there is no meaningful
    # file=/line= to attach -- fold the source page into the message text
    # instead. This step decides the job's pass/fail verdict itself, from
    # failing_count below, rather than deferring to the crawl step's exit
    # code: on the published DEFAULT_LINKSANITY_VERSION pin (0.2.0), crawl's
    # own exit is broken+error only, so a too_many_redirects-only run exits 0
    # there (that status only started failing crawl's own exit on main,
    # unreleased as of this writing). Keying the verdict off
    # FAILING_STATUS_VALUES here keeps it correct no matter which linksanity
    # version is pinned.
    status_select = _jq_status_select()
    report_step = r"""      - name: Report failing links
        if: always()
        run: |
          RESULTS=crawl-results.json
          # If the crawl step produced no results file at all, it already
          # failed the job on its own nonzero exit -- deliberately not an
          # additional failure here, just nothing to report on.
          if [ -f "$RESULTS" ] && [ -s "$RESULTS" ]; then
            # A jq parse failure is not "zero failing links": fail loudly
            # rather than let a corrupt results file read as a silent green.
            if ! failing_count=$(jq '[.[] | select(__STATUS_SELECT__)] | length' "$RESULTS" 2>&1); then
              echo "::error::could not parse $RESULTS with jq: $failing_count"
              exit 1
            fi
            case "$failing_count" in
              (''|*[!0-9]*)
                echo "::error::jq returned a non-numeric failing count: $failing_count"
                exit 1
                ;;
            esac
            if [ "$failing_count" -gt 0 ]; then
              # .error (and, more rarely, .url/.source_file) can be arbitrary
              # third-party text -- e.g. a Playwright exception string -- and
              # may contain embedded CR/LF. Left unsanitized, jq -r would emit
              # that newline literally and `while read` would split it into a
              # second "line" that GitHub parses as its own, attacker-controlled
              # ::error:: annotation. Collapse CR/LF to a space before use.
              jq -r '
                .[]
                | select(__STATUS_SELECT__)
                | . as $r
                | ($r.source_file // "" | gsub("[\r\n]+"; " ")) as $source
                | ($r.url // "" | gsub("[\r\n]+"; " ")) as $url
                | (if $r.http_code != null then ($r.http_code|tostring) elif $r.error != null then ($r.error|tostring) else "" end | gsub("[\r\n]+"; " ")) as $detail
                | "::error::" + $url + " (found on " + $source + ") — " + ($r.status // "") + (if $detail == "" then "" else " " + $detail end)
              ' "$RESULTS" | while IFS= read -r annotation; do
                printf '%s\n' "$annotation"
              done || true

              if [ -n "$GITHUB_STEP_SUMMARY" ]; then
                {
                  echo "### $failing_count failing link(s) found"
                  echo ""
                  echo "| Source page | URL | Status | Detail |"
                  echo "| --- | --- | --- | --- |"
                  jq -r '
                    .[]
                    | select(__STATUS_SELECT__)
                    | . as $r
                    | ($r.source_file // "" | gsub("[\r\n]+"; " ")) as $source
                    | ($r.url // "" | gsub("[\r\n]+"; " ")) as $url
                    | (if $r.http_code != null then ($r.http_code|tostring) elif $r.error != null then ($r.error|tostring) else "" end | gsub("[\r\n]+"; " ")) as $detail
                    | "| " + ($source | gsub("\\|"; "\\|")) + " | " + ($url | gsub("\\|"; "\\|")) + " | " + ($r.status // "") + " | " + ($detail | gsub("\\|"; "\\|")) + " |"
                  ' "$RESULTS"
                } >> "$GITHUB_STEP_SUMMARY" || true
              fi

              exit 1
            fi
          fi""".replace("__STATUS_SELECT__", status_select)

    return f"""# Crawls {url} and fails the job if any link is failing.
name: Link check

on:
  workflow_dispatch:        # manual "Run workflow" button
  schedule:
    - cron: "{schedule}"

permissions:
  contents: read

jobs:
  linkcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # only needed if you keep a .linksanity-skip file in the repo

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install linksanity
        run: |
          pip install "linksanity[browser]=={version}"
          playwright install --with-deps chromium

      - name: Crawl {url}
        run: |
{crawl_step}

{report_step}

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: linkcheck-results
          path: crawl-results.json
"""


def _git_commit(repo_path: Path, target_path: Path) -> None:
    """Stage and commit the generated workflow file. Never pushes."""
    rel_path = target_path.relative_to(repo_path)

    add = subprocess.run(
        ["git", "add", str(rel_path)], cwd=repo_path, capture_output=True, text=True
    )
    if add.returncode != 0:
        print(f"error: git add failed:\n{add.stderr}", file=sys.stderr)
        sys.exit(1)

    commit = subprocess.run(
        ["git", "commit", "-m", f"Add link-check GitHub Actions workflow ({rel_path})"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        print(f"error: git commit failed:\n{commit.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"committed {rel_path}")


def build_parser() -> argparse.ArgumentParser:
    doc_lines = __doc__.splitlines() if __doc__ else []
    parser = argparse.ArgumentParser(
        description=doc_lines[0] if doc_lines else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(doc_lines[1:]).strip() if len(doc_lines) > 1 else None,
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Target repository root to install the workflow into (default: '.')",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Site URL to crawl (no default; required when --yes is passed)",
    )
    parser.add_argument(
        "--schedule",
        default=None,
        help=f"Cron expression for the scheduled trigger (default: {DEFAULT_SCHEDULE!r})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=f"Max pages passed to `linksanity crawl --max-pages` (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--linksanity-version",
        dest="linksanity_version",
        default=None,
        help=(
            "linksanity version the workflow pins and installs "
            f"(default: {DEFAULT_LINKSANITY_VERSION!r})"
        ),
    )
    parser.add_argument(
        "--check-anchors",
        dest="check_anchors",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "Include --check-anchors in the crawl step (default: true; "
            f"requires linksanity >= {CHECK_ANCHORS_MIN_VERSION})"
        ),
    )
    parser.add_argument(
        "--block-analytics",
        dest="block_analytics",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="Include --block-analytics in the crawl step (default: true)",
    )
    parser.add_argument(
        "--workflow-name",
        default=None,
        help=f"Workflow filename, without directory (default: {DEFAULT_WORKFLOW_NAME!r})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the workflow file if it already exists at the target path",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip all interactive prompting; use CLI values or defaults (requires --url)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="After writing the file, `git add` and `git commit` it inside --repo (never pushes)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.yes:
        if not args.url:
            print("error: --url is required when --yes is passed", file=sys.stderr)
            return 2
        url = args.url
        schedule = args.schedule if args.schedule is not None else DEFAULT_SCHEDULE
        max_pages = args.max_pages if args.max_pages is not None else DEFAULT_MAX_PAGES
        check_anchors = args.check_anchors if args.check_anchors is not None else True
        block_analytics = args.block_analytics if args.block_analytics is not None else True
        workflow_name = args.workflow_name if args.workflow_name is not None else DEFAULT_WORKFLOW_NAME
    else:
        url = args.url if args.url is not None else ask("Site URL to crawl", "")
        if not url:
            print("error: --url is required", file=sys.stderr)
            return 2

        schedule = args.schedule if args.schedule is not None else ask("Cron schedule", DEFAULT_SCHEDULE)

        if args.max_pages is not None:
            max_pages = args.max_pages
        else:
            max_pages_str = ask("Max pages", str(DEFAULT_MAX_PAGES))
            try:
                max_pages = int(max_pages_str)
            except ValueError:
                print(f"error: max pages must be an integer, got {max_pages_str!r}", file=sys.stderr)
                return 2

        if args.check_anchors is not None:
            check_anchors = args.check_anchors
        else:
            check_anchors = ask("Check anchors? (yes/no)", "yes").strip().lower() in _TRUTHY

        if args.block_analytics is not None:
            block_analytics = args.block_analytics
        else:
            block_analytics = ask("Block analytics? (yes/no)", "yes").strip().lower() in _TRUTHY

        workflow_name = (
            args.workflow_name
            if args.workflow_name is not None
            else ask("Workflow filename", DEFAULT_WORKFLOW_NAME)
        )

    version = (
        args.linksanity_version
        if args.linksanity_version is not None
        else DEFAULT_LINKSANITY_VERSION
    )

    # Fail here rather than shipping a workflow that dies on its first run with
    # a bare "No such option: --check-anchors" from inside a scheduled job.
    if check_anchors and _version_tuple(version) < _version_tuple(CHECK_ANCHORS_MIN_VERSION):
        print(
            f"error: `crawl --check-anchors` requires linksanity >= "
            f"{CHECK_ANCHORS_MIN_VERSION}, but the workflow pins {version}.\n"
            f"  Fix: re-run with --no-check-anchors, or with "
            f"--linksanity-version {CHECK_ANCHORS_MIN_VERSION} once that release "
            f"is published to PyPI.",
            file=sys.stderr,
        )
        return 2

    repo_path = Path(args.repo)
    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    target_path = workflow_dir / workflow_name

    if target_path.exists() and not args.force:
        print(
            f"error: {target_path} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 1

    yaml_text = render_workflow(
        url=url,
        schedule=schedule,
        max_pages=max_pages,
        check_anchors=check_anchors,
        block_analytics=block_analytics,
        version=version,
    )
    target_path.write_text(yaml_text, encoding="utf-8")
    print(f"wrote workflow to {target_path}")

    if args.commit:
        _git_commit(repo_path, target_path)
    else:
        rel_path = target_path.relative_to(repo_path) if target_path.is_relative_to(repo_path) else target_path
        print("Next steps:")
        print(f"  cd {repo_path}")
        print(f"  git add {rel_path}")
        print('  git commit -m "Add link-check workflow"')
        print("  git push")

    return 0


if __name__ == "__main__":
    sys.exit(main())
