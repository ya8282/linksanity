---
title: Fixing Broken Links
sidebar_position: 6
---

Most checkers stop at a red ✗. `linksanity fix` takes the next step: it scans, works out which breakages it can repair, and shows you a diff.

```bash
# Dry run — prints a unified diff, changes nothing
linksanity fix ./docs/

# Apply the fixes it is confident about
linksanity fix ./docs/ --write
```

**Dry run is the default. Files are only ever touched when you pass `--write`.** Running `linksanity fix ./docs/` on its own is always safe to try — it prints a diff of what it would change and stops there. There is no other flag or combination of flags that applies a change; `--write` is the only door.

## What it will and won't fix

| Class | Trigger | Confidence | Applied by `--write`? |
|---|---|---|---|
| `redirect` | Every hop in the chain is a 301 or 308 | High — the server itself declares the new canonical URL | **Yes** |
| `moved_file` | A broken relative link whose basename matches exactly one file in the corpus | Medium — inferred from the file tree | **Yes**, unique match only |
| `wayback` (only built with `--wayback`) | A dead external link (404/410), or one that failed outright — DNS failure, connect timeout, TLS error — with an Internet Archive snapshot | Low — a judgment call | **Never** — suggested only |

`redirect` and `moved_file` proposals are always built from a scan. `wayback` proposals are opt-in: pass `--wayback` or none are generated.

Anything ambiguous is reported, never guessed:

- A **temporary** redirect (302/307, or a chain mixing permanent and temporary hops) is only a suggestion. Pass `--redirects all` if you want those applied too.
- **Two files** with the same basename mean no auto-fix — both are listed so you can pick.
- **No basename match** falls back to close-name suggestions.
- An **archive snapshot** is never substituted for you, `--wayback` or not.

## Safety

Rewriting source files is the one thing `fix` does that a re-run can't undo, so:

- **Dry run by default** — `--write` is opt-in, as above.
- **Clean tree required** — `--write` refuses if the files it would rewrite have uncommitted changes, which it could otherwise clobber. Commit or stash first, or pass `--force` to write anyway. Outside a git repo it proceeds with a note instead of refusing, since there's no tree state to check.
- **Line-scoped edits** — only the exact line the link was found on is touched, and a URL that is a prefix of a longer URL on that line is left alone (`http://old.example.com/x` won't match inside `http://old.example.com/x/deeper`).
- **Atomic writes** — a crash mid-fix can't leave a truncated file.
- **Stale scans are safe** — if a file changed since the scan and the URL is no longer on its recorded line, that fix is skipped with a warning rather than applied blind.

`--write` on a dirty tree exits `2`, the same code as any other operational error (bad arguments, invalid config, a missing dependency, or a failed write to `--output`/a domains file) — check the exit code, not just whether files changed, when scripting this.

## Format support

`fix` rewrites `.md`, `.rst`, `.html`, and `.htm` only — a narrower set than `scan`, which also parses AsciiDoc, MDX, Jupyter notebooks, and DocBook. Links found in those other formats are still reported as proposals, but as suggestions you apply yourself; `--write` never touches them.

`.ipynb` is deliberately excluded even though `scan` reads it: a notebook's recorded line numbers are relative to a cell, not the file, so a file-level rewrite would corrupt an unrelated line.

`--format` is also narrower on `fix` than on `scan`/`crawl`: only `console` (the default diff view) or `json` (proposals). Passing `--format csv` to `fix` exits `2` with `--format must be one of: console, json` — `csv` is a `scan`/`crawl`-only format.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Nothing to fix |
| `1` | Proposals exist (dry run), or were applied (`--write`) |
| `2` | Operational error: bad arguments, an invalid config, a missing dependency (Playwright, when `js_domains` is set in the config), or a failed write to `--output` or a domains/skip file -- or `--write` refused a dirty working tree |

A `fix` exit of `1` is not a failure signal by itself — it just means there was something to report. Check `auto_applicable` in the JSON output below, or read the diff, to see what actually happened.

## JSON output: fix proposals

`fix --format json` emits fix proposals, not link results — a different shape from `scan --format json` (see [Output Modes](../guides/output-modes.md) for that schema):

```bash
linksanity fix ./docs/ --format json --output fixes.json
```

```json
[
  {
    "source_file": "docs/a.md",
    "line": 12,
    "old_url": "http://old.example.com/x",
    "new_url": "https://new.example.com/x",
    "kind": "redirect",
    "auto_applicable": true,
    "detail": "301 → https://new.example.com/x"
  }
]
```

| Key | Meaning |
|---|---|
| `kind` | `"redirect"`, `"moved_file"`, or `"wayback"` |
| `auto_applicable` | `true` = linksanity will apply it under `--write`. `false` = it needs a human |
| `detail` | Why this was proposed — worth surfacing verbatim when escalating |

## The repair loop

1. `linksanity fix ./docs/ --format json --output fixes.json` — exit `0` means nothing to fix, and you're done.
2. Apply the safe ones: `linksanity fix ./docs/ --write`.
3. Escalate the rest. Every proposal with `auto_applicable: false` is a decision, not a defect: which of two same-named files was meant, whether a 302 is permanent enough to bake in, whether an archive snapshot is an acceptable substitute for a dead link. Present `old_url`, `new_url`, and `detail`, and let a human choose.
4. Re-run `linksanity scan ./docs/` to confirm the fixes landed.

Commit or stash before step 2, rather than reaching for `--force` to get around the dirty-tree refusal — the guard is what makes the resulting `git diff` reviewable.
