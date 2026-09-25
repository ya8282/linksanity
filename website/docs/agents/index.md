---
title: AI Agents
sidebar_position: 1
---

linksanity is designed to be driven by an agent, not only by a human at a terminal — every subcommand emits structured JSON and a meaningful exit code so an agent can act on results without screen-scraping console text. That's the differentiator over comparable link checkers, which mostly assume a human is reading the output.

## JSON output schema

```bash
linksanity scan ./docs/ --format json --output results.json
```

Each item in the output array has:

```json
[
  {
    "source_file": "docs/guide.md",
    "line": 42,
    "cell": null,
    "url": "https://example.com/old",
    "link_type": "external",
    "status": "redirect",
    "http_code": 200,
    "resolved_url": "https://example.com/new",
    "error": null,
    "redirect_chain": ["https://example.com/old", "https://example.com/new"],
    "redirect_codes": [301]
  }
]
```

All eleven keys are always present — the JSON reporter emits a fixed dict shape, never a partial one. `cell`, `resolved_url`, `redirect_chain`, and `redirect_codes` are `null` when they don't apply; `link_type` is always a string.

| Key | Meaning |
|---|---|
| `source_file` | Path to the file the link was found in |
| `line` | Line number the link appears on |
| `cell` | Notebook cell index for `.ipynb` sources; `null` otherwise. **`line` is relative to the cell, not the file** |
| `url` | The link target as written in the source |
| `link_type` | `"external"`, `"internal"`, `"anchor"`, `"external_anchor"`, or `"non_http_scheme"` |
| `status` | `"ok"`, `"broken"`, `"redirect"`, `"too_many_redirects"`, `"skipped"`, or `"error"` |
| `http_code` | Final HTTP status, or `null` for links that were never fetched |
| `resolved_url` | Final URL after redirects; `null` when there was no redirect |
| `error` | Error message when `status` is `"error"`; `null` otherwise |
| `redirect_chain` | Every URL in the chain, original first; `null` unless an HTTP redirect response was actually received, and also `null` in the rare case where a hop's status code couldn't be determined (chain and codes are always `null` together, never one without the other, so a code is never guessed) |
| `redirect_codes` | The status code of each hop. Lengths differ from `redirect_chain`: `redirect_chain` holds N+1 entries (every hop plus the final URL), `redirect_codes` holds N — don't zip them naively |

`status` is the field to check for pass/fail: `"broken"`, `"error"`, and `"too_many_redirects"` are the three values that make the process exit `1`. `"ok"`, `"redirect"`, and `"skipped"` do not.

This JSON schema is stable and additive across releases — new keys may be added, but none of the eleven above will be renamed or removed. Build integrations against this contract rather than against any particular reporter.

See [Output Modes](../guides/output-modes.md) for the full reporter reference, including CSV and Markdown output.

## Repair loop

`linksanity fix --format json` emits fix proposals rather than link results, which lets an agent apply the mechanical repairs and escalate only the judgment calls:

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

The loop:

1. `linksanity fix ./docs/ --format json --output fixes.json` — exit `0` means nothing to fix, and you're done.
2. Apply the safe ones: `linksanity fix ./docs/ --write`.
3. Escalate the rest. Every proposal with `auto_applicable: false` is a decision, not a defect: which of two `config.md` files was meant, whether a 302 is permanent enough to bake in, whether an archive snapshot is an acceptable substitute for a dead link. Present `old_url`, `new_url`, and `detail`, and let the human choose.
4. Re-run `linksanity scan ./docs/` to confirm the fixes landed — exit `1` means broken links remain, `0` means the tree is clean.

An example prompt for step 3:

> These links are broken and I couldn't repair them safely. For each one, tell me which replacement to use, or say "leave it":
> `{paste the auto_applicable: false proposals}`

Two things worth building into an agent that drives `--write`:

- **Commit first.** `--write` refuses on a dirty tree by design. Don't reach for `--force` to get around that — the guard is what makes the resulting `git diff` reviewable.
- **Show the diff.** `fix` without `--write` is a safe read-only preview; use it to let a human approve before you write.

See [Fixing broken links](../recipes/fixing-broken-links.md) for the full fix workflow, including safety guarantees and format support.

## Python subprocess usage

Use this when you want to drive linksanity as an external process — for example, from a non-Python agent, or to isolate the scan in its own process. If you're calling from Python and don't need process isolation, `scan_paths` (see "Use as a library" below) is simpler than parsing subprocess output.

`result.returncode` is the fast path: check it before touching the file. If it's `2`, an operational error occurred — read `result.stderr` for the error message rather than trying to parse the output file.

```python
import json
import subprocess

result = subprocess.run(
    ["linksanity", "scan", "./docs/", "--format", "json", "--output", "results.json"],
    capture_output=True,  # --output writes the file directly, so stdout is empty; stderr carries error messages
    text=True,
)

if result.returncode == 2:
    raise RuntimeError(f"linksanity operational error: {result.stderr.strip()}")

with open("results.json") as f:
    links = json.load(f)

# result.returncode == 1 means broken links exist; iterate to act on them
broken = [r for r in links if r["status"] == "broken"]
```

## Use as a library

For Python callers that want results in-process instead of shelling out, `linksanity.scan_paths` wraps the same scan pipeline the CLI uses and returns a plain list of `LinkResult` — no asyncio required:

```python
from linksanity import scan_paths, LinkStatus

results = scan_paths(["docs/"], check_anchors=True)

broken = [r for r in results if r.status == LinkStatus.BROKEN]
for r in broken:
    print(f"{r.source_file}:{r.line} -> {r.url}")
```

For `.ipynb` sources, `r.line` is relative to the cell, not the file — use `r.cell` (the cell index, `None` for non-notebook sources) alongside it if you need a file-wide position.

Pass a `Config` (from `linksanity.load_config` or constructed directly) via the `config=` keyword for anything beyond `check_anchors`, e.g. `--workers`/`--timeout` equivalents.

Note: unlike the `linksanity scan` CLI command, `scan_paths(config=None)` does **not** auto-discover a `linksanity.toml` by walking up from the current working directory — it uses bare `Config()` defaults. Call `load_config()` yourself and pass it as `config=` if you want the CLI's config-file discovery behavior.

The full public API, all importable directly from `linksanity`: `Config`, `ConfigError`, `LinkResult`, `LinkStatus`, `LinkType`, `__version__`, `load_config`, and `scan_paths`.

## MCP tool definition

Register linksanity as a tool so an AI agent can call it on demand:

```json
{
  "name": "check_links",
  "description": "Scan documentation files for broken links. Returns structured JSON. Exit code 1 means broken links were found.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "paths": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Files or directories to scan"
      },
      "skip_urls_file": {
        "type": "string",
        "description": "Path to a file listing URLs to skip (optional)"
      }
    },
    "required": ["paths"]
  }
}
```

Invoke it in your MCP server by shelling out to `linksanity scan <paths> --format json --output /tmp/results.json` and returning the parsed JSON. In other words, your tool handler spawns the `linksanity` CLI as a child process, waits for it to finish writing the results file, then reads and returns that JSON — the CLI itself is the stable interface, not linksanity's internal Python modules.

## Claude Code tool call

If you use Claude Code, you can invoke linksanity directly from the Claude CLI:

```
! linksanity scan ./docs/ --format json --output results.json
```

Then ask Claude to interpret the output:

```
Read results.json and summarise which links are broken and why they might have rotted.
```
