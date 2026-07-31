"""End-to-end integration tests for the `linksanity fix` command.

The fixture corpus is copied into tmp_path for every test, since --write
mutates its target files.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from linksanity.cli import app

CORPUS = Path(__file__).parent.parent / "fixtures" / "fix-corpus"

runner = CliRunner()

PERM_OLD = "http://perm.example.com/old"
PERM_NEW = "http://perm.example.com/new"
TEMP_OLD = "http://temp.example.com/old"
TEMP_NEW = "http://temp.example.com/new"
DEAD = "http://dead.example.com/gone"
OK = "http://ok.example.com/"
SNAPSHOT = "http://web.archive.org/web/20200101/http://dead.example.com/gone"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    dest = tmp_path / "docs"
    shutil.copytree(CORPUS, dest)
    return dest


@pytest.fixture
def mock_web() -> None:
    """The corpus' external links: one permanent, one temporary, one dead, one fine."""
    respx.head(PERM_OLD).mock(return_value=httpx.Response(301, headers={"location": PERM_NEW}))
    respx.head(PERM_NEW).mock(return_value=httpx.Response(200))
    respx.head(TEMP_OLD).mock(return_value=httpx.Response(302, headers={"location": TEMP_NEW}))
    respx.head(TEMP_NEW).mock(return_value=httpx.Response(200))
    respx.head(DEAD).mock(return_value=httpx.Response(404))
    respx.head(OK).mock(return_value=httpx.Response(200))


def _index(corpus: Path) -> Path:
    return corpus / "index.md"


# ── Dry run ───────────────────────────────────────────────────────────────────

class TestDryRun:
    @respx.mock
    def test_dry_run_classifies_every_fix_class(
        self, corpus: Path, mock_web: None
    ) -> None:
        respx.get(url__startswith="https://archive.org/wayback/available").mock(
            return_value=httpx.Response(200, json={
                "archived_snapshots": {"closest": {"available": True, "url": SNAPSHOT}}
            })
        )
        result = runner.invoke(app, ["fix", str(corpus), "--wayback"])

        assert result.exit_code == 1
        # permanent redirect + moved file → auto-applied, shown as a diff
        assert f"+A [permanently moved page]({PERM_NEW})" in result.output
        assert "+The [setup guide](reference/setup.md#install)" in result.output
        # temporary redirect, ambiguous basename, dead link → suggestions
        assert "Suggestions" in result.output
        assert TEMP_NEW in result.output
        assert "ambiguous" in result.output
        assert SNAPSHOT in result.output

    @respx.mock
    def test_dry_run_mutates_nothing(self, corpus: Path, mock_web: None) -> None:
        before = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(corpus.rglob("*.md"))
        }
        result = runner.invoke(app, ["fix", str(corpus)])
        assert result.exit_code == 1

        after = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(corpus.rglob("*.md"))
        }
        assert after == before

    @respx.mock
    def test_healthy_link_gets_no_proposal(self, corpus: Path, mock_web: None) -> None:
        result = runner.invoke(app, ["fix", str(corpus), "--format", "json"])
        urls = {row["old_url"] for row in json.loads(result.stdout)}
        assert OK not in urls

    @respx.mock
    def test_no_wayback_flag_means_no_archive_lookup(
        self, corpus: Path, mock_web: None
    ) -> None:
        route = respx.get(url__startswith="https://archive.org/wayback/available").mock(
            return_value=httpx.Response(200, json={"archived_snapshots": {}})
        )
        runner.invoke(app, ["fix", str(corpus)])
        assert not route.called


# ── --write ───────────────────────────────────────────────────────────────────

