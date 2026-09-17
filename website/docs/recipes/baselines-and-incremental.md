---
title: Baselines and Incremental
sidebar_position: 5
---

Three flags change *what* a scan reports without changing what it fetches: `--baseline` filters out already-known breakage, and `--incremental`/`--since` narrow which files get scanned in the first place. A fourth, `--cache`/`--cache-ttl`, is a performance cache for individual URL checks — a different mechanism entirely, covered at the end.

**All four are scan-only.** None of `--baseline`, `--incremental`, `--since`, `--cache`, or `--cache-ttl` exist on `crawl`, and only `--cache`/`--cache-ttl` carry over to `fix`. Passing any of the first three to `fix` or `crawl` exits `2` with `No such option`.

## `--baseline`

```bash
# CI goes green against today's known-broken links; only new breakage fails
linksanity scan ./docs/ --baseline .linksanity-baseline.json
```

A baseline is just a previous scan's JSON results file — the same file `--format json --output` produces. With `--baseline` set, `scan` still checks every link, but before reporting drops any result that already appeared in the baseline with a "notable" status (`broken`, `error`, `redirect`, or `too_many_redirects`). `ok` and `skipped` links are never baselined, since they aren't failures to suppress.

**Identity key: `(source_file, url)`, not line number.** A baselined failure is matched by the exact pair of source file path and URL, deliberately excluding the line number — moving the link to a different line in the *same* file still matches, so an unrelated edit that shifts line numbers doesn't make an already-known-broken link look new. Two consequences worth knowing before you rely on this:

- **The same bad URL in a second file is a new failure.** Baselining `docs/a.md`'s broken link to `https://old.example.com` does *not* cover the identical URL if it also appears in `docs/b.md` — different `source_file`, different key, so `docs/b.md`'s copy fails CI even though the URL was already known-broken elsewhere.
- **A status that degrades at the same location re-fails.** The baseline entry also records the status the link had when it was baselined, and suppression only holds while the current status is no worse than that. `redirect` is ranked below `broken`/`error`/`too_many_redirects` (the latter three are equally severe: all three are CI-failing statuses, and there's no basis in this tool for treating an exhausted-redirect-limit link as less broken than an HTTP 404). So a link baselined as `redirect` that later starts 404ing is a **strictly worse** transition and fails CI again, even though it's still the same `(source_file, url)` key. A link baselined as `broken` that later becomes a `redirect` (or stays `broken`, or stays `redirect`) is same-tier-or-better and stays suppressed — `--baseline` doesn't go red just because a repo baselined a pile of redirects. `--baseline` tells you about *new locations* of notable breakage and about *worsening* of breakage already at a known location; it does not tell you about a known-broken link improving or staying exactly as bad.

  A baseline file written before this behaviour existed has no per-entry status. Reading one of those doesn't crash and doesn't turn a whole repo's CI red: an entry with no recorded status suppresses unconditionally at its key until you regenerate the baseline. Every baseline linksanity has ever written records a status, so this is a safety net rather than a path you are likely to be on.

**Where it lives.** There's no fixed path — pass whatever file you like to `--baseline`. `linksanity init` writes one to `.linksanity-baseline.json` at the repo root by default when its measuring scan finds pre-existing breakage, and wires it into the generated workflow's `baseline:` input.

**Regenerating a stale baseline.** Re-run `init` interactively (or re-run a plain `scan --format json --output <file>` with no `--baseline` set) to produce a fresh, unfiltered results file, then use that as the new baseline. Do **not** point `--baseline` at a results artifact that itself came from a `--baseline`-filtered CI run: `scan` writes `--output` *after* filtering out already-known breakage, so that artifact only contains the new failures, not the full known set — using it as a new baseline would un-suppress everything that was previously baselined. Regenerate whenever you've deliberately fixed some of the baselined links and want CI to start catching regressions there too, or after a doc migration changes which links are expected to be broken.

## `--incremental` and `--since`

```bash
# Only scan files that changed since the last recorded run
linksanity scan ./docs/ --incremental --cache .linksanity-cache.json

# Or name the git ref explicitly
linksanity scan ./docs/ --incremental --since main
```

`--incremental` narrows the file list to only those that changed, using `git diff --name-only <since> HEAD` — so `--since` accepts anything `git diff` accepts as a ref (a branch name, tag, or commit SHA), and the comparison is always against the current `HEAD`.

If `--since` isn't given, linksanity falls back to the commit recorded in the `--cache` file from the previous run (`--incremental` without a `--cache` and without `--since` has no prior commit to compare against, so it prints a warning to stderr and runs a full scan instead). Every scan that uses `--cache` records the current `HEAD` into that cache file when it finishes, regardless of whether `--incremental` was set, so a plain cached run today becomes tomorrow's `--incremental` baseline commit for free. If the diff itself fails — `since` doesn't resolve, or you're outside a git repo — linksanity also falls back to a full scan with a stderr warning rather than erroring out.

## `--cache` and `--cache-ttl`

```bash
linksanity scan ./docs/ --cache .linksanity-cache.json --cache-ttl 3600
```

A local JSON file mapping URL to its last check result and timestamp. A re-run reuses a cached result for the same URL instead of re-fetching it, as long as the entry is younger than `--cache-ttl` seconds (default `86400`, one day). Only network-checked links (`external`, `external_anchor`) are cached — filesystem and anchor checks are already fast and can go stale the moment a local file changes, so they always re-run. The cache is versioned internally; an upgrade that changes how results are classified invalidates the whole file automatically rather than serving stale classifications.

Don't confuse this with `--baseline`: the cache is a performance optimization keyed on the URL alone and expires on a timer, while a baseline is a policy decision keyed on `(source_file, url)` that doesn't expire until you regenerate it.
