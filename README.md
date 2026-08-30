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
- **GitHub Issues** — create or update an issue summarising failing links (broken, checker errors, and redirect loops)
- **Ignore domains** — skip domains you don't control
- **JS-rendered pages** — route specific domains through Playwright in scan mode
- **Retry logic** — exponential back-off on 429/503; HEAD→GET fallback on 405

## Adopt what you need

linksanity is modular — install only what you need for your use case.

| Use case | Install | Minimal example | Details |
|---|---|---|---|
| **Setup wizard** | `pip install linksanity` | `linksanity init` | [Setup: `linksanity init`](#setup-linksanity-init) |
| **Scanner only** | `pip install linksanity` | `linksanity scan ./docs/` | [Quick start](#quick-start) |
| **Fixer** | already included | `linksanity fix ./docs/` (dry run; add `--write` to apply) | [Fixing broken links](#fixing-broken-links) |
| **Browser crawl** | `pip install "linksanity[browser]"` then `playwright install chromium` | `linksanity crawl https://docs.example.com` | [Crawl a live site](#crawl-a-live-site) |
| **Pre-commit hook** | already included; add to `.pre-commit-config.yaml` | `repo: https://github.com/ya8282/linksanity`, `rev: v0.2.1`, `hooks: [{id: linksanity}]` | [Pre-commit hook](#pre-commit-hook) |
| **GitHub Action** | none — no local install needed | `- uses: ya8282/linksanity-action@v1` with `paths: docs/` | [CI integration](#ci-integration) — see the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) repo |
| **Library API** | `pip install linksanity` | `from linksanity import scan_paths` | [Use as a library](#use-as-a-library) (note: no `linksanity.toml` auto-discovery, unlike the CLI) |

## Supported formats

linksanity checks links in 8 file formats:

- **Markdown** — `.md` files
- **reStructuredText** — `.rst` files
- **HTML** — `.html`, `.htm` files
- **AsciiDoc** — `.adoc`, `.asciidoc` files
- **MDX** — `.mdx` files (CommonMark + JSX)
- **Jupyter Notebooks** — `.ipynb` files (extracts markdown cells)
- **MyST-flavored Markdown** — `.md` files with opt-in `--myst` flag or `myst = true` in config (enables MyST role extraction: `{doc}`, `{ref}`)
- **DocBook** — `.xml`, `.dbk` files (extracts `<xref linkend>` for DocBook 4 and 5, `<link xlink:href>` for DocBook 5, and `<ulink url>` for DocBook 4)

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

## Setup: `linksanity init`

The recommended way to add link checking to a repo is the setup wizard. It ships in the wheel, so no cloning is required:

```bash
pip install linksanity
linksanity init
```

`init` detects likely documentation directories, shows a table so you can confirm or edit the selection, runs a timed scan so you can see roughly what it will cost in CI, and writes `.github/workflows/linkcheck.yml` for you (plus, if the scan finds pre-existing breakage, an offered baseline file).

**`init` never runs git.** It only writes files, then prints the `git add`/`git commit` commands so you can review before committing:

```
Wrote .github/workflows/linkcheck.yml
Wrote .linksanity-baseline.json  (12 known-broken links)

  git add .github/workflows/linkcheck.yml .linksanity-baseline.json
  git commit -m "Add linksanity link checking"
```

The generated workflow runs the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) on every pull request:

```yaml
name: Link check
on: [pull_request]
permissions:
  contents: read
jobs:
  linkcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ya8282/linksanity-action@v1
        with:
          paths: docs/ README.md
          baseline: .linksanity-baseline.json
```

The `baseline:` line only appears if a baseline was written.

### Non-interactive / agent use

`--yes` skips every prompt, but requires `--paths`, since a non-interactive run has to state what to scan:

```bash
linksanity init --yes --paths docs/
```

### Baselines

A baseline is just the scan's JSON results file, the same file `--format json --output` produces. When the measuring scan finds pre-existing breakage (any result with status `broken`, `error`, or `too_many_redirects`), `init` offers to write one. Accepting means CI starts green against the docs you already have and fails only on links that break *after* adoption, instead of going red on day one against rot nobody asked to fix, which is the usual reason a freshly-added link checker gets deleted within a month.

Interactively you're asked before a baseline is written. Under `--yes`, a baseline is written by default whenever breakage is found; pass `--no-baseline` to opt out:

```bash
linksanity init --yes --paths docs/ --no-baseline
```

To refresh a stale baseline, re-run `init` interactively rather than pointing `--baseline` at a CI results artifact. With `--baseline` set, `scan` writes `--output` *after* filtering out already-known breakage, so the artifact is already shrunken and not a valid baseline.

### The cost estimate

`init` reports two numbers separately rather than collapsing them into one confident figure: the scan time it just measured locally, and a modelled CI overhead (checkout, `setup-python`, pip install) added on top before rounding up to a billed minute. Treat it as an estimate, not a promise: your local run has a different egress IP, warmer DNS, and a different CPU than the GitHub Actions runner, so local wall time is a biased proxy for runner wall time. Illustrative sample output:

```
Measured locally:  1m 52s   (318 unique URLs, 87 domains)
CI overhead:      ~40s      (checkout, setup-python, pip install)
Estimated billed: ~3 min/run   GitHub rounds each job up to a whole minute

Public repo:  free
Private repo: ~3 min/run, so ~90 min/mo at 30 runs/mo (illustrative)
              against the 2,000 min/mo free allowance
```

The `~40s` overhead figure is illustrative, not a guarantee: it comes from a fixed constant `init` adds to your measured time, not from a live check of your repo's CI run.

### Other flags

| Flag | Effect |
|---|---|
| `--paths <dir>` | Scan these paths instead of running detection; required together with `--yes`. Repeat the flag per path (`--paths docs/ --paths README.md`). It is not space-separated like the `paths:` line in the generated workflow |
| `--no-baseline` | Skip baseline generation even if breakage is found |
| `--no-measure` | Skip the timed scan entirely: no estimate, no baseline offer (for offline/air-gapped use) |
| `--workflow-name <name>` | Filename for the generated workflow: a bare filename only, no path separators (default `linkcheck.yml`) |
| `--dry-run` | Print the generated workflow (and a one-line baseline summary) to stdout; write nothing. Still runs the real measuring scan first unless combined with `--no-measure` |

Run `linksanity init --help` for the full list.

A few behaviors worth knowing before you script around `init`:

- **`--dry-run` alone still hits the network.** It skips the *writes*, not the scan. Combine with `--no-measure` for a fully offline dry run.
- **Non-interactive without `--yes` fails fast.** If stdin isn't a TTY (e.g. piped, or in CI) and `--yes` is missing, `init` exits `2` rather than hanging on a prompt, and tells you to rerun with `--yes --paths <dir>`.
- **An existing target file is an error under `--yes`, a prompt without it.** If the workflow file (or baseline file) already exists, `--yes` refuses and exits `2`; interactively you're asked whether to overwrite.

## Quick start

### Scan local source files

```bash
# Scan a directory (walks all supported file extensions recursively — see Supported formats above)
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

# Cap total pages crawled (page budget, not a depth limit)
linksanity crawl https://docs.example.com --max-pages 50

# Ignore external domains
linksanity crawl https://docs.example.com --ignore-domains ignore.txt
```

### CI integration

The recommended way to wire this up is `linksanity init` (see [Setup: `linksanity init`](#setup-linksanity-init) above), which writes the workflow below for you after detecting and confirming paths. This section documents the underlying pieces for hand-editing an existing workflow or writing one from scratch.

Link checking in CI runs on the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) composite action — one line beyond checkout:

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

**Report failing links to a GitHub Issue** — useful for scheduled runs that find regressions after merge. Creating or updating the issue needs `issues: write`, so extend the job's `permissions:` block declared above from `contents: read` to:

```yaml
permissions:
  contents: read
  issues: write
```

```yaml
      - name: Report failing links
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

**Maintainer/advanced: generating the crawl-variant workflow** — `scripts/bootstrap_linkcheck.py` writes the *crawl* variant of this workflow (shown above) into a target repo. It is a maintainer tool that lives in this repo's `scripts/` directory, not in the published wheel, so it requires cloning the repo to run. `linksanity init` (see [Setup: `linksanity init`](#setup-linksanity-init) above) is the supported way to set up link checking and does not need a clone, but it only generates the `scan`-based workflow, not this crawl variant. Reach for `bootstrap_linkcheck.py` specifically when you want the crawl variant generated for you:

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
    rev: v0.2.1
    hooks:
      - id: linksanity
```

To run full (online) checks instead, pass `--no-offline` via `args:`. pre-commit appends a hook's `args:` after its `entry`, so the later flag wins over the `--offline` baked into the hook's entry:

```yaml
      - id: linksanity
        args: [--no-offline]
```

**File types the hook actually sees.** The hook's `types_or` is
`[markdown, rst, html]`. pre-commit resolves those tags via `identify`, which
also tags `.htm` as `html`, so `.md`, `.rst`, `.html`, and `.htm` all reach the
hook. Four of the formats linksanity's own scanner supports do not:
AsciiDoc (`.adoc`/`.asciidoc`), MDX (`.mdx`), Jupyter Notebooks (`.ipynb`),
and DocBook (`.xml`/`.dbk`) never trigger the hook, even though
`linksanity scan` checks them. If your docs use those formats, either extend
`types_or` yourself in the consuming repo's `.pre-commit-config.yaml`
(`identify` tags `.xml` as `xml`, `.ipynb` as `jupyter`, `.mdx` as `mdx`, and
`.adoc`/`.asciidoc` as `asciidoc`), or run `linksanity scan` separately in CI
for full coverage. `.dbk` is a special case: `identify` gives it no
distinguishing tag, only the generic `file`/`text` ones. pre-commit ANDs
`files` with `types_or`, so a `files:` regex alone still gets filtered out by
the manifest's `types_or` and silently matches nothing. Relax `types_or` and
narrow with `files:` together:

```yaml
- id: linksanity
  types_or: [file]
  files: \.dbk$
```

### GitHub Issue reporting

Use `--github-issue` when you want failing links (broken, checker errors, or redirect loops) surfaced as a trackable GitHub Issue rather than just a failed CI run. It creates or updates a single issue titled `[linksanity] N failing link(s) found`, refreshing both the title's count and the body's link table on every run, so the team has a persistent record to triage — not just a red check mark that disappears on the next push.

linksanity finds its existing issue by scanning up to 1000 open issues, most-recently-updated first; on a repo with more open issues than that, it warns on stderr and may open a second issue instead of updating the first.

**When to use it:**

- **Scheduled runs** — a weekly cron job catches link rot that crept in after your last merge. linksanity only creates or updates the issue while links are failing — it never closes or comments on it once they're fixed, so close it yourself.
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
| `wayback` (only built with `--wayback`) | A dead external link (404/410), or one that failed outright — DNS failure, connect timeout, TLS error — with an Internet Archive snapshot | Low — a judgment call | **Never** — suggested only |

`redirect` and `moved_file` proposals are always built from a scan. `wayback`
proposals are opt-in: pass `--wayback` or none are generated.

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

## Use as a library

For Python callers that want results in-process instead of shelling out, `linksanity.scan_paths` wraps the same scan pipeline the CLI uses and returns a plain list of `LinkResult` — no asyncio required:

```python
from linksanity import scan_paths, LinkStatus

results = scan_paths(["docs/"], check_anchors=True)

broken = [r for r in results if r.status == LinkStatus.BROKEN]
for r in broken:
    print(f"{r.source_file}:{r.line} -> {r.url}")
```

For `.ipynb` sources, `r.line` is relative to the cell, not the file — use
`r.cell` (the cell index, `None` for non-notebook sources) alongside it if
you need a file-wide position.

Pass a `Config` (from `linksanity.load_config` or constructed directly) via the `config=` keyword for anything beyond `check_anchors`, e.g. `--workers`/`--timeout` equivalents.

Note: unlike the `linksanity scan` CLI command, `scan_paths(config=None)` does **not** auto-discover a `linksanity.toml` by walking up from the current working directory — it uses bare `Config()` defaults. Call `load_config()` yourself and pass it as `config=` if you want the CLI's config-file discovery behavior.

## Use with AI agents

linksanity is designed to be a clean tool call for AI agents. Use `--format json` so an agent can parse structured output without screen-scraping console text.

**Exit codes** are the primary signal — but they mean different things for `scan`/`crawl` than for `fix`:

| Command | `0` | `1` | `2` |
|---|---|---|---|
| `scan`, `crawl` | all links OK | one or more broken links | invocation error |
| `fix` | nothing to fix | proposals exist (dry run), or were applied (`--write`) | invocation error, or `--write` refused a dirty tree |

A `fix` exit of `1` is not a failure signal by itself — check `auto_applicable` in the JSON output (below) or the diff to see what happened. See [Exit codes](#exit-codes) below for the full detail.

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
| `redirect_chain` | Every URL in the chain, original first; `null` unless an HTTP redirect response was actually received, and also `null` in the rare case where a hop's status code couldn't be determined (chain and codes are always `null` together, never one without the other, so a code is never guessed). A URL that differs only by normalization (host case, scheme case, dot-segments) with no real redirect reports `status: "ok"`, not `"redirect"` |
| `redirect_codes` | The status code of each hop, parallel to `redirect_chain`'s hops. All 301/308 means permanently moved and safe to rewrite. `null` whenever `redirect_chain` is `null`, for the same reasons |

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

The four subcommands share most flags but not all of them. Passing a flag to a
subcommand that doesn't define it exits `2` with `No such option`. `init` has
its own flag set (see [Setup: `linksanity init`](#setup-linksanity-init) above)
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
regardless of subcommand.

### `linksanity scan <paths...>`

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

### `linksanity init`

Does not share flags with `scan`/`fix`/`crawl`. See
[Setup: `linksanity init`](#setup-linksanity-init) above for the full
walkthrough.

| Flag | Default | Description |
|---|---|---|
| `--yes` | off | Run non-interactively; requires `--paths` |
| `--paths <dir>` | — | Paths to scan for the workflow's `paths:` input; skips detection. Repeat per path |
| `--no-baseline` | off | Skip baseline generation even if breakage is found |
| `--no-measure` | off | Skip the timed scan entirely: no estimate, no baseline offer |
| `--workflow-name <name>` | `linkcheck.yml` | Filename for the generated workflow: a bare name, no path separators |
| `--dry-run` | off | Print the generated files; write nothing |

## Configuration file

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

Four `Config` fields — `output`, `report`, `github_issue`, `github_repo` — are
never read from `linksanity.toml` at all; see the note under the flag
compatibility matrix above.

## Exit codes

For `scan` and `crawl`:

| Code | Meaning |
|---|---|
| `0` | All links OK (or only plain redirects/skipped) |
| `1` | One or more broken links, errors, or redirect loops (`--max-redirects` exceeded) |
| `2` | Invocation error (bad arguments) |

For `fix`:

| Code | Meaning |
|---|---|
| `0` | Nothing to fix |
| `1` | Proposals exist (dry run), or were applied (`--write`) |
| `2` | Invocation error, or `--write` refused a dirty working tree |

For `init`:

| Code | Meaning |
|---|---|
| `0` | Success, or a clean `--dry-run` |
| `2` | Any refusal or error (bad arguments, non-TTY stdin without `--yes`, an existing target file, a failed scan or write) |

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
ruff check linksanity/ tests/ scripts/
mypy linksanity/
```

## License

MIT
