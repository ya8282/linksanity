"""Regression tests: scan/fix must fail fast and friendly when --js-domains
(or a linksanity.toml js_domains list) is used but playwright isn't installed,
instead of crashing mid-run with a raw traceback (linksanity-cmd.2)."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import app

runner = CliRunner()


def _mock_no_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import playwright` raise ImportError, as if the extra weren't installed."""
    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)


class TestScanJsDomainsGuard:
    def test_missing_playwright_exits_friendly_no_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_no_playwright(monkeypatch)

        domains_file = tmp_path / "js_domains.txt"
        domains_file.write_text("example.com\n")
        doc = tmp_path / "doc.md"
        doc.write_text("# Just text, no links\n")

        result = runner.invoke(
            app, ["scan", "--js-domains", str(domains_file), str(doc)]
        )

        assert result.exit_code == 2
        assert "Playwright is required for --js-domains" in result.output
        assert "pip install linksanity[browser] && playwright install chromium" in result.output
        assert "Traceback" not in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_without_js_domains_playwright_not_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity check: the guard only fires when js_domains is actually set."""
        _mock_no_playwright(monkeypatch)

        doc = tmp_path / "doc.md"
        doc.write_text("# Just text, no links\n")

        result = runner.invoke(app, ["scan", str(doc)])

        assert result.exit_code == 0
        assert "Playwright is required" not in result.output


class TestFixJsDomainsGuard:
    def test_missing_playwright_exits_friendly_no_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fix has no --js-domains flag but still reads js_domains from linksanity.toml."""
        _mock_no_playwright(monkeypatch)

        config_file = tmp_path / "linksanity.toml"
        config_file.write_text('js_domains = ["example.com"]\n')
        doc = tmp_path / "doc.md"
        doc.write_text("# Just text, no links\n")

        result = runner.invoke(
            app, ["fix", "--config", str(config_file), str(doc)]
        )

        assert result.exit_code == 2
        assert "Playwright is required for --js-domains" in result.output
        assert "pip install linksanity[browser] && playwright install chromium" in result.output
        assert "Traceback" not in result.output
