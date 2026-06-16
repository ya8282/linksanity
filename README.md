# linksanity (🏀17)

Detect broken links and redirects in Markdown, reStructuredText, and HTML documentation.

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

# Optional: browser support for JS-rendered pages
pip install "linksanity[browser]"
playwright install chromium
```

Requires Python 3.11+.

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

```yaml
# .github/workflows/linkcheck.yml
- name: Check links
  run: |
    pip install linksanity
    linksanity scan ./docs/ --format json --output linkcheck.json
  continue-on-error: false
```

### GitHub Issue reporting

```bash
export GITHUB_TOKEN=ghp_...
linksanity scan ./docs/ --github-issue --repo owner/repo
```

Creates or updates a single `[linksanity]` issue summarising all broken links. The token is read from the environment and never stored.

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

## Configuration file

Place a `linksanity.toml` in your project root (auto-discovered):

```toml
workers = 10
timeout = 15
retry = 3
check_anchors = false
max_pages = 200

ignore_domains = ["status.example.com", "internal.example.com"]
js_domains = ["spa.example.com"]
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
