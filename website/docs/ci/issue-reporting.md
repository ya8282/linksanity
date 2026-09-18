---
title: Issue Reporting
sidebar_position: 3
---

Two flags surface failures beyond the scan's own exit code: `--github-issue` for a persistent tracking issue, and `--annotations` for inline GitHub Actions annotations.

## `--github-issue` and `--repo`

Use `--github-issue` when you want failing links (broken, checker errors, or redirect loops) surfaced as a trackable GitHub Issue rather than just a failed CI run. It creates or updates a single issue titled `[linksanity] N failing link(s) found`, refreshing both the title's count and the body's link table on every run, so the team has a persistent record to triage — not just a red check mark that disappears on the next push.

linksanity finds its existing issue by scanning up to 1000 open issues, most-recently-updated first; on a repo with more open issues than that, it warns on stderr and may open a second issue instead of updating the first.

### When to use it

- **Scheduled runs** — a weekly cron job catches link rot that crept in after your last merge. linksanity creates or updates the issue while links are failing, and on the next clean run comments that the links now resolve and closes it — no need to close it yourself.
- **Repos without branch protection** — if broken links won't block a PR merge, an issue is the only signal that survives past the CI run.
- **Large docs sites** — when dozens of links break at once (e.g. a domain migration), a single issue is easier to triage than scrolling through CI logs.

### When you don't need it

- PRs where branch protection already blocks the merge on failure — a failed job is sufficient.
- Local runs and one-off checks.

### Setup

```bash
export GITHUB_TOKEN=ghp_...
linksanity scan ./docs/ --github-issue --repo owner/repo
```

`GITHUB_TOKEN` is read from the environment only — never pass it as a CLI flag or store it in a file. In GitHub Actions, use the built-in token:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The workflow job also needs `issues: write` permission:

```yaml
permissions:
  contents: read
  issues: write
```

See [GitHub Actions](./github-actions.md) for a full workflow step wiring this up on `if: failure()`.

## `--annotations`

Pass `--annotations` (or rely on its default, which auto-detects CI and enables itself inside GitHub Actions) to emit `::error::`/`::warning::` workflow commands for each failing or redirected link, so failures show up inline on the diff view without downloading an artifact. `--no-annotations` disables it explicitly. See the [CLI reference](../guides/cli-reference.md) for the full flag table.

### Security note: error text and newline injection

A `::error::`/`::warning::` workflow command is just a line of text on stdout with a specific prefix — GitHub parses whatever comes after it up to the next newline as that annotation's message. The `error` field on a link result frequently comes from `str(exc)` on an exception raised while fetching third-party web content, and Playwright exceptions in particular are routinely multi-line. If that text is written into an annotation line without collapsing embedded carriage returns and newlines, a page under test could plant a line break inside its own error text and forge a second, attacker-controlled `::error::` annotation that GitHub renders as if linksanity emitted it itself.

As of today, linksanity's own annotations reporter (`linksanity/reporters/github_annotations.py`) does sanitise this correctly: its `_esc` helper escapes `%`, `\r`, and `\n` using GitHub's official workflow-command escape sequences (`%25`, `%0D`, `%0A`) before any error text is written into an annotation line, so a CR/LF embedded in an exception message cannot break out of the line and cannot forge a second annotation. This applies both to the message text and to annotation properties like `file=`, which get the same escaping plus `,`/`:` handling.

The composite action's own annotation step (in `action.yml`, used when running via the [composite action](./github-actions.md#option-a-the-composite-action) rather than the raw CLI) builds its `::error::` lines with `jq` from the JSON results file and applies the equivalent collapse — `gsub("[\r\n]+"; " ")` — to the URL, source file, and detail fields before formatting the line, for the same reason.

Both are sanitised as of this writing. If you find a code path that formats result text into a GitHub Actions annotation or shell command without collapsing `\r`/`\n` first, treat it as a security bug, not a cosmetic one.
