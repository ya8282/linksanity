---
title: GitHub Actions
sidebar_position: 1
---

The recommended way to wire this up is [`linksanity init`](../guides/getting-started.md), which writes a workflow for you after detecting and confirming paths. This page documents the underlying pieces for hand-editing an existing workflow or writing one from scratch.

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
| `fail-on-redirect-loop` | Whether a redirect loop (`too_many_redirects`) counts toward `broken-count` and fails the job (`"true"`/`"false"`). When set to `"false"`, redirect-loop links are excluded from `broken-count` and are instead surfaced as a `::warning::` annotation (see the `warnings` output) rather than failing the job. | `true` |

`--js-domains` passed via `args` requires `browser: true`; otherwise the action fails fast with a clear error instead of installing Playwright unconditionally on every run.

`baseline` must contain no whitespace and must not start with `-` (the value is passed unquoted); the action fails with an error rather than proceeding. If set and the named file does not exist, the action also fails — it does not silently fall back to checking everything.

### Outputs

| Name | Description |
| --- | --- |
| `broken-count` | Number of links found by the scan with a failing status (`broken`, `error`, or `too_many_redirects` — a redirect loop counts as a failure even though it isn't literally "broken"). |
| `results-file` | Path to the JSON results file written by the scan. |
| `annotations` | The literal `::error::` annotation lines the action printed for failing links (empty when there were none). A caller can read this output to inspect or re-emit the exact annotation text instead of re-parsing the results file. |
| `warnings` | The literal `::warning::` annotation lines the action printed for redirect-loop links when `fail-on-redirect-loop` is `"false"` (empty when there were none). Same purpose as `annotations`, for the warning-only path. |

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

### Behaviour worth knowing about

**The action pins a version, it does not track latest.** This is intended, documented behaviour, not a defect. The action's `version` input defaults to `0.2.0`, a specific pin, not an empty string. A workflow that uses `ya8282/linksanity-action@v1` without setting `version:` therefore installs `linksanity==0.2.0`, not whatever the newest release on PyPI is. `linksanity init`'s local cost-estimate output names this pinned version, so the estimate and the generated workflow agree. If you want to track the newest release instead, pass `version: ""` explicitly; a CLI change (e.g. a renamed or removed flag) can then break the action without warning. To pin to something other than `0.2.0`, pass an explicit `version: "X.Y.Z"`.

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

```text
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

Gate this step to the scheduled trigger with `if: ${{ !cancelled() && github.event_name == 'schedule' }}`, not `if: failure()`: it must also run on a clean scheduled run so it can comment that the links now resolve and close the standing issue, but it must not run on `push`/`pull_request` runs, where a clean PR would wrongly close an issue opened by main's schedule and a fork PR's read-only token would turn the step red trying to write to it.

```yaml
      - name: Update the link-rot issue
        if: ${{ !cancelled() && github.event_name == 'schedule' }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          linksanity scan ./docs/ \
            --github-issue \
            --repo ${{ github.repository }}
```

See [Issue reporting](./issue-reporting.md) for what the issue looks like and what permissions it needs.

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

**Maintainer/advanced: generating the crawl-variant workflow** — `scripts/bootstrap_linkcheck.py` writes the *crawl* variant of this workflow into a target repo. It is a maintainer tool that lives in the linksanity repo's `scripts/` directory, not in the published wheel, so it requires cloning the repo to run. [`linksanity init`](../guides/getting-started.md) is the supported way to set up link checking and does not need a clone, but it only generates the `scan`-based workflow, not this crawl variant. Reach for `bootstrap_linkcheck.py` specifically when you want the crawl variant generated for you:

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
