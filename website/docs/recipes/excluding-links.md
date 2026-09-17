---
title: Excluding Links
sidebar_position: 3
---

Two flags exclude links from checking, and both take a **file path**, not a literal value on the command line. They share the same file format and are available on `scan`, `fix`, and `crawl`.

## `--ignore-domains`

```bash
# Skip domains you don't control
echo "internal.corp.example.com" > ignore.txt
linksanity scan ./docs/ --ignore-domains ignore.txt
```

One domain per line. A link is skipped if its host matches a line exactly, or is a subdomain of one — `internal.corp.example.com` in the file also skips `staging.internal.corp.example.com`, with no wildcard needed.

## `--skip-urls`

```bash
linksanity scan ./docs/ --skip-urls .linksanity-skip
```

One URL or pattern per line, matched with glob-style wildcards (Python's `fnmatch`: `*` matches any sequence of characters) rather than a substring or regex match. This matters because it's easy to get wrong silently — `https://staging.example.com` in the file matches only that exact URL, not everything under it; you need the trailing `*` (`https://staging.example.com/*`) to cover the whole site.

`--skip-urls` only affects external links (`http://`/`https://` targets that get checked over the network). Local file links and same-page anchors are resolved before the skip check ever runs, so listing one in the file has no effect on it.

## The `.linksanity-skip` file

`.linksanity-skip` isn't auto-discovered — it's a filename convention for the file you pass to `--skip-urls`, typically committed at the repo root so both local runs and CI use the same list:

```
# .linksanity-skip
https://app.example.com/login
https://staging.example.com/*
https://internal.corp.example.com/*
```

- Blank lines are ignored.
- A line is a comment only if `#` is the very first character — `# comment` is dropped, but a line indented before the `#` (`  # comment`) is **not** recognized as a comment and is treated as a literal pattern instead. Keep comment lines unindented.
- Every other line is matched against discovered URLs with the same `fnmatch` wildcard rules as `--skip-urls` above (because the file is read into the same `skip_urls` set).

In CI, wire it into the scan step:

```bash
linksanity scan ./docs/ \
  --skip-urls .linksanity-skip \
  --format json \
  --output linkcheck.json
```
