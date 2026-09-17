---
title: GitHub Actions
sidebar_position: 1
---

The recommended way to wire this up is [`linksanity init`](/guides/getting-started), which writes a workflow for you after detecting and confirming paths. This page documents the underlying pieces for hand-editing an existing workflow or writing one from scratch.

There are two ways to run linksanity in GitHub Actions: the composite action, or installing the CLI directly yourself.

## Option A: the composite action

Link checking runs on the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) composite action — one line beyond checkout:

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

### Inputs

| Name | Description | Default |
| --- | --- | --- |
| `paths` | Space-separated paths to scan for links. | `.` |
| `version` | Version of linksanity to install from PyPI, pinned to the release this action is tested against. Pass `""` to track the latest release instead (may break if the CLI changes), or an explicit `X.Y.Z` to pin to something else. | `0.2.0` |
| `python-version` | Python version to set up for running linksanity. | `3.12` |
| `check-anchors` | Whether to check in-page anchor links (`"true"`/`"false"`). | `false` |
| `skip-urls` | Space-separated URL patterns to skip. | `""` |
| `output` | Path to write the JSON scan results to. | `linkcheck-results.json` |
| `baseline` | Path to a previous JSON results file; only links that are newly broken relative to it fail the job. | `""` |
| `args` | Extra raw arguments passed through to `linksanity scan` as-is. | `""` |
| `upload-results` | Whether to upload the scan results file as a workflow artifact (`"true"`/`"false"`). | `true` |
| `artifact-name` | Name of the workflow artifact to upload the scan results as. Set a distinct value per job when a workflow calls this action more than once, since `upload-artifact` rejects duplicate names within a run. | `linksanity-results` |
| `browser` | Whether to install the Playwright browser extra, required for `--js-domains` (`"true"`/`"false"`). Adds a Chromium download to the run. | `false` |

`--js-domains` passed via `args` requires `browser: true`; otherwise the action fails fast with a clear error instead of installing Playwright unconditionally on every run.

`baseline` must contain no whitespace and must not start with `-` (the value is passed unquoted); the action fails with an error rather than proceeding. If set and the named file does not exist, the action also fails — it does not silently fall back to checking everything.

### Outputs

| Name | Description |
| --- | --- |
| `broken-count` | Number of links with status `broken` or `error` found by the scan. |
| `results-file` | Path to the JSON results file written by the scan. |

### Full usage

```yaml
- uses: ya8282/linksanity-action@v1
  with:
    paths: docs/ README.md
    version: "0.2.0"
    python-version: "3.12"
    check-anchors: "true"
    skip-urls: "https://example.com/flaky-endpoint *.internal.example.com"
    output: linkcheck-results.json
    baseline: .linksanity-baseline.json
    args: "--check-images"
    upload-results: "true"
```

### Known defects in the action

Two current behaviours of the action are worth knowing about before you rely on it. Neither is fixed yet; both are tracked as open beads.

**The action pins a version, it does not track latest (linksanity-4nf).** The action's `version` input defaults to `0.2.0`, a specific pin, not an empty string. A workflow that uses `ya8282/linksanity-action@v1` without setting `version:` therefore installs `linksanity==0.2.0`, not whatever the newest release on PyPI is. `linksanity init`'s local cost-estimate output names this pinned version, so the estimate and the generated workflow agree. If you want to track the newest release instead, pass `version: ""` explicitly; a CLI change (e.g. a renamed or removed flag) can then break the action without warning. To pin to something other than `0.2.0`, pass an explicit `version: "X.Y.Z"`.

**Annotations and the exit code can disagree (linksanity-jx1).** The action's step that emits `::error::` annotations filters scan results to `status == "broken"` or `status == "error"` only. But the job's exit code comes straight from `linksanity scan`, which also fails on `status == "too_many_redirects"` (a redirect loop). A run whose only failures are `too_many_redirects` results therefore fails the job — and the `broken-count` output stays `0` — while producing zero annotations explaining why. The failure is real, but nothing in the diff view or the annotation list points at it; you have to open the uploaded results artifact to see the redirect-loop entries. If your docs are prone to redirect chains, check the uploaded JSON artifact whenever a linkcheck job goes red without a visible annotation.

## Option B: install and run the CLI directly

Prefer to install the CLI directly instead of using the action — for example on self-hosted runners without Marketplace access, or when you want full control over the install step.

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

See [Issue reporting](/ci/issue-reporting) for what the issue looks like and what permissions it needs.

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

**Maintainer/advanced: generating the crawl-variant workflow** — `scripts/bootstrap_linkcheck.py` writes the *crawl* variant of this workflow into a target repo. It is a maintainer tool that lives in the linksanity repo's `scripts/` directory, not in the published wheel, so it requires cloning the repo to run. [`linksanity init`](/guides/getting-started) is the supported way to set up link checking and does not need a clone, but it only generates the `scan`-based workflow, not this crawl variant. Reach for `bootstrap_linkcheck.py` specifically when you want the crawl variant generated for you:

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
