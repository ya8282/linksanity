---
title: CLI Reference
sidebar_position: 3
---

## Which flag works with which subcommand

The four subcommands share most flags but not all of them. Passing a flag to a
subcommand that doesn't define it exits `2` with `No such option`. `init` has
its own flag set (see [Setup: `linksanity init`](/guides/getting-started))
and isn't part of the shared `scan`/`fix`/`crawl` matrix below.

| Flag | `scan` | `fix` | `crawl` |
|---|:--:|:--:|:--:|
| `--config` | ✅ | ✅ | ✅ |
| `--workers` | ✅ | ✅ | ✅ |
| `--timeout` | ✅ | ✅ | ✅ |
| `--retry` | ✅ | ✅ | ✅ |
| `--format` | ✅ | ✅ | ✅ |
| `--output` | ✅ | ✅ | ✅ |
| `--ignore-domains` | ✅ | ✅ | ✅ |
| `--skip-urls` | ✅ | ✅ | ✅ |
| `--check-anchors` | ✅ | ✅ | ✅ |
| `--check-images` | ✅ | ✅ | — |
| `--link-style` | ✅ | ✅ | — |
| `--cache`, `--cache-ttl` | ✅ | ✅ | — |
| `--report` | ✅ | — | ✅ |
| `--github-issue`, `--repo` | ✅ | — | ✅ |
| `--annotations` | ✅ | — | ✅ |
| `--max-redirects` | ✅ | — | ✅ |
| `--js-domains` | ✅ | — | — |
| `--offline` | ✅ | — | — |
| `--myst` | ✅ | — | — |
| `--baseline`, `--incremental`, `--since` | ✅ | — | — |
| `--write`, `--force`, `--redirects`, `--wayback` | — | ✅ | — |
| `--max-pages` | — | — | ✅ |
| `--playwright-workers` | — | — | ✅ |
| `--block-analytics` | — | — | ✅ |

A `linksanity.toml` is shared by all three subcommands. Most `Config` fields
are parsed from TOML regardless of which subcommand runs, but a subcommand
only *acts on* the ones with a matching flag — `check_images` is parsed even
under `crawl`, for example, but `crawl` has no `--check-images` flag and never
reads the field, so setting it silently has no effect on a crawl.

Four fields are different: `output`, `report`, `github_issue`, and
`github_repo` are never read from `linksanity.toml` at all — `load_config`
doesn't parse them from the file, so they can only be set via CLI flag,
regardless of subcommand. Because they're never consumed, linksanity also
reports them on stderr as unrecognised config keys; that warning is expected
for these four and not a sign anything is wrong. See
[Configuration](/guides/configuration) for the full detail on both of these
traps.

## `linksanity scan <paths...>`

| Flag | Default | Description |
|---|---|---|
| `--workers N` | 5 | Max concurrent HTTP checks |
| `--timeout N` | 10 | Per-request timeout (seconds) |
| `--retry N` | 2 | Retries on 429/503 |
| `--check-anchors` | off | Validate `#fragment` links |
| `--check-images` | off | Also validate `<img src>` / `![]()` image targets, not just links |
| `--myst` | off | Also extract MyST `{doc}`/`{ref}` role targets from `.md` files |
| `--link-style` | — | Relative-link resolution preset for built docs sites: `mkdocs`, `docusaurus`, `sphinx` |
| `--ignore-domains FILE` | — | One domain per line to skip |
| `--js-domains FILE` | — | Domains to check via Playwright |
| `--skip-urls FILE` | — | URLs/patterns to skip (one per line, `*` wildcards ok) |
| `--format` | console | `console`, `json`, or `csv` |
| `--output FILE` | stdout | Write results to file |
| `--report FILE` | — | Write Markdown summary to file |
| `--github-issue` | off | Open/update a GitHub Issue |
| `--repo OWNER/REPO` | — | Required with `--github-issue` |
| `--config FILE` | auto | Path to `linksanity.toml` |
| `--max-redirects N` | 10 | Max redirect hops before flagging as too-many-redirects |
| `--cache FILE` | — | Path to a local cache file; re-runs skip unchanged links within `--cache-ttl` |
| `--cache-ttl N` | 86400 | Seconds a cached link result stays valid |
| `--incremental` | off | Only scan files changed since the last run (git diff-aware) |
| `--since REF` | last recorded run | Git ref to diff against for `--incremental` |
| `--baseline FILE` | — | Previous JSON report to diff against; only new breakage is reported |
| `--annotations` / `--no-annotations` | auto-detect | Emit GitHub Actions `::error`/`::warning` annotations (auto-enabled in Actions unless writing JSON/CSV to bare stdout) |
| `--offline` | off | Skip external HTTP checks, reporting them as `skipped`; doesn't touch the cache |

## `linksanity fix <paths...>`

Takes local paths only — `fix` rewrites the file a link lives in, which a crawled URL doesn't have. Passing a URL exits `2`.

Reuses the `scan` flags that affect what gets checked (`--config`, `--workers`, `--timeout`, `--retry`, `--check-anchors`, `--check-images`, `--link-style`, `--ignore-domains`, `--skip-urls`, `--cache`, `--cache-ttl`), plus:

| Flag | Default | Description |
|---|---|---|
| `--write` | off | Apply auto-applicable fixes. Without it, `fix` only prints a diff |
| `--force` | off | Write even when the files to fix have uncommitted changes |
| `--redirects` | permanent | `permanent` (301/308 only) or `all` (also apply 302/307) |
| `--wayback` | off | Also suggest archive.org snapshots for dead external links |
| `--format` | console | `console` (diff) or `json` (proposals) |
| `--output FILE` | stdout | Write proposals to a file |

## `linksanity crawl <url>`

Same flags as `scan`, minus `--js-domains`, `--offline`, `--myst`, `--check-images`,
`--link-style`, `--cache`/`--cache-ttl`, and the `--baseline`/`--incremental`/`--since`
group, plus:

| Flag | Default | Description |
|---|---|---|
| `--max-pages N` | 500 | Stop after N pages crawled |
| `--playwright-workers N` | 2 | Max concurrent browser sessions |
| `--skip-urls FILE` | — | URLs/patterns to skip (one per line, `*` wildcards ok) |
| `--block-analytics` | off | Block analytics/tracking domains in the browser |
| `--check-anchors` | off | Validate `#fragment` links against the crawled target page's element ids |

## `linksanity init`

Does not share flags with `scan`/`fix`/`crawl`. See
[Setup: `linksanity init`](/guides/getting-started) for the full
walkthrough.

| Flag | Default | Description |
|---|---|---|
| `--yes` | off | Run non-interactively; requires `--paths` |
| `--paths <dir>` | — | Paths to scan for the workflow's `paths:` input; skips detection. Repeat per path. Literal paths, not globs |
| `--no-baseline` | off | Skip baseline generation even if breakage is found |
| `--no-measure` | off | Skip the timed scan entirely: no estimate, no baseline offer |
| `--workflow-name <name>` | `linkcheck.yml` | Filename for the generated workflow: a bare name, no path separators |
| `--dry-run` | off | Print the generated files; write nothing |
