---
title: Anchors and Images
sidebar_position: 4
---

Two opt-in flags check more than a link's bare reachability: `--check-anchors` validates the fragment after a `#`, and `--check-images` extends checking to image targets, not just links.

## `--check-anchors`

```bash
# Validate anchor fragments too
linksanity scan ./docs/ --check-anchors
```

Off by default, available on `scan`, `fix`, and `crawl`.

**How a local target anchor is resolved.** For a same-page fragment (`#section`) or a relative link with a fragment (`./guide.md#section`), linksanity first resolves the target file the normal way — same rules as any internal link, including [`--link-style`](../guides/configuration.md) if you've set it — then reads that file and extracts its real anchors: GitHub-style heading slugs for `.md`, target names for `.rst`, and `id` attributes for `.html`/`.htm` (only `id=`, so a legacy `<a name="foo">` anchor is reported broken). The fragment has to match one of those or the link is reported `broken`. AsciiDoc, MDX, notebook, and DocBook targets don't get this extraction, so a fragment link into one of those formats is always reported broken once `--check-anchors` is on.

**What happens for a fragment on a remote page.** Under `scan` and `fix`, an external URL with a fragment (`https://example.com/page#section`) is checked the same way as any other external link: linksanity confirms the page itself is reachable, but it never fetches and parses that page's HTML to see whether an element with id `section` actually exists on it. A 200 response is enough to mark it `ok` — the fragment is not verified.

`crawl` is the exception, and only for pages it actually visits: once `--check-anchors` is on and the linked page is on the same domain being crawled, linksanity checks the fragment against that page's real DOM element ids after crawling it, and reports `broken` if there's no match. If the target page hasn't been crawled yet — outside `--max-pages`, for instance — the anchor is reported `skipped` with a note rather than guessed either way. A fragment on a page outside the crawled domain is still only checked for reachability, same as `scan`.

## `--check-images`

```bash
# Also validate <img src> / ![]() targets, not just links
linksanity scan ./docs/ --check-images
```

Off by default. Extends the same broken/redirect checking to image targets — `<img src>` in HTML and `![]()` in Markdown — using the same resolution and reporting as a regular link.

`--check-images` exists on `scan` and `fix` only. `crawl` has no `--check-images` flag, and passing it to `crawl` exits `2` with `No such option`.

**The trap:** `check_images` is still parsed out of `linksanity.toml` regardless of which subcommand runs — `load_config` doesn't know or care that `crawl` has no matching flag. So `check_images = true` in your config file has no effect when you run `crawl`: no warning, no error, the field is silently read and then never acted on. See [Configuration](../guides/configuration.md) for this trap and the other fields that behave the same way.
