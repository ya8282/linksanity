# Contributing to linksanity

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Only needed if you're working on the playwright-based checker itself:

```bash
pip install -e ".[dev,browser]"
playwright install chromium
```

## Running tests

```bash
pytest                    # all tests
pytest tests/unit/        # unit tests only (no browser)
pytest tests/integration/ # integration tests (browser optional)
```

## Running the gate

Setup above installs `dev` only, not `browser` — that matches the project's
own `.venv` and CI's `test` job, so the 6 playwright skips below are the
normal state, not a broken run.

The gate is `pytest -x -q`, run from the repository root with that dev-only
install; this is exactly what CI's `test` job runs. If you use `uv` instead:
run `uv sync --extra dev` once, then `uv run pytest -x -q` is equivalent —
plain `pytest` above is canonical since it's what Setup and CI both use.

Expected: **1070 passed, 6 skipped**, coverage **87.07%** (floor: 80%, set in
`pyproject.toml`). The 6 skips are the playwright-dependent tests, skipped
because `browser` isn't installed by default, not because anything is broken.
`mypy linksanity/` and `ruff check linksanity/ tests/ scripts/` (CI's lint
scope — a bare `ruff check .` additionally lints `pyproject.toml`, and is not
the gate) must both be clean.

## Code quality

```bash
ruff check linksanity/ tests/ scripts/ --fix   # lint + auto-fix
mypy linksanity/                               # type check (strict mode)
```

Both must pass before opening a PR.

## Guidelines

- Follow the existing code style (ruff-enforced)
- New features need unit tests; new checkers/parsers need integration tests
- All public functions must have type annotations
- `GITHUB_TOKEN` must never be accepted as a CLI argument — env only
- Never write to disk unless `--output`, `--report`, or `--github-issue` is passed

## Pull requests

1. Fork and create a branch from `main`
2. Write tests for your change
3. Run `pytest`, `ruff check`, and `mypy` — all must pass
4. Open a PR with a short description of what changed and why

## Reporting bugs

Open an issue at https://github.com/ya8282/linksanity/issues with:
- Python version
- Command you ran
- Expected vs. actual output
