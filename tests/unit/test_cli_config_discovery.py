"""Tests for linksanity.toml discovery: upward walk, the .git boundary, the
one-line stderr announcement, and --config error handling (linksanity-52c).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import _announce_config, _discover_config, app

runner = CliRunner()

# A doc with one anchor link that only breaks when check_anchors is on, so
# each test can tell from the report whether its linksanity.toml (which sets
# check_anchors = true) was actually picked up.
DOC = "# Title\n\n[link](#missing)\n"


def _write_doc(directory: Path, name: str = "doc.md") -> Path:
    doc = directory / name
    doc.write_text(DOC, encoding="utf-8")
    return doc


class TestDiscoverConfigHelper:
    """Direct unit tests of the upward-walk helper."""

    def test_found_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        monkeypatch.chdir(tmp_path)
        assert _discover_config() == cfg

    def test_found_in_parent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        sub = tmp_path / "docs" / "nested"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert _discover_config() == cfg

    def test_nearest_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = false\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        nearest = sub / "linksanity.toml"
        nearest.write_text("check_anchors = true\n")
        monkeypatch.chdir(sub)
        assert _discover_config() == nearest

    def test_git_boundary_stops_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = true\n")
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        sub = proj / "docs"
        sub.mkdir()
        monkeypatch.chdir(sub)
        assert _discover_config() is None

    def test_config_alongside_git_boundary_is_still_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The .git directory itself is the boundary, but its own directory
        is still searched before the walk stops."""
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        cfg = proj / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        sub = proj / "docs"
        sub.mkdir()
        monkeypatch.chdir(sub)
        assert _discover_config() == cfg

    def test_no_config_anywhere_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        assert _discover_config() is None


