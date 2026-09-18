---
title: Configuration
sidebar_position: 4
---

`scan`, `fix`, and `crawl` discover `linksanity.toml` by walking upward from the current working directory toward the filesystem root, using the nearest one found. The walk stops at (and still checks) the first directory containing a `.git` entry, treating it as the project boundary — a stray `linksanity.toml` in an unrelated ancestor directory (e.g. your home directory) can't leak into the project you're scanning. Pass `--config path/to/linksanity.toml` to use a specific file instead; an explicit `--config` path that doesn't exist is an error, not a silent fallback to defaults.

Either way, linksanity prints one line to stderr saying which config file it loaded, or that it found none and is using defaults — never silently. That line is suppressed for `--format json`/`--format csv` runs with no `--output` file, since that's the agent/script pipe case where it would be noise on every invocation. It goes to stderr, so it would not corrupt a `--format json | jq` pipeline even when shown:

```toml
workers = 10
timeout = 15
retry = 3
check_anchors = false
myst = true
max_pages = 200
block_analytics = true

ignore_domains = ["status.example.com", "internal.example.com"]
js_domains = ["spa.example.com"]
skip_urls = [
  "https://app.example.com/login",
  "https://staging.example.com/*",
]
```

The keys above aren't the whole surface — `load_config` parses most other
`Config` fields with a matching TOML name too (the four exceptions are noted
below the table). The rest, with their defaults:

| Key | Default | Meaning |
|---|---|---|
| `playwright_workers` | `2` | Max concurrent browser sessions (`crawl`) |
| `check_images` | `false` | Also validate image targets, not just links |
| `link_style` | unset | Relative-link resolution preset: `mkdocs`, `docusaurus`, `sphinx` |
| `format` | `"console"` | Output format: `console`, `json`, or `csv` |
| `max_redirects` | `10` | Max redirect hops before flagging as too-many-redirects |
| `cache_file` | unset | Path to a local cache file |
| `cache_ttl` | `86400` | Seconds a cached link result stays valid |
| `incremental` | `false` | Only scan files changed since the last run |
| `since` | unset | Git ref to diff against for `incremental` |
| `baseline` | unset | Previous JSON report to diff against |
| `annotations` | unset (auto-detect) | Emit GitHub Actions annotations; `true`/`false` overrides auto-detect |
| `offline` | `false` | Skip external HTTP checks |

## CLI flag vs. `linksanity.toml` precedence

A CLI flag always wins over the same key set in `linksanity.toml` — the file
supplies defaults, the flag overrides them for that one invocation. See the
[CLI reference](./cli-reference.md) for the full per-subcommand flag list
and which flags exist on which subcommand.

## Two traps worth knowing before you rely on the file

**A field can be parsed from TOML under a subcommand that has no matching
flag — and then be silently ignored.** Most `Config` fields are parsed from
`linksanity.toml` regardless of which subcommand is running, but a
subcommand only *acts on* the ones it defines a flag for. `check_images` is
the clearest example: it's parsed even when you run `crawl`, but `crawl` has
no `--check-images` flag and never reads the field, so setting
`check_images = true` in `linksanity.toml` has no effect on a crawl — no
warning, no error, just a no-op. Check the [flag compatibility
matrix](./cli-reference.md) to know whether a field you set in the file
is actually acted on by the subcommand you're running.

**`output`, `report`, `github_issue`, and `github_repo` are never read from
`linksanity.toml` at all.** `load_config` doesn't parse these four fields
from the file — regardless of subcommand, they can only be set via CLI flag
(`--output`, `--report`, `--github-issue`, `--repo`). Putting
`output = "results.json"` in `linksanity.toml` does nothing; you must pass
`--output results.json` on the command line every time. Because these keys
are never consumed, linksanity also reports them on stderr as unrecognised
(`[linksanity] warning: unrecognised config key(s) in <path>: github_issue, github_repo, output, report`)
— that warning is expected for these four keys, not a sign anything is
wrong.
