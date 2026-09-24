---
title: Installation
sidebar_position: 1
---

### pip

```bash
pip install linksanity
```

For JS-rendered pages (Playwright headless browser):

```bash
pip install "linksanity[browser]"
playwright install chromium
```

### uv

```bash
uv tool install linksanity
```

For JS-rendered pages, install with the browser extra and expose Playwright's own
CLI alongside `linksanity` so `playwright install chromium` works directly:

```bash
uv tool install "linksanity[browser]" --with-executables-from playwright
playwright install chromium
```

### pipx

```bash
pipx install linksanity
```

For JS-rendered pages, install with the browser extra, then run the installed
venv's own `playwright` binary to fetch chromium — this keeps the browser
matched to the exact Playwright version `linksanity` actually uses, since
`pipx run --spec` would resolve a separate, possibly drifted install:

```bash
pipx install "linksanity[browser]"
"$(pipx environment --value PIPX_LOCAL_VENVS)/linksanity/bin/playwright" install chromium
```

Requires Python 3.11+.

The browser install is only needed for [crawl mode](./getting-started.md) or scan with `js_domains` set (via the `--js-domains` flag or `linksanity.toml`) — a plain `linksanity scan` does not launch a browser.

**From source:**

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
pip install -e ".[dev,browser]"
playwright install chromium
```
