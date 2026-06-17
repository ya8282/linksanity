# linksanity 🏀

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

- **Static scan** — parse `.md`, `.rst`, and `.html` source files without a browser
- **Live crawl** — follow links on a deployed site using a headless browser (Playwright)
- **Exit codes** — `0` = clean, `1` = broken links found (ideal for CI)
- **Multiple formats** — console (Rich), JSON, CSV; optional Markdown summary report
- **Anchor validation** — opt-in `--check-anchors` flag
- **GitHub Issues** — create or update an issue summarising broken links
- **Ignore domains** — skip domains you don't control
- **JS-rendered pages** — route specific domains through Playwright in scan mode
- **Retry logic** — exponential back-off on 429/503; HEAD→GET fallback on 405

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
    "url": "https://example.com/old",
    "source_file": "docs/guide.md",
    "line": 42,
    "status": "broken",
    "status_code": 404,
    "redirect_url": null,
    "error": null
  }
]
```

`status` is one of `"ok"`, `"broken"`, `"redirect"`, `"skipped"`, or `"error"`.

### Python subprocess usage

Use this when you want to drive linksanity from a Python script or agent — for example, to file tickets, send alerts, or trigger auto-repair after a scan. linksanity doesn't expose a public Python API, so `subprocess.run` is the correct integration point.

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

Invoke it in your MCP server by shelling out to `linksanity scan <paths> --format json --output /tmp/results.json` and returning the parsed JSON.

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

### `linksanity crawl <url>`

Same flags as `scan`, minus `--check-anchors` and `--js-domains`, plus:

| Flag | Default | Description |
|---|---|---|
| `--max-pages N` | 500 | Stop after N pages crawled |
| `--playwright-workers N` | 2 | Max concurrent browser sessions |
| `--skip-urls FILE` | — | URLs/patterns to skip (one per line, `*` wildcards ok) |
| `--block-analytics` | off | Block analytics/tracking domains in the browser |

## Configuration file

Place a `linksanity.toml` in your project root (auto-discovered):

```toml
workers = 10
timeout = 15
retry = 3
check_anchors = false
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

| Code | Meaning |
|---|---|
| `0` | All links OK (or only redirects/skipped) |
| `1` | One or more broken links |
| `2` | Invocation error (bad arguments, missing file) |

## Development

```bash
git clone https://github.com/linksanity/linksanity
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
