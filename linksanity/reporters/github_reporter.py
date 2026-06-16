"""GitHub Issue reporter — opens one issue per run summarising broken links.

Reads GITHUB_TOKEN from the environment. Never accepts the token as a CLI arg.
Deduplicates by checking for an existing open issue with the same title prefix.
"""

from __future__ import annotations

import os
from itertools import groupby
from operator import attrgetter

import httpx

from linksanity.config import Config
from linksanity.queue import LinkResult, LinkStatus

_API = "https://api.github.com"
_TITLE_PREFIX = "[linksanity]"
_BROKEN = {LinkStatus.BROKEN, LinkStatus.ERROR}


def report(results: list[LinkResult], config: Config) -> None:
    broken = [r for r in results if r.status in _BROKEN]
    if not broken:
        return

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "Export it before running linksanity with --github-issue."
        )

    repo = config.github_repo
    if not repo:
        raise ValueError("github_repo must be set when github_issue=True")

    title = f"{_TITLE_PREFIX} {len(broken)} broken link(s) found"
    body = _build_body(broken)

    existing = _find_existing_issue(token, repo, title)
    if existing:
        _update_issue(token, repo, existing, body)
    else:
        _create_issue(token, repo, title, body)


def _build_body(broken: list[LinkResult]) -> str:
    lines = [
        "linksanity detected the following broken links.\n",
        "| File | Line | URL | Detail |",
        "|---|---|---|---|",
    ]
    by_file = sorted(broken, key=attrgetter("source_file", "line"))
    for _sf, group_iter in groupby(by_file, key=attrgetter("source_file")):
        for r in group_iter:
            detail = f"`[{r.http_code}]`" if r.http_code else (r.error or "")
            lines.append(f"| `{r.source_file}` | {r.line} | `{r.url}` | {detail} |")
    lines.append("\n_Opened by [linksanity](https://github.com/linksanity/linksanity)._")
    return "\n".join(lines)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_existing_issue(token: str, repo: str, title: str) -> int | None:
    """Return the issue number of an existing open linksanity issue, or None."""
    resp = httpx.get(
        f"{_API}/repos/{repo}/issues",
        params={"state": "open", "labels": "", "per_page": 100},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    for issue in resp.json():
        if isinstance(issue.get("title"), str) and issue["title"].startswith(_TITLE_PREFIX):
            return int(issue["number"])
    return None


def _create_issue(token: str, repo: str, title: str, body: str) -> None:
    resp = httpx.post(
        f"{_API}/repos/{repo}/issues",
        json={"title": title, "body": body},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()


def _update_issue(token: str, repo: str, number: int, body: str) -> None:
    resp = httpx.patch(
        f"{_API}/repos/{repo}/issues/{number}",
        json={"body": body},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
