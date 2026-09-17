---
title: Scanning Local Files
sidebar_position: 1
---

`linksanity scan` is the entry point for checking links in a local checkout — no network crawl needed to find the links, only to check the external ones it finds.

## Scan a directory, specific files, or globs

```bash
# Scan a directory (walks all supported file extensions recursively)
linksanity scan ./docs/

# Scan specific files or globs
linksanity scan README.md docs/**/*.md
```

linksanity checks links in 8 file formats: Markdown (`.md`), reStructuredText (`.rst`), HTML (`.html`, `.htm`), AsciiDoc (`.adoc`, `.asciidoc`), MDX (`.mdx`), Jupyter Notebooks (`.ipynb`, markdown cells only), MyST-flavored Markdown (`.md` with `--myst`, below), and DocBook (`.xml`, `.dbk`).

When a path is a directory, linksanity walks it recursively for every one of those extensions. When a path is a file or a glob, it's used as given — no extension filtering beyond what the glob itself matches.

## Known issue: directory scans descend into `node_modules` and `.venv`

Scanning a directory walks it recursively with no exclusion list — verified in `linksanity/scanner.py`'s `_expand_paths`, which calls `Path.rglob` per extension and never skips vendored or virtual-env directories. Point `linksanity scan` at a repo root that contains a `node_modules/` or `.venv/` directory (a Python virtualenv commonly ships `.md` files inside installed package metadata) and it walks into both, parsing every matching file it finds there too.

**Workaround until this is fixed:** scan a narrower path that doesn't contain those directories — `linksanity scan ./docs/` rather than `linksanity scan .`. A [`.linksanity-skip`](/recipes/excluding-links) file does not fix this: it only filters which already-discovered *URLs* get checked, not which files get walked in the first place, so it can't stop linksanity from parsing files inside `node_modules/` or `.venv/`.

## `--offline`

```bash
# Skip external HTTP checks entirely — useful offline, or for a fast local-only pass
linksanity scan ./docs/ --offline
```

External links are reported as `SKIPPED` instead of checked, and `--offline` also skips reading and writing the link cache for them. Local file links and anchor checks still run as normal.

## `--myst`

```bash
# Also extract MyST {doc}/{ref} role targets from .md files
linksanity scan ./docs/ --myst
```

Off by default. It only affects `.md` files, adding MyST role-target extraction (`{doc}`, `{ref}`) alongside the standard Markdown link extraction that always runs.

## `--link-style`

```bash
# Resolve relative links the way a Docusaurus build would once deployed
linksanity scan ./docs/ --link-style docusaurus
```

For docs sites where the built site resolves relative links differently than the raw source tree. Accepts `mkdocs`, `docusaurus`, or `sphinx`; anything else exits `2`.
