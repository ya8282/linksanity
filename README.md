# linksanity 🏀

[![PyPI](https://img.shields.io/pypi/v/linksanity.svg)](https://pypi.org/project/linksanity/)

Detect broken links and redirects in Markdown, reStructuredText, and HTML content.

Don't let dead URLs leave you hanging on the rim! Catch broken docs links in the Knick of time with Linksanity.
This tool keeps your documentation or web content game flawless, ensuring you never drop the ball on your readers.

```
$ linksanity scan ./docs/
docs/api/guide.md
  BROKEN    line   12  ./missing.md — file not found
  REDIRECT  line   45  https://old.example.com → https://new.example.com

ok=38   broken=1   redirect=1   skipped=0
```

## Features

- **Static scan** — parse 8 file formats (see Supported formats below) without a browser
- **Live crawl** — follow links on a deployed site using a headless browser (Playwright)
- **Fix, don't just report** — `linksanity fix` rewrites permanently-redirected URLs and moved-file links in place (see [Fixing broken links](#fixing-broken-links))
- **Exit codes** — `0` = clean, `1` = broken links found (ideal for CI)
- **Multiple formats** — console (Rich), JSON, CSV; optional Markdown summary report
- **Anchor validation** — opt-in `--check-anchors` flag
- **GitHub Issues** — create or update an issue summarising broken links
- **Ignore domains** — skip domains you don't control
- **JS-rendered pages** — route specific domains through Playwright in scan mode
- **Retry logic** — exponential back-off on 429/503; HEAD→GET fallback on 405

## Adopt what you need

linksanity is modular — install only what you need for your use case.

| Use case | Install | Minimal example | Details |
|---|---|---|---|
| **Scanner only** | `pip install linksanity` | `linksanity scan ./docs/` | [Quick start](#quick-start) |
| **Fixer** | already included | `linksanity fix ./docs/` (dry run; add `--write` to apply) | [Fixing broken links](#fixing-broken-links) |
| **Browser crawl** | `pip install "linksanity[browser]"` then `playwright install chromium` | `linksanity crawl https://docs.example.com` | [Crawl a live site](#crawl-a-live-site) |
| **Pre-commit hook** | already included; add to `.pre-commit-config.yaml` | `repo: https://github.com/ya8282/linksanity`, `rev: v0.2.0`, `hooks: [{id: linksanity}]` | [Pre-commit hook](#pre-commit-hook) |
| **GitHub Action** | none — no local install needed | `- uses: ya8282/linksanity-action@v1` with `paths: docs/` | [CI integration](#ci-integration) — see the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) repo |
| **Library API** | `pip install linksanity` | `from linksanity import scan_paths` | [Use as a library](#use-as-a-library) (note: no `./linksanity.toml` auto-discovery, unlike the CLI) |

## Supported formats

linksanity checks links in 8 file formats:

- **Markdown** — `.md` files
- **reStructuredText** — `.rst` files
- **HTML** — `.html`, `.htm` files
- **AsciiDoc** — `.adoc`, `.asciidoc` files
- **MDX** — `.mdx` files (CommonMark + JSX)
- **Jupyter Notebooks** — `.ipynb` files (extracts markdown cells)
- **MyST-flavored Markdown** — `.md` files with opt-in `--myst` flag or `myst = true` in config (enables MyST role extraction: `{doc}`, `{ref}`)
- **DocBook** — `.xml`, `.dbk` files (extracts link and xref elements)

## Install

```bash
pip install linksanity
```

For JS-rendered pages (Playwright headless browser):

```bash
pip install "linksanity[browser]"
playwright install chromium
```

Requires Python 3.11+.

**From source:**

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
pip install -e ".[dev,browser]"
playwright install chromium
```

## Quick start

### Scan local source files

```bash
# Scan a directory (finds all .md / .rst / .html files recursively)
linksanity scan ./docs/

# Scan specific files or globs
linksanity scan README.md docs/**/*.md

# Validate anchor fragments too
linksanity scan ./docs/ --check-anchors

# Write JSON output; exit 1 if broken links found
linksanity scan ./docs/ --format json --output results.json

# Create a Markdown summary report
linksanity scan ./docs/ --report report.md

# Skip domains you don't control
echo "internal.corp.example.com" > ignore.txt
linksanity scan ./docs/ --ignore-domains ignore.txt
```

### Crawl a live site

```bash
# Crawl up to 500 pages (default)
linksanity crawl https://docs.example.com

# Limit crawl depth
linksanity crawl https://docs.example.com --max-pages 50

# Ignore external domains
linksanity crawl https://docs.example.com --ignore-domains ignore.txt
```

### CI integration

The fastest way to add link checking to CI is the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) composite action — one line beyond checkout:

```yaml
# .github/workflows/linkcheck.yml
name: Link check
on: [pull_request]
jobs:
  linkcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ya8282/linksanity-action@v1
        with:
          paths: docs/
```

Prefer to install the CLI directly instead of using the action — for example on self-hosted runners without Marketplace access, or when you want full control over the install step? See the hand-rolled workflow below.

<details>
<summary>Hand-rolled workflow (no composite action)</summary>

Add a link-check job that runs on every pull request and on a weekly schedule.

```yaml
# .github/workflows/linkcheck.yml
name: Link check

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 8 * * 1"   # every Monday at 08:00 UTC

permissions:
  contents: read

jobs:
  linkcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install linksanity
        run: pip install linksanity

      - name: Check links
        run: |
          linksanity scan ./docs/ \
            --skip-urls .linksanity-skip \
            --format json \
            --output linkcheck.json

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: linkcheck-results
          path: linkcheck.json
```

**File-based skip list** — commit a `.linksanity-skip` file at your repo root to exclude auth-gated or staging URLs. Supports `*` wildcards:

```
# .linksanity-skip
https://app.example.com/login
https://staging.example.com/*
https://internal.corp.example.com/*
```

**Report broken links to a GitHub Issue** — useful for scheduled runs that find regressions after merge:

```yaml
      - name: Report broken links
        if: failure()
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          linksanity scan ./docs/ \
            --github-issue \
            --repo ${{ github.repository }}
```

`GITHUB_TOKEN` is always read from the environment — never pass it as a CLI flag or store it in a file.

**Crawl a live docs site** — swap `scan` for `crawl` to test a deployed site:

```yaml
      - name: Crawl live docs
        run: |
          pip install "linksanity[browser]"
          playwright install --with-deps chromium
          linksanity crawl https://docs.example.com \
            --max-pages 200 \
            --block-analytics \
            --format json \
            --output crawl-results.json
```

**Generate this workflow automatically** — `scripts/bootstrap_linkcheck.py` writes a full `.github/workflows/linkcheck.yml` (the crawl variant above) into any target repo, prompting for anything not passed as a flag:

```bash
# Fully interactive — prompts for URL, schedule, max-pages, etc.
python scripts/bootstrap_linkcheck.py --repo ../some-site

# Non-interactive, all options via flags
python scripts/bootstrap_linkcheck.py --repo ../some-site --yes \
  --url https://example.com \
  --schedule "0 8 * * 1" \
  --max-pages 200
```

`--force` overwrites an existing workflow file of the same name; `--commit` stages and commits the generated file locally (never pushes). Run `python scripts/bootstrap_linkcheck.py --help` for the full option list.

</details>

### Pre-commit hook

Run linksanity locally before each commit using [pre-commit](https://pre-commit.com/). The hook defaults to `--offline` (skips live HTTP checks, reporting them as `SKIPPED`) so it stays fast and doesn't fail on a flaky network:

```yaml
# .pre-commit-config.yaml (in the consuming repo)
repos:
  - repo: https://github.com/ya8282/linksanity
    rev: v0.2.0
    hooks:
      - id: linksanity
```

To run full (online) checks instead, pass `--no-offline` via `args:`. pre-commit appends a hook's `args:` after its `entry`, so the later flag wins over the `--offline` baked into the hook's entry:

```yaml
      - id: linksanity
        args: [--no-offline]
```

### GitHub Issue reporting

Use `--github-issue` when you want broken links surfaced as a trackable GitHub Issue rather than just a failed CI run. It creates or updates a single `[linksanity]` issue listing every broken URL, so the team has a persistent record to triage — not just a red check mark that disappears on the next push.

**When to use it:**

- **Scheduled runs** — a weekly cron job catches link rot that crept in after your last merge. The issue stays open until you fix the links and the check goes green.
- **Repos without branch protection** — if broken links won't block a PR merge, an issue is the only signal that survives past the CI run.
- **Large docs sites** — when dozens of links break at once (e.g. a domain migration), a single issue is easier to triage than scrolling through CI logs.

**When you don't need it:**

- PRs where branch protection already blocks the merge on failure — a failed job is sufficient.
- Local runs and one-off checks.

**Setup:**

```bash
export GITHUB_TOKEN=ghp_...
linksanity scan ./docs/ --github-issue --repo owner/repo
```

`GITHUB_TOKEN` is read from the environment only — never pass it as a CLI flag or store it in a file. In GitHub Actions, use the built-in token:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The workflow job also needs `issues: write` permission:

```yaml
permissions:
  contents: read
  issues: write
```

## Fixing broken links

Most checkers stop at a red ✗. `linksanity fix` takes the next step: it scans, works out which breakages it can repair, and shows you a diff.

```bash
# Dry run — prints a unified diff, changes nothing
linksanity fix ./docs/

# Apply the fixes it is confident about
linksanity fix ./docs/ --write
```

**Dry run is the default. Files are only ever touched under `--write`.**

### What it will and won't fix

| Class | Trigger | Confidence | Applied by `--write`? |
|---|---|---|---|
| `redirect` | Every hop in the chain is a 301 or 308 | High — the server itself declares the new canonical URL | **Yes** |
| `moved_file` | A broken relative link whose basename matches exactly one file in the corpus | Medium — inferred from the file tree | **Yes**, unique match only |
| `wayback` | A dead external link (404/410) with an Internet Archive snapshot | Low — a judgment call | **Never** — suggested only |

Anything ambiguous is reported, never guessed:

- A **temporary** redirect (302/307, or a chain mixing permanent and temporary hops) is only a suggestion. Pass `--redirects all` if you want those applied too.
- **Two files** named `config.md` means no auto-fix — both are listed so you can pick.
- **No basename match** falls back to close-name suggestions.
- An **archive snapshot** is never substituted for you.

### Safety

Rewriting source files is the one thing linksanity does that you can't undo with a re-run, so:

- **Dry run by default** — `--write` is opt-in.
- **Clean tree required** — `--write` refuses if the files it would rewrite have uncommitted changes, which it could otherwise clobber. Commit or stash first, or pass `--force`. Outside a git repo it proceeds with a note.
- **Line-scoped edits** — only the exact line the link was found on is touched, and a URL that is a prefix of a longer URL on that line is left alone.
- **Atomic writes** — a crash mid-fix can't leave a truncated file.
- **Stale scans are safe** — if a file changed since the scan and the URL is no longer on its recorded line, that fix is skipped with a warning rather than applied blind.

### Format support

`fix` rewrites `.md`, `.rst`, `.html`, and `.htm`. Links in other scanned formats are still reported, but as suggestions you apply yourself.

`.ipynb` is deliberately excluded: notebook results carry line numbers *within a cell*, so a file-level rewrite would corrupt an unrelated line.

### A note on caches

Redirect permanence comes from status codes recorded during the check. Entries cached by linksanity 0.1.x predate that field, so redirects resolved from an old cache are treated as suggestions rather than auto-fixes. Clear the cache, or wait for the TTL, after upgrading.

## Use as a library

For Python callers that want results in-process instead of shelling out, `linksanity.scan_paths` wraps the same scan pipeline the CLI uses and returns a plain list of `LinkResult` — no asyncio required:

```python
from linksanity import scan_paths, LinkStatus

results = scan_paths(["docs/"], check_anchors=True)

broken = [r for r in results if r.status == LinkStatus.BROKEN]
for r in broken:
    print(f"{r.source_file}:{r.line} -> {r.url}")
```

Pass a `Config` (from `linksanity.load_config` or constructed directly) via the `config=` keyword for anything beyond `check_anchors`, e.g. `--workers`/`--timeout` equivalents.

Note: unlike the `linksanity scan` CLI command, `scan_paths(config=None)` does **not** auto-discover a `./linksanity.toml` in the current working directory — it uses bare `Config()` defaults. Call `load_config()` yourself and pass it as `config=` if you want the CLI's config-file discovery behavior.

## Use with AI agents

linksanity is designed to be a clean tool call for AI agents. Use `--format json` so an agent can parse structured output without screen-scraping console text.

**Exit codes** are the primary signal:

| Code | Meaning |
|---|---|
| `0` | All links OK |
| `1` | One or more broken links |
| `2` | Invocation error |

### JSON output schema

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
| `status` | `"ok"`, `"broken"`, `"redirect"`, `"too_many_redirects"`, `"skipped"`, or `"error"` |
| `link_type` | `"external"`, `"internal"`, `"anchor"`, `"external_anchor"`, or `"non_http_scheme"` |
| `http_code` | Final HTTP status, or `null` for links that were never fetched |
| `resolved_url` | Final URL after redirects; `null` when there was no redirect |
| `cell` | Notebook cell index for `.ipynb` sources; `null` otherwise. **`line` is relative to the cell, not the file** |
| `redirect_chain` | Every URL in the chain, original first; `null` when there was no redirect |
| `redirect_codes` | The status code of each hop, parallel to `redirect_chain`'s hops. All 301/308 means permanently moved and safe to rewrite. `null` for cached results written before linksanity 0.2.0 |

### Repair loop

`linksanity fix --format json` emits fix proposals rather than link results, which lets an agent apply the mechanical repairs and escalate only the judgment calls:

```bash
linksanity fix ./docs/ --format json --output fixes.json
```

```json
[
  {
    "source_file": "docs/a.md",
    "line": 12,
    "old_url": "http://old.example.com/x",
    "new_url": "https://new.example.com/x",
    "kind": "redirect",
    "auto_applicable": true,
    "detail": "301 → https://new.example.com/x"
  }
]
```

| Key | Meaning |
|---|---|
| `kind` | `"redirect"`, `"moved_file"`, or `"wayback"` |
| `auto_applicable` | `true` = linksanity will apply it under `--write`. `false` = it needs a human |
| `detail` | Why this was proposed — worth surfacing verbatim when escalating |

The loop:

1. `linksanity fix ./docs/ --format json --output fixes.json` — exit `0` means nothing to fix, and you're done.
2. Apply the safe ones: `linksanity fix ./docs/ --write`.
3. Escalate the rest. Every proposal with `auto_applicable: false` is a decision, not a defect: which of two `config.md` files was meant, whether a 302 is permanent enough to bake in, whether an archive snapshot is an acceptable substitute for a dead link. Present `old_url`, `new_url`, and `detail`, and let the human choose.
4. Re-run `linksanity scan ./docs/` to confirm the fixes landed.

An example prompt for step 3:

> These links are broken and I couldn't repair them safely. For each one, tell me which replacement to use, or say "leave it":
> `{paste the auto_applicable: false proposals}`

Two things worth building into an agent that drives `--write`:

- **Commit first.** `--write` refuses on a dirty tree by design. Don't reach for `--force` to get around that — the guard is what makes the resulting `git diff` reviewable.
- **Show the diff.** `fix` without `--write` is a safe read-only preview; use it to let a human approve before you write.

### Python subprocess usage

Use this when you want to drive linksanity as an external process — for example, from a non-Python agent, or to isolate the scan in its own process. If you're calling from Python and don't need process isolation, `scan_paths` (see "Use as a library" above) is simpler than parsing subprocess output.

`result.returncode` is the fast path: check it before touching the file. If it's `2`, something went wrong with invocation — read `result.stderr` for the error message rather than trying to parse the output file.

```python
import json
import subprocess

result = subprocess.run(
    ["linksanity", "scan", "./docs/", "--format", "json", "--output", "results.json"],
    capture_output=True,  # stdout goes to the file; stderr carries error messages
    text=True,
)

if result.returncode == 2:
    raise RuntimeError(f"linksanity invocation error: {result.stderr.strip()}")

with open("results.json") as f:
    links = json.load(f)

# result.returncode == 1 means broken links exist; iterate to act on them
broken = [r for r in links if r["status"] == "broken"]
```

### MCP tool definition

Register linksanity as a tool so an AI agent can call it on demand:

```json
{
  "name": "check_links",
  "description": "Scan documentation files for broken links. Returns structured JSON. Exit code 1 means broken links were found.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "paths": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Files or directories to scan"
      },
      "skip_urls_file": {
        "type": "string",
        "description": "Path to a file listing URLs to skip (optional)"
      }
    },
    "required": ["paths"]
  }
}
```

Invoke it in your MCP server by shelling out to `linksanity scan <paths> --format json --output /tmp/results.json` and returning the parsed JSON. In other words, your tool handler spawns the `linksanity` CLI as a child process, waits for it to finish writing the results file, then reads and returns that JSON — the CLI itself is the stable interface, not linksanity's internal Python modules.

### Claude Code / claude-code tool call

If you use Claude Code, you can invoke linksanity directly from the Claude CLI:

```
! linksanity scan ./docs/ --format json --output results.json
```

Then ask Claude to interpret the output:

```
Read results.json and summarise which links are broken and why they might have rotted.
```

## Options

### Which flag works with which subcommand

The three subcommands share most flags but not all of them. Passing a flag to a
subcommand that doesn't define it exits `2` with `No such option`.

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

A `linksanity.toml` is shared by all three subcommands, so a key set there is
accepted even by a subcommand with no matching flag. Keys that a subcommand
doesn't act on are ignored silently — `check_images` is ignored by `crawl`,
for example, since `crawl` has no `--check-images` flag.

### `linksanity scan <paths...>`

| Flag | Default | Description |
|---|---|---|
| `--workers N` | 5 | Max concurrent HTTP checks |
| `--timeout N` | 10 | Per-request timeout (seconds) |
| `--retry N` | 2 | Retries on 429/503 |
| `--check-anchors` | off | Validate `#fragment` links |
| `--ignore-domains FILE` | — | One domain per line to skip |
| `--js-domains FILE` | — | Domains to check via Playwright |
| `--skip-urls FILE` | — | URLs/patterns to skip (one per line, `*` wildcards ok) |
| `--format` | console | `console`, `json`, or `csv` |
| `--output FILE` | stdout | Write results to file |
| `--report FILE` | — | Write Markdown summary to file |
| `--github-issue` | off | Open/update a GitHub Issue |
| `--repo OWNER/REPO` | — | Required with `--github-issue` |
| `--config FILE` | auto | Path to `linksanity.toml` |
| `--annotations` / `--no-annotations` | auto-detect | Emit GitHub Actions `::error`/`::warning` annotations (auto-enabled in Actions unless writing JSON/CSV to bare stdout) |
| `--offline` | off | Skip external HTTP checks, reporting them as `skipped`; doesn't touch the cache |

### `linksanity fix <paths...>`

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

### `linksanity crawl <url>`

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

## Configuration file

Place a `linksanity.toml` in your project root (auto-discovered):

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

## Exit codes

For `scan` and `crawl`:

| Code | Meaning |
|---|---|
| `0` | All links OK (or only redirects/skipped) |
| `1` | One or more broken links |
| `2` | Invocation error (bad arguments, missing file) |

For `fix`:

| Code | Meaning |
|---|---|
| `0` | Nothing to fix |
| `1` | Proposals exist (dry run), or were applied (`--write`) |
| `2` | Invocation error, or `--write` refused a dirty working tree |

## Development

Clone the [repository](https://github.com/ya8282/linksanity) and set up a dev environment:

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,browser]"
playwright install chromium

# Run tests
pytest

# Lint + type check
ruff check linksanity/ tests/
mypy linksanity/
```

## License

MIT
