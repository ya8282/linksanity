# Contributing to linksanity

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/ya8282/linksanity
cd linksanity
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,browser]"
playwright install chromium
```

## Running tests

```bash
pytest                    # all tests
pytest tests/unit/        # unit tests only (no browser)
pytest tests/integration/ # integration tests (browser optional)
```

## Code quality

```bash
ruff check linksanity/ tests/ --fix   # lint + auto-fix
mypy linksanity/                      # type check (strict mode)
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
