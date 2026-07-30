#!/usr/bin/env python3
"""Run a linksanity case study against a docs site and render a Markdown report.

Usage:
    python scripts/case_study.py <target> <docs-subpath> <slug> [--out-dir case-studies]

<target> is either a git URL (shallow-cloned into a temp dir) or an existing
local directory. <docs-subpath> is the path to the docs tree relative to the
target's root ("." if the target root itself is the docs tree).

Runs `linksanity scan` (JSON output) and `linksanity fix --dry-run` against
the resolved docs directory, then writes <out-dir>/<slug>.md summarizing the
results.

stdlib only; no third-party dependencies.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

STATUS_ORDER = ["ok", "broken", "redirect", "too_many_redirects", "skipped", "error"]


def _is_git_url(target: str) -> bool:
    if target.startswith(("http://", "https://", "ssh://", "git://", "git@")):
        return True
    return target.endswith(".git")


def _clone(target: str, dest: Path) -> None:
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", target, str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed for {target!r}:\n{proc.stderr}")


def _commit_sha(repo_dir: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed:\n{proc.stderr}")
    return proc.stdout.strip()


def _run_scan(docs_dir: Path, json_out: Path) -> tuple[float, list[dict]]:
    cmd = [
        sys.executable, "-m", "linksanity", "scan", str(docs_dir),
        "--format", "json", "--output", str(json_out),
    ]
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - start
    # Exit code 1 means "broken links found" -- success for this script.
    # Only other non-zero codes, or a missing JSON file, are real failures.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"linksanity scan failed (exit {proc.returncode}):\n{proc.stderr}")
    if not json_out.exists():
        raise RuntimeError(f"linksanity scan produced no JSON output:\n{proc.stderr}")
    data = json.loads(json_out.read_text(encoding="utf-8"))
    return elapsed, data


def _run_fix_dry_run(docs_dir: Path) -> int | None:
    """Count auto-applicable fixes `linksanity fix --dry-run` would apply.

    Returns None if the dry run itself fails or its output can't be parsed
    as JSON -- that is surfaced honestly in the rendered report rather than
    guessed at as zero.
    """
    cmd = [sys.executable, "-m", "linksanity", "fix", str(docs_dir), "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return None
    stdout = proc.stdout.strip()
    if stdout.startswith("[linksanity] nothing to fix"):
        return 0
    if not stdout:
        return None
    try:
        proposals = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return sum(1 for p in proposals if p.get("auto_applicable"))


def _stats(results: list[dict]) -> dict[str, int]:
    files = {r["source_file"] for r in results}
    counts = dict.fromkeys(STATUS_ORDER, 0)
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "files_scanned": len(files),
        "links_checked": len(results),
        "ok": counts["ok"],
        "broken": counts["broken"] + counts["error"] + counts["too_many_redirects"],
        "redirect": counts["redirect"],
        "skipped": counts["skipped"],
    }


def _render(
    *,
    slug: str,
    target: str,
    commit: str,
    date: str,
    stats: dict[str, int],
    results: list[dict],
    auto_fixable: int | None,
    runtime_s: float,
    scan_cmd: str,
    fix_cmd: str,
) -> str:
    is_clean = stats["broken"] == 0 and stats["redirect"] == 0

    lines = [f"# Case Study: {slug}", ""]
    lines.append(f"- **Target:** {target}")
    lines.append(f"- **Commit:** {commit}")
    lines.append(f"- **Date:** {date}")
    lines.append("")

    if is_clean:
        lines.append("**Clean site.** No broken or redirected links found.")
        lines.append("")

    lines.append("## Stats")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("| --- | --- |")
    lines.append(f"| Files scanned | {stats['files_scanned']} |")
    lines.append(f"| Links checked | {stats['links_checked']} |")
    lines.append(f"| OK | {stats['ok']} |")
    lines.append(f"| Broken | {stats['broken']} |")
    lines.append(f"| Redirect | {stats['redirect']} |")
    lines.append(f"| Skipped | {stats['skipped']} |")
    lines.append("")

    lines.append("## Sample findings")
    lines.append("")
    non_ok = [r for r in results if r["status"] != "ok"][:10]
    if not non_ok:
        lines.append("No issues found.")
    else:
        lines.append("| Location | URL | Status |")
        lines.append("| --- | --- | --- |")
        for r in non_ok:
            lines.append(f"| {r['source_file']}:{r['line']} | {r['url']} | {r['status']} |")
    lines.append("")

    lines.append("## Auto-fixable")
    lines.append("")
    if auto_fixable is None:
        lines.append(
            "Could not determine how many links are auto-fixable "
            "(`linksanity fix` dry run failed)."
        )
    else:
        lines.append(f"{auto_fixable} link(s) could be auto-fixed by `linksanity fix --write`.")
    lines.append("")

    lines.append("## Runtime")
    lines.append("")
    lines.append(f"Scan completed in {runtime_s:.2f}s.")
    lines.append("")

    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(scan_cmd)
    lines.append(fix_cmd)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", help="Git URL to shallow-clone, or an existing local directory")
    parser.add_argument("docs_subpath", help="Docs path relative to the target root ('.' for the root itself)")
    parser.add_argument("slug", help="Short slug used for the output filename")
    parser.add_argument("--out-dir", default="case-studies", help="Directory to write <slug>.md into")
    args = parser.parse_args(argv)

    with contextlib.ExitStack() as stack:
        if Path(args.target).is_dir():
            repo_root = Path(args.target).resolve()
            commit = "local"
        elif _is_git_url(args.target):
            tmp = stack.enter_context(tempfile.TemporaryDirectory())
            repo_root = Path(tmp) / "repo"
            try:
                _clone(args.target, repo_root)
                commit = _commit_sha(repo_root)
            except RuntimeError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        else:
            print(
                f"error: target is neither an existing local directory nor a "
                f"recognizable git URL: {args.target}",
                file=sys.stderr,
            )
            return 2

        docs_dir = repo_root / args.docs_subpath
        if not docs_dir.exists():
            print(
                f"error: docs subpath {args.docs_subpath!r} not found under target {args.target!r}",
                file=sys.stderr,
            )
            return 2

        work_tmp = stack.enter_context(tempfile.TemporaryDirectory())
        json_out = Path(work_tmp) / f"{args.slug}.json"

        try:
            runtime_s, results = _run_scan(docs_dir, json_out)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        auto_fixable = _run_fix_dry_run(docs_dir)
        stats = _stats(results)

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.slug}.md"

        scan_cmd = f"python -m linksanity scan {docs_dir} --format json --output {args.slug}.json"
        fix_cmd = f"python -m linksanity fix {docs_dir} --format json"

        markdown = _render(
            slug=args.slug,
            target=args.target,
            commit=commit,
            date=datetime.now(UTC).date().isoformat(),
            stats=stats,
            results=results,
            auto_fixable=auto_fixable,
            runtime_s=runtime_s,
            scan_cmd=scan_cmd,
            fix_cmd=fix_cmd,
        )
        out_path.write_text(markdown, encoding="utf-8")
        print(f"case study written to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
