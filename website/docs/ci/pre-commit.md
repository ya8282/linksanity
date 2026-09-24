---
title: Pre-commit
sidebar_position: 2
---

Run linksanity locally before each commit using [pre-commit](https://pre-commit.com/). A pre-commit run is local: it hits the network to check live URLs unless `--offline` is used.

## Setup

```yaml
# .pre-commit-config.yaml (in the consuming repo)
repos:
  - repo: https://github.com/ya8282/linksanity
    rev: v0.4.0
    hooks:
      - id: linksanity
```

The hook's `entry` is `linksanity scan --offline`, so by default it skips live HTTP checks (reporting them as `SKIPPED`) and stays fast without failing on a flaky network.

To run full (online) checks instead, pass `--no-offline` via `args:`. pre-commit appends a hook's `args:` after its `entry`, so the later flag wins over the `--offline` baked into the hook's entry:

```yaml
      - id: linksanity
        args: [--no-offline]
```

Any other `linksanity scan` flag can be passed the same way, appended after `args:`.

## Which files the hook sees

The hook is declared with `types_or: [markdown, rst, html]`. pre-commit resolves those tags via `identify`, which also tags `.htm` as `html`, so `.md`, `.rst`, `.html`, and `.htm` all reach the hook.

Four of the formats linksanity's own scanner supports do not trigger the hook, even though `linksanity scan` checks them directly:

- AsciiDoc (`.adoc`/`.asciidoc`)
- MDX (`.mdx`)
- Jupyter Notebooks (`.ipynb`)
- DocBook (`.xml`/`.dbk`)

If your docs use those formats, either extend `types_or` yourself in the consuming repo's `.pre-commit-config.yaml` (`identify` tags `.xml` as `xml`, `.ipynb` as `jupyter`, `.mdx` as `mdx`, and `.adoc`/`.asciidoc` as `asciidoc`), or run `linksanity scan` separately in CI for full coverage.

`.dbk` is a special case: `identify` gives it no distinguishing tag, only the generic `file`/`text` ones. pre-commit ANDs `files:` with `types_or:`, so a `files:` regex alone still gets filtered out by the manifest's `types_or:` and silently matches nothing. Relax `types_or:` and narrow with `files:` together:

```yaml
- id: linksanity
  types_or: [file]
  files: \.dbk$
```

## Passing extra arguments

Any flag `linksanity scan` accepts can be passed via `args:` — it's appended after the hook's `entry`, so a later flag with the same name wins over one baked into `entry` (as with `--no-offline` above). For example, to also check in-page anchors:

```yaml
      - id: linksanity
        args: [--check-anchors]
```

See the [CLI reference](../guides/cli-reference.md) for the full flag list.
