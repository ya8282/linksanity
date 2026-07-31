"""Tests for the `fix` CLI command — argument validation, guards, exit codes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from linksanity.cli import app
from linksanity.fixer import FixKind, FixProposal

runner = CliRunner()

OLD = "http://old.example.com/x"
NEW = "https://new.example.com/x"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _proposal(source_file: str, **overrides: object) -> FixProposal:
    defaults: dict[str, object] = {
        "source_file": source_file,
        "line": 1,
        "old_url": OLD,
        "new_url": NEW,
        "kind": FixKind.REDIRECT,
        "auto_applicable": True,
        "detail": "301 → " + NEW,
    }
    defaults.update(overrides)
    return FixProposal(**defaults)  # type: ignore[arg-type]


def _patch_proposals(proposals: list[FixProposal]) -> object:
    """Stub the scan+proposal pipeline; these tests are about the CLI surface."""

    async def fake(*_args: object, **_kwargs: object) -> list[FixProposal]:
        return proposals

    return patch("linksanity.cli._collect_proposals", new=fake)


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    f = tmp_path / "a.md"
    f.write_text(f"See [docs]({OLD}) here\n", encoding="utf-8")
    return f


# ── Flag plumbing ─────────────────────────────────────────────────────────────

class TestConfigPlumbing:
    def test_flags_reach_the_scan_config(self, doc: Path, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        async def fake(
            paths: list[str], config: object, redirects: str, wayback: bool
        ) -> list[FixProposal]:
            captured.update(
                paths=paths, config=config, redirects=redirects, wayback=wayback
            )
            return []

        cache_file = tmp_path / "cache.json"
        with patch("linksanity.cli._collect_proposals", new=fake):
            result = runner.invoke(app, [
                "fix", str(doc),
                "--workers", "3",
                "--timeout", "7",
                "--retry", "1",
                "--check-anchors",
                "--check-images",
                "--link-style", "mkdocs",
                "--cache", str(cache_file),
                "--cache-ttl", "60",
                "--redirects", "all",
                "--wayback",
            ])

        assert result.exit_code == 0, result.output
        config = captured["config"]
        assert config.workers == 3           # type: ignore[attr-defined]
        assert config.timeout == 7           # type: ignore[attr-defined]
        assert config.retry == 1             # type: ignore[attr-defined]
        assert config.check_anchors is True  # type: ignore[attr-defined]
        assert config.check_images is True   # type: ignore[attr-defined]
        assert config.link_style == "mkdocs"  # type: ignore[attr-defined]
        assert config.cache_file == str(cache_file)  # type: ignore[attr-defined]
        assert config.cache_ttl == 60        # type: ignore[attr-defined]
        assert captured["redirects"] == "all"
        assert captured["wayback"] is True
        assert captured["paths"] == [str(doc)]

    def test_domain_files_reach_the_config(self, doc: Path, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        async def fake(
            paths: list[str], config: object, redirects: str, wayback: bool
        ) -> list[FixProposal]:
            captured["config"] = config
            return []

        ignore = tmp_path / "ignore.txt"
        ignore.write_text("skipme.example.com\n", encoding="utf-8")
        skip = tmp_path / "skip.txt"
        skip.write_text("https://auth.example.com/*\n", encoding="utf-8")

        with patch("linksanity.cli._collect_proposals", new=fake):
            runner.invoke(app, [
                "fix", str(doc),
                "--ignore-domains", str(ignore),
                "--skip-urls", str(skip),
            ])

        config = captured["config"]
        assert config.ignore_domains == {"skipme.example.com"}       # type: ignore[attr-defined]
        assert config.skip_urls == {"https://auth.example.com/*"}    # type: ignore[attr-defined]

    def test_defaults_are_dry_run_and_permanent_only(self, doc: Path) -> None:
        captured: dict[str, object] = {}

        async def fake(
            paths: list[str], config: object, redirects: str, wayback: bool
        ) -> list[FixProposal]:
            captured.update(redirects=redirects, wayback=wayback)
            return []

        with patch("linksanity.cli._collect_proposals", new=fake):
            runner.invoke(app, ["fix", str(doc)])

        assert captured["redirects"] == "permanent"
        assert captured["wayback"] is False


# ── Invocation errors (exit 2) ────────────────────────────────────────────────

class TestInvocationErrors:
    def test_url_argument_is_rejected(self) -> None:
        result = runner.invoke(app, ["fix", "https://example.com"])
        assert result.exit_code == 2
        assert "not URLs" in result.output

    def test_url_argument_points_at_scan_and_crawl(self) -> None:
        result = runner.invoke(app, ["fix", "http://example.com"])
        assert "scan" in result.output and "crawl" in result.output

    def test_url_mixed_with_paths_is_still_rejected(self, doc: Path) -> None:
        result = runner.invoke(app, ["fix", str(doc), "https://example.com"])
        assert result.exit_code == 2

    def test_bad_redirects_value_rejected(self, doc: Path) -> None:
        result = runner.invoke(app, ["fix", str(doc), "--redirects", "sometimes"])
        assert result.exit_code == 2
        assert "--redirects" in result.output

    def test_bad_format_rejected(self, doc: Path) -> None:
        result = runner.invoke(app, ["fix", str(doc), "--format", "xml"])
        assert result.exit_code == 2
        assert "--format" in result.output

    def test_bad_link_style_rejected(self, doc: Path) -> None:
        result = runner.invoke(app, ["fix", str(doc), "--link-style", "jekyll"])
        assert result.exit_code == 2
        assert "--link-style" in result.output


# ── Exit codes ────────────────────────────────────────────────────────────────

class TestExitCodes:
    def test_no_proposals_exits_zero(self, doc: Path) -> None:
        with _patch_proposals([]):
            result = runner.invoke(app, ["fix", str(doc)])
        assert result.exit_code == 0
        assert "nothing to fix" in result.output

    def test_no_proposals_message_is_on_stderr_not_stdout(self, doc: Path) -> None:
        # Console format is unchanged apart from the stream: no JSON, no empty
        # structure printed to a human — just the message, now on stderr.
        with _patch_proposals([]):
            result = runner.invoke(app, ["fix", str(doc)])
        assert result.exit_code == 0
        assert "nothing to fix" in result.stderr
        assert "nothing to fix" not in result.stdout
        assert result.stdout == ""

    def test_proposals_in_dry_run_exit_one(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc)])
        assert result.exit_code == 1

    def test_applied_proposals_exit_one(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert result.exit_code == 1


# ── Dry run is the default ────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_does_not_touch_the_file(self, doc: Path) -> None:
        original = doc.read_text(encoding="utf-8")
        with _patch_proposals([_proposal(str(doc))]):
            runner.invoke(app, ["fix", str(doc)])
        assert doc.read_text(encoding="utf-8") == original

    def test_dry_run_prints_a_diff(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc)])
        assert f"-See [docs]({OLD}) here" in result.output
        assert f"+See [docs]({NEW}) here" in result.output

    def test_suggestions_are_listed(self, doc: Path) -> None:
        p = _proposal(str(doc), auto_applicable=False, detail="302, use --redirects all")
        with _patch_proposals([p]):
            result = runner.invoke(app, ["fix", str(doc)])
        assert "Suggestions" in result.output
        assert "302, use --redirects all" in result.output


# ── --write ───────────────────────────────────────────────────────────────────

class TestWrite:
    def test_write_applies_the_fix(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            runner.invoke(app, ["fix", str(doc), "--write"])
        assert doc.read_text(encoding="utf-8") == f"See [docs]({NEW}) here\n"

    def test_write_reports_the_modified_file(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert str(doc) in result.output
        assert "Applied 1 fix" in result.output

    def test_write_counts_only_fixes_that_landed(self, doc: Path) -> None:
        # doc holds the URL on line 1 only; the line 2 proposal cannot apply.
        # Reporting "Applied 2" would claim a write that never happened.
        with _patch_proposals([_proposal(str(doc)), _proposal(str(doc), line=2)]):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert "Applied 1 fix" in result.output

    def test_write_never_applies_suggestions(self, doc: Path) -> None:
        original = doc.read_text(encoding="utf-8")
        p = _proposal(str(doc), auto_applicable=False)
        with _patch_proposals([p]):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert doc.read_text(encoding="utf-8") == original
        assert "No auto-applicable fixes" in result.output

    def test_write_still_shows_suggestions(self, doc: Path) -> None:
        proposals = [
            _proposal(str(doc)),
            _proposal(str(doc), auto_applicable=False, detail="needs a human"),
        ]
        with _patch_proposals(proposals):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert "needs a human" in result.output


# ── Git dirty guard ───────────────────────────────────────────────────────────

class TestDirtyTreeGuard:
    @pytest.fixture
    def repo_doc(self, tmp_path: Path) -> Path:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "T")
        f = tmp_path / "a.md"
        f.write_text(f"See [docs]({OLD}) here\n", encoding="utf-8")
        _git(tmp_path, "add", "a.md")
        _git(tmp_path, "commit", "-q", "-m", "first")
        return f

    def test_clean_tree_writes(self, repo_doc: Path) -> None:
        with _patch_proposals([_proposal(str(repo_doc))]):
            result = runner.invoke(app, ["fix", str(repo_doc), "--write"])
        assert result.exit_code == 1
        assert NEW in repo_doc.read_text(encoding="utf-8")

    def test_dirty_tree_refuses_and_exits_two(self, repo_doc: Path) -> None:
        repo_doc.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        before = repo_doc.read_text(encoding="utf-8")

        with _patch_proposals([_proposal(str(repo_doc))]):
            result = runner.invoke(app, ["fix", str(repo_doc), "--write"])

        assert result.exit_code == 2
        assert "refusing to write" in result.output
        assert repo_doc.read_text(encoding="utf-8") == before

    def test_force_overrides_dirty_tree(self, repo_doc: Path) -> None:
        repo_doc.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        with _patch_proposals([_proposal(str(repo_doc))]):
            result = runner.invoke(app, ["fix", str(repo_doc), "--write", "--force"])
        assert result.exit_code == 1
        assert NEW in repo_doc.read_text(encoding="utf-8")

    def test_dry_run_ignores_a_dirty_tree(self, repo_doc: Path) -> None:
        repo_doc.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        with _patch_proposals([_proposal(str(repo_doc))]):
            result = runner.invoke(app, ["fix", str(repo_doc)])
        assert result.exit_code == 1

    def test_dirty_tree_refuses_when_invoked_with_a_relative_path(
        self, repo_doc: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: a relative source_file plus git running from the target's
        # own directory resolved the pathspec against the wrong base, so the
        # guard saw a clean tree and wrote over uncommitted changes.
        repo_doc.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        before = repo_doc.read_text(encoding="utf-8")
        monkeypatch.chdir(repo_doc.parent)

        with _patch_proposals([_proposal("a.md")]):
            result = runner.invoke(app, ["fix", "a.md", "--write"])

        assert result.exit_code == 2
        assert "refusing to write" in result.output
        assert repo_doc.read_text(encoding="utf-8") == before

    def test_dirty_tree_refuses_from_a_subdirectory_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "T")
        docs = tmp_path / "docs"
        docs.mkdir()
        f = docs / "index.md"
        f.write_text(f"See [docs]({OLD}) here\n", encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "first")

        f.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        before = f.read_text(encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with _patch_proposals([_proposal("docs/index.md")]):
            result = runner.invoke(app, ["fix", "./docs/", "--write"])

        assert result.exit_code == 2
        assert f.read_text(encoding="utf-8") == before

    def test_non_repo_proceeds_with_a_note(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--write"])
        assert result.exit_code == 1
        assert "not a git repository" in result.output
        assert NEW in doc.read_text(encoding="utf-8")

    def test_suggestion_only_run_skips_the_guard(self, repo_doc: Path) -> None:
        # Nothing would be written, so a dirty tree is irrelevant.
        repo_doc.write_text(f"See [docs]({OLD}) here\nlocal edit\n", encoding="utf-8")
        p = _proposal(str(repo_doc), auto_applicable=False)
        with _patch_proposals([p]):
            result = runner.invoke(app, ["fix", str(repo_doc), "--write"])
        assert result.exit_code == 1


# ── JSON output ───────────────────────────────────────────────────────────────

class TestJsonOutput:
    def test_json_schema_keys(self, doc: Path) -> None:
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--format", "json"])
        [row] = json.loads(result.output)
        assert row == {
            "source_file": str(doc),
            "line": 1,
            "old_url": OLD,
            "new_url": NEW,
            "kind": "redirect",
            "auto_applicable": True,
            "detail": "301 → " + NEW,
        }

    def test_json_includes_suggestions(self, doc: Path) -> None:
        proposals = [_proposal(str(doc)), _proposal(str(doc), auto_applicable=False)]
        with _patch_proposals(proposals):
            result = runner.invoke(app, ["fix", str(doc), "--format", "json"])
        rows = json.loads(result.output)
        assert [r["auto_applicable"] for r in rows] == [True, False]

    def test_output_file_written(self, doc: Path, tmp_path: Path) -> None:
        out = tmp_path / "fixes.json"
        with _patch_proposals([_proposal(str(doc))]):
            runner.invoke(app, ["fix", str(doc), "--format", "json", "--output", str(out)])
        assert json.loads(out.read_text(encoding="utf-8"))[0]["kind"] == "redirect"

    def test_unwritable_output_exits_two(self, doc: Path, tmp_path: Path) -> None:
        bad = tmp_path / "no-such-dir" / "fixes.json"
        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--output", str(bad)])
        assert result.exit_code == 2
        assert "cannot write output" in result.output

    def test_no_proposals_still_yields_parseable_json_on_stdout(self, doc: Path) -> None:
        # Regression: "nothing to fix" used to go to stdout unconditionally,
        # corrupting `--format json` output for a pipe-parsing consumer.
        with _patch_proposals([]):
            result = runner.invoke(app, ["fix", str(doc), "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == []
        assert "nothing to fix" in result.stderr
        assert "nothing to fix" not in result.stdout

    def test_no_proposals_json_output_file_is_written(self, doc: Path, tmp_path: Path) -> None:
        # A consumer redirecting to --output must get a real (empty) JSON
        # document, not an empty/absent file, when there is nothing to fix.
        out = tmp_path / "fixes.json"
        with _patch_proposals([]):
            result = runner.invoke(
                app, ["fix", str(doc), "--format", "json", "--output", str(out)]
            )
        assert result.exit_code == 0
        assert json.loads(out.read_text(encoding="utf-8")) == []


# ── format precedence: linksanity.toml `format` key vs --format (linksanity-u65) ─

class TestFormatConfigPrecedence:
    def test_config_format_json_used_without_flag(
        self, doc: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text('format = "json"\n')
        monkeypatch.chdir(tmp_path)

        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc)])

        assert result.exit_code == 1, result.stderr
        rows = json.loads(result.stdout)
        assert rows[0]["kind"] == "redirect"

    def test_explicit_flag_overrides_config_format(
        self, doc: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text('format = "json"\n')
        monkeypatch.chdir(tmp_path)

        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc), "--format", "console"])

        assert result.exit_code == 1, result.stderr
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)
        assert f"-See [docs]({OLD}) here" in result.stdout

    def test_no_config_no_flag_defaults_to_console(
        self, doc: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc)])

        assert result.exit_code == 1, result.stderr
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)

    def test_bad_config_format_rejected(
        self, doc: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text('format = "bogus"\n')
        monkeypatch.chdir(tmp_path)

        with _patch_proposals([_proposal(str(doc))]):
            result = runner.invoke(app, ["fix", str(doc)])

        assert result.exit_code == 2
        assert "--format" in result.stderr
