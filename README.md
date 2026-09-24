# linksanity 🏀

[![PyPI](https://img.shields.io/pypi/v/linksanity.svg)](https://pypi.org/project/linksanity/)

Detect broken links and redirects in Markdown, reStructuredText, HTML, AsciiDoc, MDX, Jupyter Notebooks, MyST-flavored Markdown, and DocBook content — either by statically scanning source files or by crawling a live deployed site with a headless browser — and fix the ones it's confident about in place. Don't let dead URLs leave you hanging on the rim: linksanity keeps your documentation or web content game flawless, so you never drop the ball on your readers.

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

## Install

```bash
pip install linksanity
```

For JS-rendered pages (Playwright headless browser, needed for `crawl`):

```bash
pip install "linksanity[browser]"
playwright install chromium
```

Requires Python 3.11+.

## Quick start

```bash
$ linksanity scan ./docs/
docs/api/guide.md
  BROKEN    line   12  ./missing.md — file not found
  REDIRECT  line   45  https://old.example.com → https://new.example.com

ok=38   broken=1   redirect=1   skipped=0
```

Exit code `0` means every link is clean; `1` means at least one broken or redirected link was found — plug that straight into CI. See [Exit codes](https://ya8282.github.io/linksanity/guides/output-modes#exit-codes) for the full table, including `2` and `3`. Point it at a single file, a directory, or a glob; add `--check-anchors` to also validate in-page fragments, or `--format json --output results.json` for machine-readable results.

The fastest way to wire this into a repo is the setup wizard, which detects your docs directory and writes a GitHub Actions workflow for you:

```bash
linksanity init
```

## Documentation

The full docs site covers setup, every flag, CI integration, fixing broken links, and driving linksanity from an AI agent:

- **Overview**: [Start here](https://ya8282.github.io/linksanity/)
- **Guides**: [Installation](https://ya8282.github.io/linksanity/guides/installation) · [Getting started](https://ya8282.github.io/linksanity/guides/getting-started) (`linksanity init`, baselines, first scan) · [CLI reference](https://ya8282.github.io/linksanity/guides/cli-reference) (every flag, per subcommand) · [Configuration](https://ya8282.github.io/linksanity/guides/configuration) (`linksanity.toml`) · [Output modes](https://ya8282.github.io/linksanity/guides/output-modes) (reporters, JSON schema, exit codes)
- **Recipes**: [Scanning local files](https://ya8282.github.io/linksanity/recipes/scanning-local-files) · [Crawling a site](https://ya8282.github.io/linksanity/recipes/crawling-a-site) · [Excluding links](https://ya8282.github.io/linksanity/recipes/excluding-links) · [Anchors and images](https://ya8282.github.io/linksanity/recipes/anchors-and-images) · [Baselines and incremental scans](https://ya8282.github.io/linksanity/recipes/baselines-and-incremental) · [Fixing broken links](https://ya8282.github.io/linksanity/recipes/fixing-broken-links)
- **CI**: [GitHub Actions](https://ya8282.github.io/linksanity/ci/github-actions) · [Pre-commit hook](https://ya8282.github.io/linksanity/ci/pre-commit) · [Issue reporting](https://ya8282.github.io/linksanity/ci/issue-reporting)
- **AI agents**: [Driving linksanity from an agent](https://ya8282.github.io/linksanity/agents) (JSON schemas, repair loop, MCP tool definition, library usage)
- **Reference**: [Internals](https://ya8282.github.io/linksanity/internals) (how it works, contributing) · [Troubleshooting](https://ya8282.github.io/linksanity/troubleshooting)

## License

MIT

## Contributing

See [CONTRIBUTING.md](https://github.com/ya8282/linksanity/blob/main/CONTRIBUTING.md) for the dev setup, test/lint commands, and PR checklist.
