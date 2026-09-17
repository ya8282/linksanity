---
title: Troubleshooting
sidebar_position: 1
---

Common failure modes, keyed to the actual message you'll see and the code path that produces it, not general link-checker folklore.

## Rate limited by a host (HTTP 429)

**Symptom:** the JSON report shows `"status": "broken"` with `"http_code": 429` for a URL that opens fine in a browser.

**Cause:** linksanity already retries `429` and `503` responses on its own — `_RETRY_ON = {429, 503}` — sleeping `2 ** attempt` seconds between attempts, up to `--retry` (default 2). Once retries are exhausted it reports the last response as `broken`, http code and all; there's no separate "rate limited" status.

**Fix:** give the host more room — fewer concurrent requests and more retries:

```bash
linksanity scan ./docs/ --workers 2 --retry 4
```

If the host rate-limits you no matter what, skip it instead:

```bash
echo "flaky-host.example.com" >> ignore.txt
linksanity scan ./docs/ --ignore-domains ignore.txt
```

## Network errors and timeouts (DNS, connection reset, TLS)

**Symptom:** the JSON report shows `"status": "error"` — never `"broken"` — with `"http_code": null` and the `error` field holding whatever the transport library reported (a DNS lookup failure, a reset connection, a TLS handshake failure all land here).

**Cause:** these never get an HTTP response to classify, so they can't go through the normal `broken` path. They're caught as `except httpx.HTTPError as exc:` and, once retries are exhausted, stored verbatim as `error=str(last_exc)`. The `http_code: null` is the tell — a real 4xx/5xx from the server is always `broken` with a populated `http_code`; a transport-level failure is always `error` with `http_code` unset.

**Fix:** most of these are a too-short timeout, not a genuinely dead host — raise it before assuming the link is broken:

```bash
linksanity scan ./docs/ --timeout 20 --retry 3
```

## A host blocks bots with 401, 403, or a nonstandard code like LinkedIn's 999

**Symptom:** `"status": "broken"` with `"http_code": 401`, `403`, or `999` for a page that opens fine in a real browser.

**Cause:** status classification has no bot-detection exception — `if code >= 400: return LinkStatus.BROKEN` treats every 4xx (and LinkedIn's non-standard 999) the same as an actually-dead link.

**Fix:** exclude the domain rather than trying to make requests look like a browser:

```bash
echo "linkedin.com" >> ignore.txt
linksanity scan ./docs/ --ignore-domains ignore.txt
```

If you only want to skip specific pages on a host rather than the whole domain, use `--skip-urls` instead — see [Excluding Links](/recipes/excluding-links).

## `crawl` exits immediately with "Playwright is required"

**Symptom:**

```
[linksanity] Playwright is required for crawl mode.
Install it: pip install linksanity[browser] && playwright install chromium
```

**Cause:** `crawl` checks for the `playwright` package before doing anything else and exits with status `2` if the import fails — no scan is attempted. The same guard runs for `scan`/`fix` when `--js-domains` is set (`"Playwright is required for --js-domains."`), since JS-rendered pages need a browser too.

**Fix:**

```bash
pip install "linksanity[browser]"
playwright install chromium
```

See [Installation](/guides/installation) for the from-source variant.

## Running out of file descriptors under high `--workers`

**Symptom:** `linksanity scan` aborts partway through, or a batch of otherwise-fine URLs all come back `"status": "error"` with an OS-level message (something like `[Errno 24] Too many open files`) in the `error` field — that text comes from the operating system, not from a linksanity-defined string.

**Cause:** concurrency is gated only by `asyncio.Semaphore(config.workers)`, one open connection per in-flight check; nothing lowers `--workers` automatically when the process's file-descriptor limit is tight. Any `OSError` raised while opening a connection is caught by the generic top-level handler — `except Exception as exc:` → `error=str(exc)` — and surfaces whatever the OS said, unfiltered.

**Fix:** lower concurrency:

```bash
linksanity scan ./docs/ --workers 3
```

If you need the higher concurrency, raise the shell's open-file limit instead (`ulimit -n 4096`) before running the same command.

## Too many redirects

**Symptom:** the JSON report shows `"status": "too_many_redirects"` with an error like `too many redirects (max 10)`.

**Cause:** after `--max-redirects` hops (default 10) without settling on a final response, httpx raises `TooManyRedirects`, which linksanity reports as its own `too_many_redirects` status — a failing status distinct from `broken`.

This has a sharp edge in CI: the GitHub Action's `::error::` annotation step only looks at `status == "broken"` or `status == "error"` results, but the job's exit code also fails on `too_many_redirects`. A run whose only failures are redirect loops fails the job with zero annotations explaining why — you have to open the uploaded JSON artifact to find them. See [GitHub Actions](/ci/github-actions) for the full writeup.

**Fix:** if the chain is long but does eventually resolve, raise the cap:

```bash
linksanity scan ./docs/ --max-redirects 20
```

If it's a genuine redirect loop, fix the source link instead — raising `--max-redirects` won't help a loop.

## Internal link reports `"broken"` with "file not found"

**Symptom:** `"status": "broken"` with an error like `file not found: /path/to/docs/guide.md`, or for an anchor link, `anchor '#section' not found in guide.md`.

**Cause:** an internal link is resolved relative to its source file's directory; if nothing exists at that path, linksanity tries your `--link-style` preset's built-URL conventions (mkdocs, docusaurus, or sphinx — extensionless links, directory-index links) before giving up. The most common false alarm is a missing `--link-style`: the file exists on disk, but the link is written the way the *built* site serves it, not as a raw source path.

**Fix:** tell linksanity which static-site generator's link conventions to try:

```bash
linksanity scan ./docs/ --link-style docusaurus
```

See [Configuration](/guides/configuration) for the other `--link-style` presets and where this can live in `linksanity.toml` instead of on the command line.
