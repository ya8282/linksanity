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

When a path is a directory, linksanity walks it recursively for every one of those extensions, skipping vendored and hidden directories along the way (`node_modules`, `.venv`, `venv`, `site-packages`, `vendor`, `target`, `build`, `dist`, `_build`, `.tox`, and any directory starting with `.`, case-insensitive) — the same rule `linksanity init` uses to propose paths, so a directory init proposes isn't scanned in full including its vendored subtrees. That pruning only applies while walking *into* a directory: a path you pass explicitly is always scanned in full even if it's one of those names (`linksanity scan node_modules/docs/` still scans `node_modules/docs/`), and dot-*files* (e.g. a root-level `.hidden.md`) are never pruned, only dot-*directories*. When a path is a file or a glob, it's used as given — no extension filtering or pruning beyond what the glob itself matches.

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
