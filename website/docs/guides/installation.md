---
title: Installation
sidebar_position: 1
---

```bash
pip install linksanity
```

For JS-rendered pages (Playwright headless browser):

```bash
pip install "linksanity[browser]"
playwright install chromium
```

Requires Python 3.11+.

The browser install is only needed for [crawl mode](/guides/getting-started) or scan's `--js-domains` flag — a plain `linksanity scan` does not launch a browser.

**From source:**

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
pip install -e ".[dev,browser]"
playwright install chromium
```
