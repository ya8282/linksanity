"""Tests for GitHub Actions annotations wiring in the CLI (Task 36)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import _annotations_enabled, app
from linksanity.config import Config

runner = CliRunner()

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


# ── _annotations_enabled truth table ────────────────────────────────────────
#
# Inputs crossed: config.annotations (None/True/False), GITHUB_ACTIONS env
# (unset/"false"/"true"), config.format (console/json/csv), config.output
# (None/set).

class TestAnnotationsEnabledExplicitFlag:
    """config.annotations set (not None) always wins, regardless of env/format/output."""

    def test_explicit_true_wins_with_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        cfg = Config(annotations=True, format="console", output=None)
        assert _annotations_enabled(cfg) is True

    def test_explicit_true_wins_with_json_bare_stdout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        cfg = Config(annotations=True, format="json", output=None)
        assert _annotations_enabled(cfg) is True

    def test_explicit_false_wins_with_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=False, format="console", output=None)
        assert _annotations_enabled(cfg) is False

    def test_explicit_false_wins_with_output_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=False, format="json", output="out.json")
        assert _annotations_enabled(cfg) is False


class TestAnnotationsEnabledAutoDetect:
    """config.annotations is None — falls through to GITHUB_ACTIONS + suppression rule."""

    def test_env_unset_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        cfg = Config(annotations=None, format="console", output=None)
        assert _annotations_enabled(cfg) is False

    def test_env_false_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "false")
        cfg = Config(annotations=None, format="console", output=None)
        assert _annotations_enabled(cfg) is False

    def test_env_true_console_format_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="console", output=None)
        assert _annotations_enabled(cfg) is True

    def test_env_true_json_bare_stdout_suppressed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="json", output=None)
        assert _annotations_enabled(cfg) is False

    def test_env_true_csv_bare_stdout_suppressed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="csv", output=None)
        assert _annotations_enabled(cfg) is False

    def test_env_true_json_with_output_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="json", output="out.json")
        assert _annotations_enabled(cfg) is True

    def test_env_true_csv_with_output_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="csv", output="out.csv")
        assert _annotations_enabled(cfg) is True

    def test_env_true_console_with_output_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        cfg = Config(annotations=None, format="console", output="out.txt")
        assert _annotations_enabled(cfg) is True


# ── scan() CLI wiring ───────────────────────────────────────────────────────

class TestScanAnnotationsWiring:
    def test_no_env_no_flag_no_annotation_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert "::error " not in result.output

    def test_explicit_flag_fires_without_ci_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f), "--annotations"])
        assert "::error " in result.output
        assert "missing.md" in result.output

    def test_no_annotations_flag_suppresses_even_in_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f), "--no-annotations"])
        assert "::error " not in result.output

    def test_auto_detect_fires_in_ci_console_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert "::error " in result.output

    def test_auto_detect_suppressed_for_bare_json_stdout_in_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f), "--format", "json"])
        assert "::error " not in result.output
        # And the JSON must still be valid — no annotation lines leaked in
        import json

        data = json.loads(result.output)
        assert data[0]["status"] == "broken"

    def test_auto_detect_enabled_for_json_with_output_file_in_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        out = tmp_path / "out.json"
        result = runner.invoke(app, ["scan", str(f), "--format", "json", "--output", str(out)])
        # Annotations go to real stdout (not the --output file), so they show
        # up in the CLI's captured output even though --output was set.
        assert "::error " in result.output
        # The output file itself must remain untouched JSON.
        import json

        data = json.loads(out.read_text())
        assert data[0]["status"] == "broken"

    def test_no_broken_links_no_annotation_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        f = tmp_path / "clean.md"
        f.write_text("# Just text, no links\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0
        assert "::error " not in result.output
        assert "::warning " not in result.output


# ── crawl() CLI wiring (flag parsing only — playwright not required) ───────

class TestCrawlAnnotationsFlagParsing:
    """crawl() requires playwright to run past its import guard, so these
    tests only verify the --annotations/--no-annotations flag is accepted
    and rejected consistently with scan(); full end-to-end firing is covered
    by the scan() tests above, which share the same _annotations_enabled()
    and _run_annotations_reporter() wiring."""

    def test_annotations_flag_does_not_break_help(self) -> None:
        result = runner.invoke(app, ["crawl", "--help"])
        assert result.exit_code == 0
        output = _ANSI_ESCAPE.sub("", result.output)
        assert "--annotations" in output
        assert "--no-annotations" in output
