---
title: Output Modes
sidebar_position: 5
---

## Reporters

`--format` selects one of three result formats, and two more reporters run
independently of `--format` when their own flag is set:

| Reporter | Trigger | What it does |
|---|---|---|
| `console` | `--format console` (default) | Human-readable, one line per notable link (anything other than `ok`/`skipped`) plus a summary tally |
| `json` | `--format json` | The full result array described below — the stable machine-readable format |
| `csv` | `--format csv` | Same result data as CSV rows |
| `markdown` | `--report FILE` | Writes a Markdown summary report to `FILE`, independent of `--format` |
| `github` | `--github-issue` | Creates or updates a GitHub Issue summarising failing links |
| `github annotations` | auto-detected in GitHub Actions, or `--annotations`/`--no-annotations` | Emits `::error`/`::warning` annotations so failing links surface inline on the PR diff |

linksanity is designed to be a clean tool call for AI agents. Use `--format json` so an agent can parse structured output without screen-scraping console text.

**Exit codes** are the primary signal — but they mean different things for `scan`/`crawl` than for `fix`:

| Command | `0` | `1` | `2` | `3` |
|---|---|---|---|---|
| `scan`, `crawl` | all links OK | one or more broken links | operational error (bad arguments, invalid config, an I/O failure, or a missing dependency — Playwright for `crawl` or `--js-domains`) | `--github-issue` reporter failed |
| `fix` | nothing to fix | proposals exist (dry run), or were applied (`--write`) | operational error (bad arguments, invalid config, a missing dependency — Playwright, when `js_domains` is set — or a failed write to `--output`/a domains/skip file), or `--write` refused a dirty tree | n/a — `fix` has no `--github-issue` |

A `fix` exit of `1` is not a failure signal by itself — check `auto_applicable` in the JSON output (below) or the diff to see what happened.

## JSON output schema

```bash
linksanity scan ./docs/ --format json --output results.json
```

Each item in the output array has:

```json
[
  {
    "source_file": "docs/guide.md",
    "line": 42,
    "cell": null,
    "url": "https://example.com/old",
    "link_type": "external",
    "status": "redirect",
    "http_code": 200,
    "resolved_url": "https://example.com/new",
    "error": null,
    "redirect_chain": ["https://example.com/old", "https://example.com/new"],
    "redirect_codes": [301]
  }
]
```

| Key | Meaning |
|---|---|
| `source_file` | Path to the file the link was found in |
| `line` | Line number the link appears on |
| `url` | The link target as written in the source |
| `status` | `"ok"`, `"broken"`, `"redirect"`, `"too_many_redirects"`, `"skipped"`, or `"error"` |
| `link_type` | `"external"`, `"internal"`, `"anchor"`, `"external_anchor"`, or `"non_http_scheme"` |
| `http_code` | Final HTTP status, or `null` for links that were never fetched |
| `resolved_url` | Final URL after redirects; `null` when there was no redirect |
| `error` | Error message when `status` is `"error"`; `null` otherwise |
| `cell` | Notebook cell index for `.ipynb` sources; `null` otherwise. **`line` is relative to the cell, not the file** |
| `redirect_chain` | Every URL in the chain, original first; `null` unless an HTTP redirect response was actually received, and also `null` in the rare case where a hop's status code couldn't be determined (chain and codes are always `null` together, never one without the other, so a code is never guessed). A URL that differs only by normalization (host case, scheme case, dot-segments) with no real redirect reports `status: "ok"`, not `"redirect"` |
| `redirect_codes` | The status code of each hop, one per hop. Note the lengths differ: `redirect_chain` holds N+1 entries (every hop plus the final URL) while `redirect_codes` holds N, so do not zip them naively. All 301/308 means permanently moved and safe to rewrite. `null` whenever `redirect_chain` is `null`, for the same reasons |

`linksanity fix --format json` emits a different schema — fix proposals rather than link results. See the [CLI reference](./cli-reference.md) for the `fix` flag table, and [Fixing broken links](../recipes/fixing-broken-links.md) for the proposal fields and the repair loop.

## Exit codes

For `scan` and `crawl`:

| Code | Meaning |
|---|---|
| `0` | All links OK (or only plain redirects/skipped) |
| `1` | One or more broken links, errors, or redirect loops (`--max-redirects` exceeded) |
| `2` | Operational error: bad arguments, an invalid or unreadable config, a file that couldn't be read or written, or a missing optional dependency (e.g. Playwright for `crawl` or `--js-domains`) |
| `3` | `--github-issue` reporter itself failed (e.g. missing `GITHUB_TOKEN`, GitHub API error) -- distinct from `1` so "we could not tell you" doesn't look like "nothing to tell you" |

For `fix`:

| Code | Meaning |
|---|---|
| `0` | Nothing to fix |
| `1` | Proposals exist (dry run), or were applied (`--write`) |
| `2` | Operational error: bad arguments, an invalid config, a missing dependency (Playwright, when `js_domains` is set in the config), or a failed write to `--output` or a domains/skip file -- or `--write` refused a dirty working tree |

For `init`:

| Code | Meaning |
|---|---|
| `0` | All validation, config loading, and (unless `--no-measure`) the measuring scan passed. A real run then wrote the workflow (and baseline, if any); `--dry-run` printed them instead, without checking whether the target files already exist |
| `2` | Bad arguments, non-TTY stdin without `--yes`, no path to scan, declining the competing-checker prompt, an invalid config, or a failed measuring scan -- all of these run before the dry-run check, so they exit `2` even under `--dry-run`. On a real (non-dry) run only: an existing workflow/baseline file, or a failed write |
