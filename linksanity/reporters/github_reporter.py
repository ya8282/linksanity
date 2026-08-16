"""GitHub Issue reporter — opens one issue per run summarising failing links.

Reads GITHUB_TOKEN from the environment. Never accepts the token as a CLI arg.
Deduplicates by listing open issues sorted by most-recently-updated first
(the reporter PATCHes the linksanity issue on every run, so it is bumped to
the front of that ordering) and checking for an existing one with the same
title prefix. Pagination follows the `Link: rel="next"` header, up to a
bounded page cap, as a correctness backstop for the first run against a repo
where the issue exists but has gone untouched for a long time.
"""

from __future__ import annotations

import os
import re
import sys
from itertools import groupby
from operator import attrgetter

import httpx

from linksanity._meta import HOMEPAGE_URL
from linksanity.config import Config
from linksanity.queue import FAILING_STATUSES, LinkResult
from linksanity.reporters._markdown_escape import escape_plain, wrap_code_span

_API = "https://api.github.com"
_TITLE_PREFIX = "[linksanity]"
_REPO_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")
# Runaway guard: at 100 issues/page this covers 1000 open issues before we
# give up and warn. A repo with more open issues than that is pathological
# enough to warrant a human looking at it rather than the reporter looping
# forever.
_MAX_PAGES = 10


def report(results: list[LinkResult], config: Config) -> None:
    failing = [r for r in results if r.status in FAILING_STATUSES]
    if not failing:
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
    if not _REPO_RE.match(repo):
        raise ValueError(f"github_repo must be in OWNER/REPO format, got: {repo!r}")

    title = f"{_TITLE_PREFIX} {len(failing)} failing link(s) found"
    body = _build_body(failing)

    existing = _find_existing_issue(token, repo, title)
    if existing:
        _update_issue(token, repo, existing, title, body)
    else:
        _create_issue(token, repo, title, body)


def _build_body(failing: list[LinkResult]) -> str:
    lines = [
        "linksanity detected the following failing links.\n",
        "| File | Line | URL | Detail |",
        "|---|---|---|---|",
    ]
    by_file = sorted(failing, key=attrgetter("source_file", "line"))
    for _sf, group_iter in groupby(by_file, key=attrgetter("source_file")):
        for r in group_iter:
            detail = f"`[{r.http_code}]`" if r.http_code else escape_plain(r.error or "")
            line_col = f"cell {r.cell}, line {r.line}" if r.cell is not None else f"{r.line}"
            lines.append(
                f"| {wrap_code_span(r.source_file)} | {line_col} | "
                f"{wrap_code_span(r.url)} | {detail} |"
            )
    lines.append(f"\n_Opened by [linksanity]({HOMEPAGE_URL})._")
    return "\n".join(lines)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_existing_issue(token: str, repo: str, title: str) -> int | None:
    """Return the issue number of an existing open linksanity issue, or None.

    Paginates through `GET /repos/{repo}/issues` following the `Link:
    rel="next"` response header, stopping as soon as a match is found. The
    `issues` endpoint also returns pull requests, which are skipped via the
    `pull_request` key present only on PR entries.

    The walk gives up after `_MAX_PAGES` pages (1000 open issues), warning
    on stderr and returning None, which causes `report()` to create a new
    issue instead of updating the existing one. Sorting by
    `updated`/`desc` is what keeps this adequate in practice, since the
    linksanity issue is pinned near page 1 by the PATCH on every run.
    """
    url: str = f"{_API}/repos/{repo}/issues"
    params: dict[str, str | int] | None = {
        "state": "open",
        "labels": "",
        "per_page": 100,
        # Sort by most-recently-updated: the reporter PATCHes the linksanity
        # issue on every run, so this keeps it pinned to page 1 in practice
        # and is what makes _MAX_PAGES an adequate cap rather than a source
        # of duplicate issues on busy repos. Direction is set explicitly
        # rather than relying on the endpoint's default.
        "sort": "updated",
        "direction": "desc",
    }
    for _page in range(_MAX_PAGES):
        resp = httpx.get(url, params=params, headers=_headers(token), timeout=15)
        resp.raise_for_status()
        for issue in resp.json():
            if "pull_request" in issue:
                continue
            if isinstance(issue.get("title"), str) and issue["title"].startswith(_TITLE_PREFIX):
                return int(issue["number"])
        next_link = resp.links.get("next")
        if not next_link or not next_link.get("url"):
            return None
        url = next_link["url"]
        params = None  # the `next` URL already carries all query params
    print(
        f"linksanity: gave up searching for an existing issue after {_MAX_PAGES} pages "
        "of open issues; a duplicate issue may be created.",
        file=sys.stderr,
    )
    return None


def _create_issue(token: str, repo: str, title: str, body: str) -> None:
    resp = httpx.post(
        f"{_API}/repos/{repo}/issues",
        json={"title": title, "body": body},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()


def _update_issue(token: str, repo: str, number: int, title: str, body: str) -> None:
    resp = httpx.patch(
        f"{_API}/repos/{repo}/issues/{number}",
        json={"title": title, "body": body},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
