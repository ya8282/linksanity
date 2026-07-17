"""Tests for fixer.py — proposal builders and the file rewrite engine."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from linksanity.fixer import (
    FixKind,
    FixProposal,
    apply_proposals,
    build_moved_file_proposals,
    build_redirect_proposals,
    build_wayback_proposals,
    is_permanent_redirect,
    render_diff,
)
from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType

OLD = "http://old.example.com/x"
NEW = "https://new.example.com/x"


def _result(**overrides: object) -> LinkResult:
    defaults: dict[str, object] = {
        "source_file": "docs/a.md",
        "line": 1,
        "url": OLD,
        "link_type": LinkType.EXTERNAL,
        "status": LinkStatus.REDIRECT,
        "http_code": 200,
        "resolved_url": NEW,
        "redirect_codes": [301],
    }
    defaults.update(overrides)
    return LinkResult(**defaults)  # type: ignore[arg-type]


def _queue(*sources: tuple[str, int], url: str = OLD) -> LinkQueue:
    q = LinkQueue()
    for source_file, line in sources:
        q.add(url, source_file, line, LinkType.EXTERNAL)
    return q


def _proposal(source_file: str, line: int, **overrides: object) -> FixProposal:
    defaults: dict[str, object] = {
        "source_file": source_file,
        "line": line,
        "old_url": OLD,
        "new_url": NEW,
        "kind": FixKind.REDIRECT,
        "auto_applicable": True,
        "detail": "301 → " + NEW,
    }
    defaults.update(overrides)
    return FixProposal(**defaults)  # type: ignore[arg-type]


# ── is_permanent_redirect ─────────────────────────────────────────────────────

class TestIsPermanentRedirect:
    @pytest.mark.parametrize("codes,expected", [
        ([301], True),
        ([308], True),
        ([301, 308], True),
        ([301, 301], True),
        ([302], False),
        ([307], False),
        ([301, 302], False),   # one temporary hop taints the whole chain
        ([302, 301], False),
        ([], False),           # no chain recorded
        (None, False),         # pre-0.2.0 cache entry
    ])
    def test_permanence(self, codes: list[int] | None, expected: bool) -> None:
        assert is_permanent_redirect(_result(redirect_codes=codes)) is expected


# ── Redirect proposals ────────────────────────────────────────────────────────

class TestRedirectProposals:
    def test_permanent_redirect_is_auto_applicable(self) -> None:
        q = _queue(("docs/a.md", 3))
        [p] = build_redirect_proposals([_result(line=3)], q)
        assert p.kind is FixKind.REDIRECT
        assert p.auto_applicable is True
        assert (p.old_url, p.new_url) == (OLD, NEW)
        assert p.source_file == "docs/a.md"
        assert p.line == 3

    def test_temporary_redirect_is_suggestion_only(self) -> None:
        q = _queue(("docs/a.md", 1))
        [p] = build_redirect_proposals([_result(redirect_codes=[302])], q)
        assert p.auto_applicable is False

    def test_all_redirects_flag_promotes_temporary(self) -> None:
        q = _queue(("docs/a.md", 1))
        [p] = build_redirect_proposals(
            [_result(redirect_codes=[302])], q, all_redirects=True
        )
        assert p.auto_applicable is True

    def test_one_proposal_per_occurrence(self) -> None:
        # LinkQueue dedupes the URL, but every source line needs its own fix.
        q = _queue(("docs/a.md", 3), ("docs/a.md", 9), ("docs/b.md", 2))
        proposals = build_redirect_proposals([_result()], q)
        assert [(p.source_file, p.line) for p in proposals] == [
            ("docs/a.md", 3),
            ("docs/a.md", 9),
            ("docs/b.md", 2),
        ]

    def test_non_redirect_results_ignored(self) -> None:
        q = _queue(("docs/a.md", 1))
        results = [
            _result(status=LinkStatus.OK, resolved_url=None),
            _result(status=LinkStatus.BROKEN, resolved_url=None),
        ]
        assert build_redirect_proposals(results, q) == []

    def test_ipynb_source_is_suggestion_only(self) -> None:
        # Notebook line numbers are within-cell; a file-level rewrite would
        # corrupt an unrelated line.
        q = _queue(("docs/nb.ipynb", 4))
        [p] = build_redirect_proposals([_result(source_file="docs/nb.ipynb")], q)
        assert p.auto_applicable is False
        assert "ipynb" in p.detail

    def test_unsupported_format_is_suggestion_only(self) -> None:
        q = _queue(("docs/a.adoc", 1))
        [p] = build_redirect_proposals([_result(source_file="docs/a.adoc")], q)
        assert p.auto_applicable is False

    def test_detail_names_the_codes_and_target(self) -> None:
        q = _queue(("docs/a.md", 1))
        [p] = build_redirect_proposals([_result(redirect_codes=[301, 308])], q)
        assert "301,308" in p.detail
        assert NEW in p.detail


# ── Moved-file resolver ───────────────────────────────────────────────────────

def _broken_internal(url: str, source_file: str = "docs/a.md") -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=1,
        url=url,
        link_type=LinkType.INTERNAL,
        status=LinkStatus.BROKEN,
        error="file not found",
    )


class TestMovedFileProposals:
    def test_unique_basename_match_is_auto_applicable(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "reference").mkdir(parents=True)
        target = tmp_path / "docs" / "reference" / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "docs" / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./guide/setup.md"
        q = _queue((str(source), 1), url=url)
        [p] = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        )
        assert p.kind is FixKind.MOVED_FILE
        assert p.auto_applicable is True
        assert p.new_url == "reference/setup.md"

    def test_fragment_is_preserved(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "reference").mkdir(parents=True)
        target = tmp_path / "docs" / "reference" / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "docs" / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./guide/setup.md#install"
        q = _queue((str(source), 1), url=url)
        [p] = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        )
        assert p.new_url == "reference/setup.md#install"

    def test_relpath_walks_up_across_sibling_dirs(self, tmp_path: Path) -> None:
        # source in docs/guide/, target in docs/reference/ → needs ../
        (tmp_path / "docs" / "guide").mkdir(parents=True)
        (tmp_path / "docs" / "reference").mkdir(parents=True)
        target = tmp_path / "docs" / "reference" / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "docs" / "guide" / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./setup.md#install"
        q = _queue((str(source), 1), url=url)
        [p] = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        )
        assert p.new_url == "../reference/setup.md#install"

    def test_ambiguous_basename_yields_suggestions_not_a_guess(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "one").mkdir()
        (tmp_path / "two").mkdir()
        a = tmp_path / "one" / "setup.md"
        b = tmp_path / "two" / "setup.md"
        for f in (a, b):
            f.write_text("x", encoding="utf-8")
        source = tmp_path / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./gone/setup.md"
        q = _queue((str(source), 1), url=url)
        proposals = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [a, b, source]
        )
        assert len(proposals) == 2
        assert all(p.auto_applicable is False for p in proposals)
        assert {p.new_url for p in proposals} == {"one/setup.md", "two/setup.md"}

    def test_no_match_falls_back_to_close_matches_as_suggestions(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./setpu.md"  # typo, no exact basename match
        q = _queue((str(source), 1), url=url)
        [p] = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        )
        assert p.auto_applicable is False
        assert p.new_url == "setup.md"

    def test_no_match_and_nothing_close_yields_nothing(self, tmp_path: Path) -> None:
        target = tmp_path / "wildly-different.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./setup.md"
        q = _queue((str(source), 1), url=url)
        assert build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        ) == []

    def test_existing_target_is_not_a_moved_file(self, tmp_path: Path) -> None:
        # Broken because of a missing anchor, not a missing file. Re-pointing
        # the path would be wrong — the file is exactly where the link says.
        target = tmp_path / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "a.md"
        source.write_text("x", encoding="utf-8")

        url = "./setup.md#no-such-anchor"
        q = _queue((str(source), 1), url=url)
        assert build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target, source]
        ) == []

    def test_external_and_ok_results_ignored(self, tmp_path: Path) -> None:
        target = tmp_path / "setup.md"
        target.write_text("x", encoding="utf-8")
        q = _queue(("docs/a.md", 1), url="./gone/setup.md")
        results = [
            LinkResult(
                source_file="docs/a.md", line=1, url="./gone/setup.md",
                link_type=LinkType.EXTERNAL, status=LinkStatus.BROKEN,
            ),
            LinkResult(
                source_file="docs/a.md", line=1, url="./gone/setup.md",
                link_type=LinkType.INTERNAL, status=LinkStatus.OK,
            ),
        ]
        assert build_moved_file_proposals(results, q, [target]) == []

    def test_docbook_xref_sentinel_ignored(self, tmp_path: Path) -> None:
        target = tmp_path / "setup.md"
        target.write_text("x", encoding="utf-8")
        url = "docbook-xref:some-id"
        q = _queue(("docs/a.md", 1), url=url)
        assert build_moved_file_proposals([_broken_internal(url)], q, [target]) == []

    def test_non_rewritable_source_is_suggestion_only(self, tmp_path: Path) -> None:
        target = tmp_path / "setup.md"
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "nb.ipynb"
        source.write_text("x", encoding="utf-8")

        url = "./gone/setup.md"
        q = _queue((str(source), 1), url=url)
        [p] = build_moved_file_proposals(
            [_broken_internal(url, str(source))], q, [target]
        )
        assert p.auto_applicable is False


# ── Wayback suggester ─────────────────────────────────────────────────────────

DEAD = "http://dead.example.com/page"
SNAPSHOT = "http://web.archive.org/web/20200101/http://dead.example.com/page"
WAYBACK_API = "https://archive.org/wayback/available"


def _dead(**overrides: object) -> LinkResult:
    defaults: dict[str, object] = {
        "source_file": "docs/a.md",
        "line": 1,
        "url": DEAD,
        "link_type": LinkType.EXTERNAL,
        "status": LinkStatus.BROKEN,
        "http_code": 404,
    }
    defaults.update(overrides)
    return LinkResult(**defaults)  # type: ignore[arg-type]


def _available(available: bool = True) -> httpx.Response:
    if not available:
        return httpx.Response(200, json={"archived_snapshots": {}})
    return httpx.Response(200, json={
        "archived_snapshots": {
            "closest": {"available": True, "url": SNAPSHOT, "status": "200"}
        }
    })


class TestWaybackProposals:
    @pytest.mark.asyncio
    @respx.mock
    async def test_snapshot_becomes_a_suggestion(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), url=DEAD)
        [p] = await build_wayback_proposals([_dead()], q, timeout=5)
        assert p.kind is FixKind.WAYBACK
        assert p.new_url == SNAPSHOT
        assert p.auto_applicable is False   # never auto-applied, by design

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_snapshot_yields_nothing(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(return_value=_available(False))
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert await build_wayback_proposals([_dead()], q, timeout=5) == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_archive_timeout_degrades_to_no_suggestion(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(
            side_effect=httpx.ConnectTimeout("archive.org is down")
        )
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert await build_wayback_proposals([_dead()], q, timeout=5) == []
        assert capsys.readouterr().err != ""   # noted, not raised

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_json_degrades_to_no_suggestion(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(
            return_value=httpx.Response(200, text="<html>not json</html>")
        )
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert await build_wayback_proposals([_dead()], q, timeout=5) == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_410_is_eligible(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert len(await build_wayback_proposals([_dead(http_code=410)], q, timeout=5)) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_transport_error_is_eligible(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), url=DEAD)
        result = _dead(status=LinkStatus.ERROR, http_code=None, error="dns failure")
        assert len(await build_wayback_proposals([result], q, timeout=5)) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_is_not_eligible(self) -> None:
        # A server error is transient, not link rot — no archive lookup at all.
        route = respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert await build_wayback_proposals([_dead(http_code=500)], q, timeout=5) == []
        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_internal_link_is_not_eligible(self) -> None:
        route = respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), url=DEAD)
        result = _dead(link_type=LinkType.INTERNAL)
        assert await build_wayback_proposals([result], q, timeout=5) == []
        assert not route.called

    @pytest.mark.asyncio
    async def test_no_eligible_results_makes_no_client(self) -> None:
        # No respx mock installed: if this tried any I/O it would fail.
        q = _queue(("docs/a.md", 1), url=DEAD)
        assert await build_wayback_proposals([_dead(status=LinkStatus.OK)], q, timeout=5) == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_suggestion_per_occurrence(self) -> None:
        respx.get(url__startswith=WAYBACK_API).mock(return_value=_available())
        q = _queue(("docs/a.md", 1), ("docs/b.md", 7), url=DEAD)
        proposals = await build_wayback_proposals([_dead()], q, timeout=5)
        assert [(p.source_file, p.line) for p in proposals] == [
            ("docs/a.md", 1), ("docs/b.md", 7)
        ]


# ── Rewrite engine ────────────────────────────────────────────────────────────

class TestApplyProposals:
    def test_rewrites_the_url_on_the_recorded_line(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"# Title\nSee [docs]({OLD}) for more.\n", encoding="utf-8")
        modified = apply_proposals([_proposal(str(f), 2)])
        assert modified == [str(f)]
        assert f.read_text(encoding="utf-8") == f"# Title\nSee [docs]({NEW}) for more.\n"

    def test_touches_no_other_line(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}\n{OLD}\n{OLD}\n", encoding="utf-8")
        apply_proposals([_proposal(str(f), 2)])
        assert f.read_text(encoding="utf-8") == f"{OLD}\n{NEW}\n{OLD}\n"

    def test_all_occurrences_on_the_same_line_are_replaced(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"[a]({OLD}) and [b]({OLD})\n", encoding="utf-8")
        apply_proposals([_proposal(str(f), 1)])
        assert f.read_text(encoding="utf-8") == f"[a]({NEW}) and [b]({NEW})\n"

    def test_url_that_is_a_prefix_of_a_longer_url_is_not_touched(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}/deeper/page\n", encoding="utf-8")
        modified = apply_proposals([_proposal(str(f), 1)])
        assert modified == []
        assert f.read_text(encoding="utf-8") == f"{OLD}/deeper/page\n"

    def test_prefix_guard_still_fixes_a_real_match_on_the_same_line(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}/deeper and {OLD} alone\n", encoding="utf-8")
        apply_proposals([_proposal(str(f), 1)])
        assert f.read_text(encoding="utf-8") == f"{OLD}/deeper and {NEW} alone\n"

    def test_multiple_files_each_written_once(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a.md", tmp_path / "b.md"
        a.write_text(f"{OLD}\n{OLD}\n", encoding="utf-8")
        b.write_text(f"x\n{OLD}\n", encoding="utf-8")
        modified = apply_proposals([
            _proposal(str(a), 1), _proposal(str(a), 2), _proposal(str(b), 2)
        ])
        assert sorted(modified) == sorted([str(a), str(b)])
        assert a.read_text(encoding="utf-8") == f"{NEW}\n{NEW}\n"
        assert b.read_text(encoding="utf-8") == f"x\n{NEW}\n"

    def test_suggestion_only_proposals_are_never_applied(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}\n", encoding="utf-8")
        modified = apply_proposals([_proposal(str(f), 1, auto_applicable=False)])
        assert modified == []
        assert f.read_text(encoding="utf-8") == f"{OLD}\n"

    def test_stale_line_is_skipped_with_a_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # File edited since the scan: the URL is no longer on line 1.
        f = tmp_path / "a.md"
        f.write_text("something else entirely\n", encoding="utf-8")
        modified = apply_proposals([_proposal(str(f), 1)])
        assert modified == []
        assert f.read_text(encoding="utf-8") == "something else entirely\n"
        assert "skipped" in capsys.readouterr().err.lower()

    def test_line_number_past_end_of_file_is_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}\n", encoding="utf-8")
        modified = apply_proposals([_proposal(str(f), 99)])
        assert modified == []
        assert capsys.readouterr().err != ""

    def test_unreadable_file_is_skipped_not_raised(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "gone.md"
        modified = apply_proposals([_proposal(str(missing), 1)])
        assert modified == []
        assert capsys.readouterr().err != ""

    def test_file_without_trailing_newline_keeps_not_having_one(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"line1\n{OLD}", encoding="utf-8")
        apply_proposals([_proposal(str(f), 2)])
        assert f.read_text(encoding="utf-8") == f"line1\n{NEW}"

    def test_crlf_line_endings_are_preserved(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_bytes(f"# Title\r\n{OLD}\r\n".encode())
        apply_proposals([_proposal(str(f), 2)])
        assert f.read_bytes() == f"# Title\r\n{NEW}\r\n".encode()

    def test_non_ascii_content_survives(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"André está aquí {OLD}\n", encoding="utf-8")
        apply_proposals([_proposal(str(f), 1)])
        assert f.read_text(encoding="utf-8") == f"André está aquí {NEW}\n"

    def test_empty_proposal_list_writes_nothing(self) -> None:
        assert apply_proposals([]) == []

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}\n", encoding="utf-8")
        apply_proposals([_proposal(str(f), 1)])
        assert [p.name for p in tmp_path.iterdir()] == ["a.md"]


# ── Diff rendering ────────────────────────────────────────────────────────────

class TestRenderDiff:
    def test_diff_shows_old_and_new(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"See {OLD} here\n", encoding="utf-8")
        diff = render_diff([_proposal(str(f), 1)])
        assert f"-See {OLD} here" in diff
        assert f"+See {NEW} here" in diff

    def test_diff_does_not_modify_the_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        original = f"See {OLD} here\n"
        f.write_text(original, encoding="utf-8")
        render_diff([_proposal(str(f), 1)])
        assert f.read_text(encoding="utf-8") == original

    def test_suggestion_only_proposals_are_not_diffed(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"See {OLD} here\n", encoding="utf-8")
        assert render_diff([_proposal(str(f), 1, auto_applicable=False)]) == ""

    def test_empty_proposals_render_empty(self) -> None:
        assert render_diff([]) == ""

    def test_stale_line_renders_nothing_and_stays_quiet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A dry run must not emit the stale-line warning; only --write does.
        f = tmp_path / "a.md"
        f.write_text("something else entirely\n", encoding="utf-8")
        assert render_diff([_proposal(str(f), 1)]) == ""
        assert capsys.readouterr().err == ""

    def test_line_past_end_of_file_renders_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"{OLD}\n", encoding="utf-8")
        assert render_diff([_proposal(str(f), 99)]) == ""

    def test_unreadable_file_renders_nothing(self, tmp_path: Path) -> None:
        assert render_diff([_proposal(str(tmp_path / "gone.md"), 1)]) == ""


# ── Atomic write ──────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_failed_replace_leaves_no_temp_file_and_original_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "a.md"
        original = f"{OLD}\n"
        f.write_text(original, encoding="utf-8")

        def boom(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("linksanity.fixer.os.replace", boom)
        with pytest.raises(OSError, match="disk full"):
            apply_proposals([_proposal(str(f), 1)])

        assert f.read_text(encoding="utf-8") == original
        assert [p.name for p in tmp_path.iterdir()] == ["a.md"]
