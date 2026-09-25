# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-24

### Added

- **`LinkStatus.BLOCKED`** — HTTP 401/403 responses are now classified as
  `BLOCKED` instead of `BROKEN`. **Behavior change:** `BLOCKED` does not
  count toward CI exit codes or `FAILING_STATUSES` by default, unlike a 404.
  If you were relying on "any 4xx fails the build," you will now see fewer
  failures specifically for 401/403 responses — those links still show up in
  reports, they just no longer fail CI on their own.
- **`--stealth`** flag (`scan`, `crawl`) — patches common headless-Chromium
  fingerprints to reduce false-positive `BLOCKED` results from
  fingerprint-based bot detection; does not help against IP-reputation-based
  bot walls. See README for details.
- **Documentation site** published at
  [ya8282.github.io/linksanity](https://ya8282.github.io/linksanity/) —
  installation, getting started, CLI reference, configuration, recipes, CI
  integration, driving linksanity from an agent, internals, and
  troubleshooting, deployed via GitHub Pages. The README is trimmed to an
  at-a-glance Features list plus a pointer at the site.
- **Config key warnings** — `load_config` now warns on stderr about
  `linksanity.toml` keys it does not read, so a misspelled key or a stray
  `[tool.linksanity]` table no longer succeeds silently. `output`, `report`,
  `github_issue`, and `github_repo` are TOML-only-excluded by design and are
  expected to trigger this warning too — that is not a bug.
- Docs: `uv` and `pipx` install methods are now documented alongside `pip`,
  including the `browser` extra.

### Changed

- Console and markdown `REDIRECT` lines no longer repeat the original URL
  at the start of the redirect chain, and end with the hop codes (e.g.
  `[301]`, `[301, 302]`) instead of the final response code; that suffix is
  omitted when no hop codes are present, and the URL-only line printed when
  no chain was recorded no longer carries a code at all. The
  `--annotations` redirect warning says `redirect [301]` when hop codes are
  recorded, instead of `HTTP 200`. **Behavior change:** if you parse console, markdown, or
  annotation text for a redirect's code, update to read the hop-code list
  instead of a single trailing code. JSON and CSV output are unchanged.
- The GitHub issue reporter now comments on and closes the standing
  link-rot issue on any clean `--github-issue` run, instead of doing
  nothing. Docs show how to gate the CI step to
  `if: ${{ !cancelled() && github.event_name == 'schedule' }}` so it is only
  the scheduled run that closes the issue, without firing on
  `push`/`pull_request` runs. **Behavior change:** a step still gated on
  `if: failure()` will not pick up this close — see the GitHub Actions docs
  for the updated gating.
- **Exit code 3** for a failed `--github-issue` report (missing
  `GITHUB_TOKEN`, a non-2xx GitHub API response, etc.). **Behavior change:**
  previously exited 1, indistinguishable from "broken links found." A CI
  step can now tell "we could not tell you" apart from "nothing to tell
  you." Token and `github_repo` validation also now run before the
  clean-run check rather than after it, so **a clean `--github-issue` run
  with no `GITHUB_TOKEN` set (or an invalid `github_repo`) now exits 3
  instead of silently exiting 0** — this can surface on local runs or
  PR/push jobs that set `--github-issue` without a token.

### Fixed

- `init --paths`: reject absolute paths and `..` components, which
  previously passed validation but produced a workflow whose `paths:` value
  matches nothing (or escapes the checkout) on the runner
- `init --paths`: more precise refusal messages — names the actual
  offending character instead of a generic list, calls out glob
  metacharacters beyond `*` (`?`, `!`, `+`, brackets), explains that paths
  are literal strings rather than globs, and diagnoses an all-slash or
  empty value instead of falling through to the generic message
- `init --dry-run` no longer refuses on a workflow or baseline file that
  already exists — it was never going to write to either
- `init`'s cost estimate names the pinned `linksanity-action` version
  instead of claiming "CI installs the latest release"
- `init` and the scanner no longer descend into *any* directory symlink
  (self-referential or not) — a symlinked subdirectory inside a scanned or
  probed tree is no longer walked; the symlinked file entries themselves are
  still counted/scanned. Previously a symlink loop inflated a probe
  directory's file count and could loop. **Behavior change:** a docs tree
  that reaches other content only through a symlinked directory will see
  fewer files proposed by `init` and scanned by `scan`/`fix` than before
- The scanner now prunes vendored and dot directories the same way
  `init`'s detection does, so a directory `init` proposed is not then
  scanned in full
- Root-relative links (e.g. `/guides/output-modes`) now resolve against the
  scan root instead of the filesystem root
- Each scanned pattern gets its own root instead of one corpus-wide common
  path, fixing false matches when unrelated trees were scanned together
  (e.g. `scan /tmp /usr`)
- A baselined link that degrades to a worse status (e.g. a suppressed
  redirect that becomes broken) now re-fails instead of staying suppressed
- Config: a bool value for an integer key (e.g. `workers = true`) is now
  rejected instead of silently becoming `1`
- Config: a non-integral float for an integer key (e.g. `workers = 2.5`) is
  now rejected instead of being silently truncated
- Domains file: an indented `#` line is now treated as a comment, matching
  a flush-left one
- Dedupe now keys source-dependent links (root-relative, anchor, same
  relative text under different directories) on the resolved base rather
  than the raw URL, so they are all checked instead of collapsing into one
  result; the fixer no longer proposes the same fix multiple times for a
  URL that yields several results

## [0.3.0] - 2026-08-30

### Added

**New `init` command** — a setup wizard that scaffolds CI link checking
into an existing repository.

- Detects documentation paths (Markdown, reStructuredText, HTML, and the
  other supported source formats) under the current directory and proposes
  a `paths:` list, or accepts `--paths` to skip detection for a
  non-interactive run
- Runs a real, timed link check locally to produce a measured cost
  estimate (billed CI minutes) before anything is written, so the estimate
  reflects the actual corpus rather than a guess
- Generates a `.github/workflows/<name>.yml` (default `linkcheck.yml`)
  wired to `ya8282/linksanity-action@v1`
- Writes an optional baseline file when existing breakage is found, so CI
  starts from "no new breakage" rather than failing immediately
  (`--no-baseline` to skip)
- `--dry-run` prints the generated files without writing them; `--yes`
  runs non-interactively (requires `--paths`)
- Never touches git: no `git init`, `git add`, or `git commit` — the wizard
  only detects, measures, and writes files

**`action-repo` pairing.** The workflow `init` generates includes a
`baseline:` input on `ya8282/linksanity-action`. That input requires
`ya8282/linksanity-action@v1` at `v1.0.0` or later — an older pinned copy
of the action does not recognize `baseline:` and fails the job with an
unknown-input error. `v1` and `v1.0.0` of the action both now include
`baseline:` support, so pinning `@v1` (floating) or `@v1.0.0` (pinned) is
safe.

### Dependencies

- `pyyaml` added as a test-only dev dependency (used to validate the
  workflow YAML `init` generates). Runtime dependencies are unchanged —
  linksanity still ships zero new runtime dependencies.

## [0.2.1] - 2026-08-03

### Fixed

- Browser checker no longer reports downloadable URLs as errors. Chromium
  headless turns a PDF navigation into a download, so `page.goto()` aborted
  with "Download is starting" and every reachable `.pdf` — or any URL served
  with `Content-Disposition: attachment` — was marked broken. Both `check` and
  crawl mode now fall back to the HTTP checker for that case.

## [0.2.0] - 2026-07-30

### Added

**New `fix` subcommand** — proposes and applies repairs for broken links.

- Redirect proposals: rewrite a link to the address it already redirects to
- Moved-file resolver: find a local file that was renamed or relocated
- Wayback suggester: offer an archive.org snapshot for a dead external link
- `--write` applies fixes; without it `fix` only prints a diff
- Guards against writing into a dirty working tree unless `--force` is passed

**Five new source formats**, joining Markdown, reStructuredText, and HTML.

- MDX (`.mdx`), including JSX `href`/`to` attributes, skipping fenced code blocks
- MyST roles and directives
- Jupyter notebooks (`.ipynb`) — links in Markdown cells, with the cell number
  reported alongside the line
- AsciiDoc (`.adoc`) — `link:`/`xref:` macros and bare autolinks
- DocBook XML — `ulink`/`link`/`xref`, resolved against a corpus-wide ID index

**Anchor validation for `crawl`.** `--check-anchors` was previously `scan`-only.
It now works against a live site: same-domain `#fragment` links are collected
during the crawl and validated against the target page's element IDs once that
page has been fetched.

**GitHub Actions integration.**

- `--annotations` / `--no-annotations` emits `::error`/`::warning` annotations,
  auto-enabled when running in Actions
- Official pre-commit hook definition
- `scripts/bootstrap_linkcheck.py` scaffolds a scheduled link-check workflow
  into a target repository

**Scan controls.**

- `--offline` skips external HTTP checks and reports them as `skipped`
- `--baseline` produces diff-friendly output for tracking changes over time
- Link result caching and incremental scan (`--cache`, `--cache-ttl`,
  `--incremental`, `--since`)
- `--check-images` also validates `<img src>` and `![]()` image targets, not
  just links
- `--link-style` selects a relative-link resolution preset for built docs
  sites: `mkdocs`, `docusaurus`, or `sphinx`
- `--myst` extracts MyST `{doc}`/`{ref}` role targets from `.md` files
- Redirect chains and their status codes are captured and reported
- `--max-redirects` flags excessive redirect hops

**Library API.** `scan_paths()` is now a supported entry point for embedding
linksanity in other tools.

### Changed

- Console, JSON, CSV, Markdown, and GitHub reporters all surface the notebook
  cell number alongside the line number
- Skipped fixes report what was observed rather than an internal reason
- The fix count reported is the number actually written, not attempted

### Fixed

- `--js-domains` now fails with an actionable message when Playwright is not
  installed, instead of an `ImportError` from deep in the router
- A malformed, wrongly-typed, non-UTF-8, or unreadable `linksanity.toml` now
  exits 2 with a message naming the file, instead of a raw traceback and
  exit 1. `load_config` raises the new `linksanity.ConfigError` (a
  `ValueError` subclass, so an existing `except ValueError` still catches it)
- `scan_paths()` no longer crashes when called from a running event loop
- Parser line numbers corrected for Markdown, reStructuredText, and HTML
- Rich markup in free-text fields is escaped in the console reporter, so a URL
  containing `[` no longer corrupts output
- Scanner exception handling narrowed to `Exception`, so `CancelledError`
  propagates instead of being swallowed into a result
- The private-host guard checks the resolved address
- AsciiDoc: trailing punctuation, heading collisions, and unterminated blocks
- DocBook: `id`/`xml:id` short-circuit in `extract_ids`
- Dirty-tree guard no longer passes silently on relative paths

### Removed

- The unused `lxml` dependency

## [0.1.1] - 2026-06

Initial public release. `scan` and `crawl` over Markdown, reStructuredText, and
HTML, with Playwright-backed checking for JS-rendered pages.

[0.4.0]: https://github.com/ya8282/linksanity/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ya8282/linksanity/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/ya8282/linksanity/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ya8282/linksanity/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/ya8282/linksanity/releases/tag/v0.1.1