class TestWrite:
    @respx.mock
    def test_write_applies_exactly_the_expected_edits(
        self, corpus: Path, mock_web: None
    ) -> None:
        result = runner.invoke(app, ["fix", str(corpus), "--write"])
        assert result.exit_code == 1

        assert _index(corpus).read_text(encoding="utf-8") == (
            "# Fix corpus\n"
            "\n"
            f"A [permanently moved page]({PERM_NEW}) is safe to rewrite.\n"
            "\n"
            f"A [temporarily moved page]({TEMP_OLD}) is not.\n"
            "\n"
            f"A [dead page]({DEAD}) may have an archive snapshot.\n"
            "\n"
            "The [setup guide](reference/setup.md#install) moved to another directory.\n"
            "\n"
            f"A [healthy link]({OK}) needs no proposal at all.\n"
        )

    @respx.mock
    def test_write_leaves_ambiguous_links_alone(
        self, corpus: Path, mock_web: None
    ) -> None:
        before = (corpus / "ambiguous.md").read_text(encoding="utf-8")
        runner.invoke(app, ["fix", str(corpus), "--write"])
        assert (corpus / "ambiguous.md").read_text(encoding="utf-8") == before

    @respx.mock
    def test_second_run_has_nothing_left_to_apply(
        self, corpus: Path, mock_web: None
    ) -> None:
        first = runner.invoke(app, ["fix", str(corpus), "--write"])
        assert first.exit_code == 1
        after_first = _index(corpus).read_text(encoding="utf-8")

        second = runner.invoke(app, ["fix", str(corpus), "--write"])

        # Suggestions remain (temporary redirect, ambiguous link), so exit is
        # still 1 — but nothing further is written.
        assert _index(corpus).read_text(encoding="utf-8") == after_first
        assert "No auto-applicable fixes" in second.output

    @respx.mock
    def test_redirects_all_applies_the_temporary_one(
        self, corpus: Path, mock_web: None
    ) -> None:
        runner.invoke(app, ["fix", str(corpus), "--write", "--redirects", "all"])
        content = _index(corpus).read_text(encoding="utf-8")
        assert f"[temporarily moved page]({TEMP_NEW})" in content

    @respx.mock
    def test_wayback_suggestion_is_never_written(
        self, corpus: Path, mock_web: None
    ) -> None:
        respx.get(url__startswith="https://archive.org/wayback/available").mock(
            return_value=httpx.Response(200, json={
                "archived_snapshots": {"closest": {"available": True, "url": SNAPSHOT}}
            })
        )
        runner.invoke(app, ["fix", str(corpus), "--write", "--wayback"])
        content = _index(corpus).read_text(encoding="utf-8")
        assert SNAPSHOT not in content
        assert f"[dead page]({DEAD})" in content


# ── JSON schema ───────────────────────────────────────────────────────────────

class TestJsonSchema:
    @respx.mock
    def test_documented_schema(self, corpus: Path, mock_web: None) -> None:
        result = runner.invoke(app, ["fix", str(corpus), "--format", "json"])
        rows = json.loads(result.stdout)
        assert rows
        for row in rows:
            assert set(row) == {
                "source_file", "line", "old_url", "new_url",
                "kind", "auto_applicable", "detail",
            }
            assert row["kind"] in {"redirect", "moved_file", "wayback"}
            assert isinstance(row["auto_applicable"], bool)
            assert isinstance(row["line"], int)

    @respx.mock
    def test_agent_can_split_auto_from_escalation(
        self, corpus: Path, mock_web: None
    ) -> None:
        result = runner.invoke(app, ["fix", str(corpus), "--format", "json"])
        rows = json.loads(result.stdout)
        auto = {r["kind"] for r in rows if r["auto_applicable"]}
        manual = {r["kind"] for r in rows if not r["auto_applicable"]}
        assert auto == {"redirect", "moved_file"}
        assert "moved_file" in manual   # the ambiguous config.md pair


# ── Exit codes ────────────────────────────────────────────────────────────────

class TestExitCodes:
    @respx.mock
    def test_clean_corpus_exits_zero(self, tmp_path: Path) -> None:
        respx.head(OK).mock(return_value=httpx.Response(200))
        (tmp_path / "clean.md").write_text(f"[fine]({OK})\n", encoding="utf-8")
        result = runner.invoke(app, ["fix", str(tmp_path)])
        assert result.exit_code == 0
        assert "nothing to fix" in result.output
