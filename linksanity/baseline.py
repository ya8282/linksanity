"""Baseline diffing — compare a scan against a previous JSON report.

Lets CI fail only on *new* breakage instead of re-flagging known, pre-existing
broken links on every run — but a link that *degrades* at a known location
(e.g. a baselined redirect that starts 404ing) must still fail: that's the
exact failure this feature exists to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

from linksanity.queue import FAILING_STATUSES, LinkResult, LinkStatus

_NOTABLE = {
    LinkStatus.BROKEN,
    LinkStatus.ERROR,
    LinkStatus.REDIRECT,
    LinkStatus.TOO_MANY_REDIRECTS,
    LinkStatus.BLOCKED,
}
_NOTABLE_VALUES = {s.value for s in _NOTABLE}

# Severity tiers for re-failing a baselined link on a status transition.
# Only a transition to a *strictly higher* tier re-fails; same-tier and
# downgrading transitions stay suppressed.
#
#   0 — REDIRECT: notable, but the CLI does not exit non-zero on it alone.
#   0 — BLOCKED: notable but not a confirmed failure (see queue.py —
#       FAILING_STATUSES deliberately excludes it, a 401/403 means the
#       request was refused, not that the resource is gone), so it sits
#       alongside REDIRECT rather than the failing tier. A baselined-blocked
#       link stays suppressed unless it degrades into a FAILING_STATUSES
#       status — e.g. the bot-wall response turning into a real 404.
#   1 — BROKEN / ERROR / TOO_MANY_REDIRECTS: all three are in
#       FAILING_STATUSES (queue.py) — the link is unusable and CI already
#       exits on it — so they're ranked equal. There's no signal in this
#       codebase that TOO_MANY_REDIRECTS is a "lesser" failure than BROKEN;
#       it's exhausted --max-redirects and never resolved, same as the other
#       two. Reuse FAILING_STATUSES rather than re-deriving the split.
_SEVERITY: dict[LinkStatus, int] = {
    LinkStatus.REDIRECT: 0,
    LinkStatus.BLOCKED: 0,
    **{status: 1 for status in FAILING_STATUSES},
}


def _severity(status: LinkStatus) -> int:
    return _SEVERITY.get(status, 0)


def _key(source_file: str, url: str) -> tuple[str, str]:
    # Keyed on (file, url), not line — an unrelated edit shifting line numbers
    # shouldn't make an already-known-broken link look "new".
    return (source_file, url)


# Maps an identity key to the status it had in the baseline report. `None`
# means the baseline entry predates this change and carries no status (see
# load_baseline) — it suppresses unconditionally, matching the old
# status-blind behaviour, so an un-regenerated baseline file keeps working.
Baseline = dict[tuple[str, str], LinkStatus | None]


def load_baseline(path: Path) -> Baseline:
    """Return identity keys of every notable link in a prior JSON report, mapped to their status.

    A baseline entry with no "status" field (written before status-aware
    comparison existed) maps to None, which suppresses any notable status at
    that key — more lenient than any released behaviour — rather than crashing or treating
    the whole baseline as empty.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    baseline: Baseline = {}
    for r in data:
        key = _key(r["source_file"], r["url"])
        if "status" not in r or r["status"] is None:
            baseline[key] = None
            continue
        raw = r["status"]
        if raw not in _NOTABLE_VALUES:
            continue
        baseline[key] = LinkStatus(raw)
    return baseline


def only_new(results: list[LinkResult], baseline: Baseline) -> list[LinkResult]:
    """Drop notable results already known at their baseline severity or better.

    A result is suppressed when its key is in the baseline and either the
    baseline entry has no recorded status (legacy file) or its status is at
    least as severe as the baseline's. It re-fails when the current status is
    strictly more severe than what was baselined — e.g. redirect -> broken.
    """
    kept = []
    for r in results:
        if r.status not in _NOTABLE:
            kept.append(r)
            continue
        old_status = baseline.get(_key(r.source_file, r.url), ...)
        if old_status is ...:
            kept.append(r)  # not in baseline: new
        elif old_status is None:
            pass  # legacy entry: suppress unconditionally
        elif _severity(r.status) > _severity(old_status):
            kept.append(r)  # strictly worse than baselined: re-fail
        # else: same or better tier than baselined: stays suppressed
    return kept
