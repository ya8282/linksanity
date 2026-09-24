# linksanity 🏀

[![PyPI](https://img.shields.io/pypi/v/linksanity.svg)](https://pypi.org/project/linksanity/)

Detect broken links and redirects in live deployed sites or source files. Don't let dead URLs leave you hanging on the rim: linksanity keeps your documentation or web content game flawless, so you never drop the ball on your readers.

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

It can also crawl the rendered pages on your site.

## Prerequisites

- Requires Python 3.11+.
 
## Install

```bash
pip install linksanity
```

If you intend to check JS-rendered pages, install the Playwright headless browser:

```bash
pip install "linksanity[browser]"
playwright install chromium
```

Pass `--stealth` to `scan`/`crawl` to patch the common headless-Chromium fingerprints (`navigator.webdriver`, plugins, languages, etc.) that some sites use for bot detection. It only helps against fingerprint-based checks — it does not help against IP-reputation-based bot walls (iso.org is a confirmed example of the latter).

## Quick start

For a source file scan, run the following command, replacing `DOCS_DIR` with the path to your documentation source file directory:

```bash
$ linksanity scan DOCS_DIR
```

Sample output:

```bash
DOCS_DIR/api/guide.md
  BROKEN    line   12  ./missing.md — file not found
  REDIRECT  line   45  https://old.example.com → https://new.example.com
  BLOCKED   line   78  https://example.com/page [403]

ok=38   broken=1   redirect=1   blocked=1   skipped=0
```

Exit code `0` means every link is clean; `1` means at least one broken or redirected link was found — plug that straight into CI. `BLOCKED` does not affect the exit code: a blocked link means the request was refused (401/403), not that the resource is confirmed gone. Point it at a single file, a directory, or a glob; add `--check-anchors` to also validate in-page fragments, or `--format json --output results.json` for machine-readable results.

The fastest way to wire this into a repo is the setup wizard, which detects your docs directory and writes a GitHub Actions workflow for you:

```bash
linksanity init
```

## License

MIT

## Contributing

See [CONTRIBUTING.md](https://github.com/ya8282/linksanity/blob/main/CONTRIBUTING.md) for the dev setup, test/lint commands, and PR checklist.
