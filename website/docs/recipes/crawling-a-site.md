---
title: Crawling a Site
sidebar_position: 2
---

`linksanity crawl` checks links on a **deployed** site by following its pages with a headless browser, rather than parsing local source files. Use it to test a site after it's built and published — [Scanning Local Files](/recipes/scanning-local-files) covers checking the source instead.

## Prerequisite: Playwright

`crawl` refuses to run without Playwright installed:

```bash
pip install "linksanity[browser]"
playwright install chromium
```

Missing it exits `2` with a message telling you to install it before continuing. See [Installation](/guides/installation) for the full setup, including the from-source variant.

## Crawl a live site

```bash
# Crawl up to 500 pages (default)
linksanity crawl https://docs.example.com

# Cap total pages crawled
linksanity crawl https://docs.example.com --max-pages 50
```

**`--max-pages` is a page budget, not a depth limit.** It caps the total number of pages visited across the whole crawl — it does not limit how many links deep the crawl follows. The crawl runs breadth-first in batches (sized by `--playwright-workers`) and simply stops once it has visited `--max-pages` pages, however many hops that took to reach. There is no separate flag to limit crawl depth.

## `--playwright-workers`

```bash
# Run more browser sessions concurrently to crawl faster
linksanity crawl https://docs.example.com --playwright-workers 4
```

Max concurrent Playwright browser sessions used to load same-domain pages. Default is 2. This is separate from `--workers`, which caps concurrent plain HTTP checks of external links found on those pages.

## `--block-analytics`

```bash
linksanity crawl https://docs.example.com --block-analytics
```

Blocks and ignores requests to common analytics/tracking domains in the browser, and folds those domains into the effective ignore set so they're also skipped as external links.

## `--ignore-domains`

```bash
# Ignore external domains you don't control
echo "internal.corp.example.com" > ignore.txt
linksanity crawl https://docs.example.com --ignore-domains ignore.txt
```

Takes a file, one domain per line — see [Excluding Links](/recipes/excluding-links) for the file format and matching rules, which are shared with `scan`.

## `--max-redirects`

```bash
linksanity crawl https://docs.example.com --max-redirects 5
```

Max redirect hops before a link is flagged as too-many-redirects instead of followed. Default is 10.
