---
title: Overview
sidebar_position: 1
---

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
- **Fix, don't just report** — `linksanity fix` rewrites permanently-redirected URLs and moved-file links in place (see [Fixing broken links](/recipes/fixing-broken-links))
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
| **Setup wizard** | `pip install linksanity` | `linksanity init` | [Setup: `linksanity init`](/guides/getting-started) |
| **Scanner only** | `pip install linksanity` | `linksanity scan ./docs/` | [Quick start](/guides/getting-started) |
| **Fixer** | already included | `linksanity fix ./docs/` (dry run; add `--write` to apply) | [Fixing broken links](/recipes/fixing-broken-links) |
| **Browser crawl** | `pip install "linksanity[browser]"` then `playwright install chromium` | `linksanity crawl https://docs.example.com` | [Crawl a live site](/guides/getting-started) |
| **Pre-commit hook** | already included; add to `.pre-commit-config.yaml` | `repo: https://github.com/ya8282/linksanity`, `rev: v0.3.0`, `hooks: [{id: linksanity}]` | [Pre-commit hook](/ci/pre-commit) |
| **GitHub Action** | none — no local install needed | `- uses: ya8282/linksanity-action@v1` with `paths: docs/` | [CI integration](/ci/github-actions) — see the [ya8282/linksanity-action](https://github.com/ya8282/linksanity-action) repo |
| **Library API** | `pip install linksanity` | `from linksanity import scan_paths` | [Use as a library](/agents) (note: no `linksanity.toml` auto-discovery, unlike the CLI) |

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
