---
title: Getting Started
sidebar_position: 2
---

## Setup: `linksanity init`

The recommended way to add link checking to a repo is the setup wizard. It ships in the wheel, so no cloning is required:

```bash
pip install linksanity
linksanity init
```

`init` detects likely documentation directories, shows a table so you can confirm or edit the selection, runs a timed scan so you can see roughly what it will cost in CI, and writes `.github/workflows/linkcheck.yml` for you (plus, if the scan finds pre-existing breakage, an offered baseline file).

**`init` never runs git.** It only writes files, then prints the `git add`/`git commit` commands so you can review before committing:

```text
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

`init` reports two numbers separately rather than collapsing them into one confident figure: the scan time it just measured locally, and a modelled CI overhead (runner setup, checkout, `setup-python`, pip install, artifact upload) added on top before rounding up to a billed minute. Treat it as an estimate, not a promise: your local run has a different egress IP, warmer DNS, and a different CPU than the GitHub Actions runner, so local wall time is a biased proxy for runner wall time. Illustrative sample output:

```text
Measured locally:  1m 52s   (318 unique URLs, 87 domains)
CI overhead:      ~9s      (runner setup, checkout, python, pip install, artifact upload)
Estimated billed: ~3 min/run   GitHub rounds each job up to a whole minute

Public repo:  free
Private repo: ~3 min/run, so ~90 min/mo at 30 runs/mo (illustrative)
              against the 2,000 min/mo free allowance
```

The `~9s` overhead figure is illustrative, not a guarantee: it comes from a fixed constant `init` adds to your measured time, not from a live check of your repo's CI run.

### Other flags

| Flag | Effect |
|---|---|
| `--paths <dir>` | Scan these paths instead of running detection; required together with `--yes`. Repeat the flag per path (`--paths docs/ --paths README.md`). It is not space-separated like the `paths:` line in the generated workflow. Values are literal directory or file paths, not glob patterns |
| `--no-baseline` | Skip baseline generation even if breakage is found |
| `--no-measure` | Skip the timed scan entirely: no estimate, no baseline offer (for offline/air-gapped use) |
| `--workflow-name <name>` | Filename for the generated workflow: a bare filename only, no path separators (default `linkcheck.yml`) |
| `--dry-run` | Print the generated workflow (and a one-line baseline summary) to stdout; write nothing. Still runs the real measuring scan first unless combined with `--no-measure` |

Run `linksanity init --help` for the full list.

A few behaviors worth knowing before you script around `init`:

- **`--dry-run` alone still hits the network.** It skips the *writes*, not the scan. Combine with `--no-measure` for a fully offline dry run.
- **Non-interactive without `--yes` fails fast.** If stdin isn't a TTY (e.g. piped, or in CI) and `--yes` is missing, `init` exits `2` rather than hanging on a prompt, and tells you to rerun with `--yes --paths <dir>`.
- **An existing target file is an error under `--yes`, a prompt without it — except under `--dry-run`, which never refuses.** If the workflow file (or baseline file) already exists, `--yes` refuses and exits `2`; interactively you're asked whether to overwrite. `--dry-run` skips that check entirely: it prints a note that the file already exists and that a real run would refuse, then renders the normal dry-run output and exits `0`.

## Quick start

Both `scan` and `crawl` print one line per notable link (anything other than `ok` or `skipped`), then a summary tally:

```text
$ linksanity scan ./docs/

docs/api/guide.md
  BROKEN    line   12  ./missing.md — file not found: /home/you/project/docs/api/missing.md
  REDIRECT  line   45  https://old.example.com → https://new.example.com [301]
  TOOMANY   line   67  https://flaky.example.com — too many redirects (max 10)

────────────────────────────────────────────────────────────────────────────────────────────────────
  ok=35   broken=1   redirect=1   too_many_redirects=1   blocked=0   skipped=0
```

### Scan local source files

```bash
# Scan a directory (walks all supported file extensions recursively — see the Overview page for supported formats)
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
