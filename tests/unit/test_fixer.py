"""Tests for fixer.py — proposal builders and the file rewrite engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from linksanity.fixer import (
    FixKind,
    FixProposal,
    apply_proposals,
    build_redirect_proposals,
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
