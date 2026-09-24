"""Tests for the `--stealth` CLI flag: plumbing from CLI args to Config,
for both `scan` and `crawl` (linksanity-h51.6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import app
from linksanity.config import Config
from linksanity.queue import LinkQueue

runner = CliRunner()


def _write_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text("# Just text, no links\n")
    return doc


class TestScanStealthFlag:
    def test_stealth_flag_sets_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)

        captured: dict[str, Config] = {}

        async def fake_run_scan(paths: list[str], config: Config) -> LinkQueue:
            captured["config"] = config
            return LinkQueue()

        monkeypatch.setattr("linksanity.cli.run_scan", fake_run_scan)

        result = runner.invoke(app, ["scan", "doc.md", "--stealth"])

        assert result.exit_code == 0, result.output
        assert captured["config"].stealth is True

    def test_without_stealth_defaults_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)

        captured: dict[str, Config] = {}

        async def fake_run_scan(paths: list[str], config: Config) -> LinkQueue:
            captured["config"] = config
            return LinkQueue()

        monkeypatch.setattr("linksanity.cli.run_scan", fake_run_scan)

        result = runner.invoke(app, ["scan", "doc.md"])

        assert result.exit_code == 0, result.output
        assert captured["config"].stealth is False


class TestCrawlStealthFlag:
    def test_stealth_flag_sets_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("playwright", reason="playwright not installed -- skipping")

        captured: dict[str, Config] = {}

        async def fake_run_crawl(url: str, config: Config) -> LinkQueue:
            captured["config"] = config
            return LinkQueue()

        monkeypatch.setattr("linksanity.crawler.run_crawl", fake_run_crawl)

        result = runner.invoke(
            app, ["crawl", "http://example.invalid", "--stealth"]
        )

        assert result.exit_code == 0, result.output
        assert captured["config"].stealth is True

    def test_without_stealth_defaults_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("playwright", reason="playwright not installed -- skipping")

        captured: dict[str, Config] = {}

        async def fake_run_crawl(url: str, config: Config) -> LinkQueue:
            captured["config"] = config
            return LinkQueue()

        monkeypatch.setattr("linksanity.crawler.run_crawl", fake_run_crawl)

        result = runner.invoke(app, ["crawl", "http://example.invalid"])

        assert result.exit_code == 0, result.output
        assert captured["config"].stealth is False