class TestScanConfigDiscoveryEndToEnd:
    def test_found_in_cwd_is_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["scan", "doc.md", "--offline"])

        assert result.exit_code == 1  # broken link found -> non-zero exit
        assert "broken=1" in result.stdout
        assert f"[linksanity] using config: {cfg}" in result.stderr

    def test_found_in_parent_from_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        _write_doc(sub)
        monkeypatch.chdir(sub)

        result = runner.invoke(app, ["scan", "doc.md", "--offline"])

        assert result.exit_code == 1  # broken link found -> non-zero exit
        assert "broken=1" in result.stdout
        assert f"[linksanity] using config: {cfg}" in result.stderr

    def test_nearest_config_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = false\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        nearest = sub / "linksanity.toml"
        nearest.write_text("check_anchors = true\n")
        _write_doc(sub)
        monkeypatch.chdir(sub)

        result = runner.invoke(app, ["scan", "doc.md", "--offline"])

        assert result.exit_code == 1  # broken link found -> non-zero exit
        assert "broken=1" in result.stdout
        assert f"[linksanity] using config: {nearest}" in result.stderr

    def test_git_boundary_stops_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = true\n")
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        sub = proj / "docs"
        sub.mkdir()
        _write_doc(sub)
        monkeypatch.chdir(sub)

        result = runner.invoke(app, ["scan", "doc.md", "--offline"])

        assert result.exit_code == 0
        assert "ok=1" in result.stdout  # anchor not checked -> not broken
        assert "[linksanity] no linksanity.toml found; using defaults" in result.stderr

    def test_no_config_anywhere_uses_defaults_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        _write_doc(empty)
        monkeypatch.chdir(empty)

        result = runner.invoke(app, ["scan", "doc.md", "--offline"])

        assert result.exit_code == 0
        assert "ok=1" in result.stdout
        assert "[linksanity] no linksanity.toml found; using defaults" in result.stderr

    def test_explicit_config_overrides_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = true\n")
        explicit = tmp_path / "other.toml"
        explicit.write_text("check_anchors = false\n")
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["scan", "doc.md", "--config", str(explicit), "--offline"]
        )

        assert result.exit_code == 0
        assert "ok=1" in result.stdout  # explicit config's check_anchors=false won
        assert f"[linksanity] using config: {explicit}" in result.stderr

    def test_explicit_missing_config_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "does-not-exist.toml"

        result = runner.invoke(
            app, ["scan", "doc.md", "--config", str(missing), "--offline"]
        )

        assert result.exit_code == 2
        assert "not found" in result.stderr
        assert str(missing) in result.stderr

    def test_announcement_is_on_stderr_and_json_output_file_is_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text("check_anchors = true\n")
        _write_doc(tmp_path)
        out = tmp_path / "out.json"
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            ["scan", "doc.md", "--offline", "--format", "json", "--output", str(out)],
        )

        assert result.exit_code == 1  # broken link found -> non-zero exit
        assert result.stdout == ""
        assert "[linksanity] using config" in result.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == "broken"

    def test_announcement_suppressed_for_bare_stdout_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare `--format json` with no --output is the agent/script pipe
        case: the announcement is suppressed outright (not merely kept off
        stdout), matching _annotations_enabled's existing Assumption 6 for
        the same scenario. See TestAnnouncementSuppression for direct
        coverage of the suppression rule itself."""
        (tmp_path / "linksanity.toml").write_text("check_anchors = true\n")
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["scan", "doc.md", "--offline", "--format", "json"])

        assert result.exit_code == 1  # broken link found -> non-zero exit
        assert result.stderr == ""
        data = json.loads(result.stdout)
        assert isinstance(data, list)


class TestAnnouncementSuppression:
    """Direct coverage of _announce_config's suppression rule: bare
    json/csv stdout (no --output) is the agent/script pipe case, and is
    suppressed outright, mirroring _annotations_enabled's Assumption 6."""

    def test_suppressed_for_bare_json_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        _announce_config(Path("linksanity.toml"), format="json", output=None)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_suppressed_for_bare_csv_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        _announce_config(None, format="csv", output=None)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_not_suppressed_for_json_with_output_file(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _announce_config(Path("linksanity.toml"), format="json", output="out.json")
        captured = capsys.readouterr()
        assert "using config" in captured.err

    def test_not_suppressed_for_console_format(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _announce_config(None, format="console", output=None)
        captured = capsys.readouterr()
        assert "no linksanity.toml found" in captured.err


class TestFixConfigDiscoveryEndToEnd:
    """`fix` shares the same discovery helper as `scan`; a light check that it
    is actually wired up, not a re-test of fix's own proposal pipeline."""

    def test_config_discovered_from_parent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("check_anchors = true\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        _write_doc(sub)
        monkeypatch.chdir(sub)

        result = runner.invoke(app, ["fix", "doc.md"])

        assert f"[linksanity] using config: {cfg}" in result.stderr

    def test_explicit_missing_config_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_doc(tmp_path)
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "does-not-exist.toml"

        result = runner.invoke(app, ["fix", "doc.md", "--config", str(missing)])

        assert result.exit_code == 2
        assert "not found" in result.stderr


class TestCrawlConfigDiscoveryEndToEnd:
    """`crawl` shares the same discovery helper; verified without a live
    crawl by stubbing linksanity.crawler.run_crawl."""

    def test_config_discovered_from_parent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("playwright", reason="playwright not installed — skipping")
        from linksanity.queue import LinkQueue

        cfg = tmp_path / "linksanity.toml"
        cfg.write_text("max_pages = 3\n")
        sub = tmp_path / "docs"
        sub.mkdir()
        monkeypatch.chdir(sub)

        async def fake_run_crawl(*_args: object, **_kwargs: object) -> LinkQueue:
            return LinkQueue()

        monkeypatch.setattr("linksanity.crawler.run_crawl", fake_run_crawl)

        # console format (not bare json/csv stdout) so the announcement isn't
        # suppressed -- see TestAnnouncementSuppression for that case.
        result = runner.invoke(app, ["crawl", "http://example.invalid"])

        assert f"[linksanity] using config: {cfg}" in result.stderr

    def test_explicit_missing_config_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("playwright", reason="playwright not installed — skipping")
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "does-not-exist.toml"

        result = runner.invoke(
            app,
            ["crawl", "http://example.invalid", "--config", str(missing)],
        )

        assert result.exit_code == 2
        assert "not found" in result.stderr
