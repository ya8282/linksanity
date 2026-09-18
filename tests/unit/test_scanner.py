"""Tests for scanner.py — cache integration and incremental (git diff) filtering."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import respx

from linksanity import cache as cache_module
from linksanity.config import Config
from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.scanner import (
    _collect_docbook_ids,
    _expand_paths,
    _expand_paths_and_roots,
    _pattern_root,
    run_scan,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
DOCBOOK_BOOK_DIR = FIXTURES / "docbook-book"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _ok(url: str, src: str, line: int, lt: LinkType) -> LinkResult:
    return LinkResult(
        source_file=src, line=line, url=url, link_type=lt,
        status=LinkStatus.OK, http_code=200,
    )


def _mock_dispatch() -> AsyncMock:
    mock = AsyncMock()
    mock.side_effect = lambda url, src, line, lt, *a, **kw: _ok(url, src, line, lt)
    return mock


class TestCorpusFiles:
    @pytest.mark.asyncio
    async def test_expanded_corpus_recorded_on_queue(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[l](https://example.com)\n")
        (tmp_path / "b.md").write_text("no links\n")

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(tmp_path)], Config())

        assert sorted(p.name for p in queue.corpus_files) == ["a.md", "b.md"]

    @pytest.mark.asyncio
    async def test_corpus_keeps_unchanged_files_under_incremental(
        self, tmp_path: Path
    ) -> None:
        # The fixer needs every move candidate, not just the changed files.
        _git(tmp_path, "init")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "a.md").write_text("[l](https://example.com)\n")
        (tmp_path / "b.md").write_text("no links\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "init")

        config = Config(incremental=True, since="HEAD")
        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(tmp_path)], config)

        assert sorted(p.name for p in queue.corpus_files) == ["a.md", "b.md"]


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_cache_miss_dispatches_and_persists(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1
        data = json.loads(cache_file.read_text())
        assert "https://example.com" in data["urls"]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_dispatch(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            await run_scan([str(doc)], config)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            queue = await run_scan([str(doc)], config)

        mock_dispatch.assert_not_awaited()
        assert queue.results()[0].status == LinkStatus.OK

    @pytest.mark.asyncio
    async def test_expired_cache_entry_is_rechecked(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({
            "version": cache_module._CACHE_VERSION,
            "urls": {
                "https://example.com": {
                    "source_file": str(doc), "line": 1, "link_type": "external",
                    "status": "ok", "http_code": 200, "resolved_url": None,
                    "error": None, "redirect_chain": None,
                    "checked_at": 0,
                }
            },
            "last_commit": None,
        }))
        config = Config(cache_file=str(cache_file), cache_ttl=3600)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1

    @pytest.mark.asyncio
    async def test_local_link_types_are_not_cached(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        (tmp_path / "other.md").write_text("# Other\n")
        doc.write_text("[link](other.md)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file))

        await run_scan([str(doc)], config)

        data = json.loads(cache_file.read_text())
        assert data["urls"] == {}


class TestOfflineCacheBypass:
    """Task 37: --offline must neither read nor write the cache for the
    external links it short-circuits (router.dispatch returns SKIPPED for
    these, but scanner.py's own read/write gates are what actually keep the
    cache untouched)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_offline_ignores_warm_cache_entry(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({
            "version": cache_module._CACHE_VERSION,
            "urls": {
                "https://example.com": {
                    "source_file": str(doc), "line": 1, "link_type": "external",
                    "status": "ok", "http_code": 200, "resolved_url": None,
                    "error": None, "redirect_chain": None,
                    "checked_at": 9999999999,
                }
            },
            "last_commit": None,
        }))
        config = Config(cache_file=str(cache_file), offline=True)

        queue = await run_scan([str(doc)], config)

        result = queue.results()[0]
        assert result.status == LinkStatus.SKIPPED
        assert result.error == "skipped: --offline"

    @pytest.mark.asyncio
    @respx.mock
    async def test_offline_does_not_write_cache(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        cache_file = tmp_path / "cache.json"
        config = Config(cache_file=str(cache_file), offline=True)

        await run_scan([str(doc)], config)

        data = json.loads(cache_file.read_text())
        assert data["urls"] == {}

    @pytest.mark.asyncio
    @respx.mock
    async def test_offline_fires_zero_http_requests(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n[link2](https://other.com/x)\n")
        config = Config(offline=True)

        queue = await run_scan([str(doc)], config)

        assert {r.status for r in queue.results()} == {LinkStatus.SKIPPED}


class TestIncremental:
    @pytest.mark.asyncio
    async def test_no_baseline_runs_full_scan(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        config = Config(incremental=True)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(doc)], config)

        assert mock_dispatch.await_count == 1
        assert "no previous run recorded" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_since_filters_to_changed_files_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        unchanged = tmp_path / "unchanged.md"
        unchanged.write_text("[link](https://unchanged.com)\n")
        _git(tmp_path, "add", "unchanged.md")
        _git(tmp_path, "commit", "-q", "-m", "first")
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()

        changed = tmp_path / "changed.md"
        changed.write_text("[link](https://changed.com)\n")
        _git(tmp_path, "add", "changed.md")
        _git(tmp_path, "commit", "-q", "-m", "second")

        config = Config(incremental=True, since=baseline)

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()):
            queue = await run_scan([str(tmp_path)], config)

        urls = {r.url for r in queue.results()}
        assert urls == {"https://changed.com"}

    @pytest.mark.asyncio
    async def test_bad_since_ref_falls_back_to_full_scan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        _git(tmp_path, "add", "index.md")
        _git(tmp_path, "commit", "-q", "-m", "first")

        config = Config(incremental=True, since="not-a-real-ref")

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan([str(tmp_path)], config)

        assert mock_dispatch.await_count == 1
        assert "could not diff" in capsys.readouterr().err


class TestDispatchExceptionHandling:
    """cmd.2 safety net: dispatch() exceptions surfaced via gather(return_exceptions=True)
    become ERROR results, but non-Exception BaseExceptions (e.g. cancellation) must not
    be silently swallowed."""

    @pytest.mark.asyncio
    async def test_exception_converted_to_error_result_with_type_name(
        self, tmp_path: Path
    ) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        config = Config()

        with patch(
            "linksanity.scanner.dispatch", new=AsyncMock(side_effect=ValueError("boom"))
        ):
            queue = await run_scan([str(doc)], config)

        result = queue.results()[0]
        assert result.status == LinkStatus.ERROR
        assert result.error == "ValueError: boom"

    @pytest.mark.asyncio
    async def test_exception_with_empty_message_still_diagnosable(
        self, tmp_path: Path
    ) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        config = Config()

        with patch(
            "linksanity.scanner.dispatch", new=AsyncMock(side_effect=RuntimeError())
        ):
            queue = await run_scan([str(doc)], config)

        result = queue.results()[0]
        assert result.status == LinkStatus.ERROR
        assert result.error == "RuntimeError: "

    @pytest.mark.asyncio
    async def test_cancelled_error_outcome_is_reraised_not_swallowed(
        self, tmp_path: Path
    ) -> None:
        # Real asyncio.gather special-cases CancelledError: it re-raises rather
        # than handing it back in the results list, even with return_exceptions=True.
        # Patch gather directly so the scanner's own outcome-handling loop sees a
        # CancelledError value and must re-raise it instead of converting it to
        # an ERROR result.
        doc = tmp_path / "index.md"
        doc.write_text("[link](https://example.com)\n")
        config = Config()

        async def _fake_gather(*coros: object, return_exceptions: bool = True) -> list:
            for c in coros:
                c.close()  # avoid "coroutine was never awaited" warnings
            return [asyncio.CancelledError()]

        with (
            patch("linksanity.scanner.dispatch", new=_mock_dispatch()),
            patch("linksanity.scanner.asyncio.gather", new=_fake_gather),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_scan([str(doc)], config)


class TestExpandPathsPruning:
    """linksanity-5j6: the directory walk must prune the same vendored/hidden
    directories init.py's detection prunes, but only while walking into a
    directory -- an explicitly-requested path is always scanned in full."""

    def test_denylisted_dir_pruned_several_levels_deep(self, tmp_path: Path) -> None:
        deep = tmp_path / "node_modules" / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.md").write_text("# deep\n")
        (tmp_path / "docs.md").write_text("# docs\n")

        paths = _expand_paths([str(tmp_path)])

        assert [p.name for p in paths] == ["docs.md"]

    def test_dot_directory_pruned(self, tmp_path: Path) -> None:
        for dotdir in (".venv", ".git"):
            nested = tmp_path / dotdir / "nested"
            nested.mkdir(parents=True)
            (nested / "hidden.md").write_text("# hidden\n")
        (tmp_path / "docs.md").write_text("# docs\n")

        paths = _expand_paths([str(tmp_path)])

        assert [p.name for p in paths] == ["docs.md"]

    def test_explicit_denylisted_path_is_still_scanned(self, tmp_path: Path) -> None:
        target = tmp_path / "node_modules" / "docs"
        target.mkdir(parents=True)
        (target / "readme.md").write_text("# readme\n")

        paths = _expand_paths([str(target)])

        assert [p.name for p in paths] == ["readme.md"]

    def test_explicit_file_inside_denylisted_dir_is_still_scanned(
        self, tmp_path: Path
    ) -> None:
        venv_dir = tmp_path / ".venv" / "share" / "doc"
        venv_dir.mkdir(parents=True)
        f = venv_dir / "license.md"
        f.write_text("# license\n")

        paths = _expand_paths([str(f)])

        assert paths == [f]

    def test_normal_nested_directory_still_scanned(self, tmp_path: Path) -> None:
        nested = tmp_path / "docs" / "guides"
        nested.mkdir(parents=True)
        (nested / "guide.md").write_text("# guide\n")

        paths = _expand_paths([str(tmp_path)])

        assert [p.name for p in paths] == ["guide.md"]

    def test_root_level_dot_file_is_not_pruned(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.md").write_text("# hidden\n")

        paths = _expand_paths([str(tmp_path)])

        assert [p.name for p in paths] == [".hidden.md"]

    def test_symlinked_directory_is_not_descended(self, tmp_path: Path) -> None:
        # linksanity-1fb: shares init.py's should_descend guard -- a
        # directory symlink (here self-referential) must not be followed.
        # Unguarded, this loops until ELOOP is caught by _walk_pruned's
        # `except OSError`, re-finding a.md at every level first -- a scan
        # that descends a symlink loop is worse than init's wrong count.
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# a\n")
        (docs / "loop").symlink_to(docs, target_is_directory=True)

        paths = _expand_paths([str(tmp_path)])

        assert [p.name for p in paths] == ["a.md"]


class TestPerPatternRoot:
    """linksanity-ham: multi-pattern/glob scans must resolve each file's
    root-relative links against the root of the *pattern* that produced it,
    not one corpus-wide commonpath (which can sit outside every scanned
    tree entirely)."""

    @pytest.mark.asyncio
    async def test_unrelated_directories_each_resolve_against_own_root(
        self, tmp_path: Path
    ) -> None:
        # Measured repro (0ho's reviewer): a decoy file sits at the
        # commonpath of the two unrelated trees, outside both of them. The
        # old corpus-wide commonpath root let a genuinely broken
        # root-relative link resolve against the decoy and report OK -- a
        # false negative. Each pattern's own root must not see the decoy.
        (tmp_path / "missing.md").write_text("# decoy, outside both trees\n")

        x_docs = tmp_path / "x" / "docs"
        x_docs.mkdir(parents=True)
        (x_docs / "page.md").write_text("[link](/missing.md)\n")

        y_docs = tmp_path / "y" / "docs"
        y_docs.mkdir(parents=True)
        (y_docs / "other.md").write_text("# nothing here\n")

        config = Config(offline=True)

        # Single-pattern scan: already correct before and after this fix.
        queue_single = await run_scan([str(x_docs)], config)
        assert queue_single.summary()["broken"] == 1

        # Multi-pattern scan: this is the bug. Before the fix, x/docs and
        # y/docs's commonpath (tmp_path) contains the decoy, so the link
        # resolves against it and passes.
        queue_multi = await run_scan([str(x_docs), str(y_docs)], config)
        assert queue_multi.summary()["broken"] == 1
        assert queue_multi.summary()["ok"] == 0


class TestPatternRoot:
    """_pattern_root: the root a single pattern's own root-relative links
    resolve against."""

    def test_directory_pattern_roots_at_itself(self, tmp_path: Path) -> None:
        d = tmp_path / "docs"
        d.mkdir()

        assert _pattern_root(str(d)) == d.resolve()

    def test_file_pattern_roots_at_parent(self, tmp_path: Path) -> None:
        f = tmp_path / "docs" / "index.md"
        f.parent.mkdir()
        f.write_text("# x\n")

        assert _pattern_root(str(f)) == f.resolve().parent

    def test_glob_roots_at_literal_prefix_not_match_commonpath(
        self, tmp_path: Path
    ) -> None:
        # Both matches share a deeper common parent than the glob's own
        # literal (non-magic) prefix directory. The commonpath of the
        # matches would wrongly root at that deeper directory.
        deep = tmp_path / "globdir" / "sub" / "deep"
        deep.mkdir(parents=True)
        (deep / "one.md").write_text("# one\n")
        (deep / "two.md").write_text("# two\n")

        pattern = str(tmp_path / "globdir" / "**" / "*.md")

        assert _pattern_root(pattern) == (tmp_path / "globdir").resolve()

    def test_bare_glob_with_no_directory_part_roots_at_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert _pattern_root("*.md") == tmp_path.resolve()

    def test_nonexistent_pattern_does_not_crash(self) -> None:
        root = _pattern_root("does/not/exist.md")

        assert isinstance(root, Path)


class TestExpandPathsAndRoots:
    """_expand_paths_and_roots: per-file root map threaded alongside the
    existing deduplicated file list."""

    def test_pattern_matching_nothing_does_not_crash(self, tmp_path: Path) -> None:
        paths, roots = _expand_paths_and_roots([str(tmp_path / "nope" / "*.md")])

        assert paths == []
        assert roots == {}

    def test_mixed_absolute_and_relative_patterns_do_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        abs_dir = tmp_path / "abs_docs"
        abs_dir.mkdir()
        (abs_dir / "a.md").write_text("# a\n")
        rel_dir = tmp_path / "rel_docs"
        rel_dir.mkdir()
        (rel_dir / "b.md").write_text("# b\n")

        paths, roots = _expand_paths_and_roots([str(abs_dir), "rel_docs"])

        assert {p.name for p in paths} == {"a.md", "b.md"}
        by_name = {p.name: p for p in paths}
        assert roots[by_name["a.md"]] == abs_dir.resolve()
        assert roots[by_name["b.md"]] == rel_dir.resolve()

    def test_file_matched_by_two_patterns_keeps_first_patterns_root(
        self, tmp_path: Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        f = docs / "index.md"
        f.write_text("# x\n")

        paths, roots = _expand_paths_and_roots([str(docs), str(f)])

        assert paths == [f]
        assert roots[f] == docs.resolve()


class TestDocbookIdPrescan:
    """_collect_docbook_ids() -- corpus-wide (not per-file) DocBook id collection."""

    def test_merges_ids_across_multiple_files(self) -> None:
        # chapter-1.xml defines id="install-step"; chapter-2.xml only xrefs it.
        # A corpus-wide walk over both files must surface the id regardless of
        # which file it's collected from.
        paths = [DOCBOOK_BOOK_DIR / "chapter-1.xml", DOCBOOK_BOOK_DIR / "chapter-2.xml"]

        ids = _collect_docbook_ids(paths)

        assert "install-step" in ids

    def test_skipped_when_no_docbook_files(self, tmp_path: Path) -> None:
        doc = tmp_path / "index.md"
        doc.write_text("# Just markdown\n")

        with patch("linksanity.scanner.docbook.extract_ids") as mock_extract_ids:
            ids = _collect_docbook_ids([doc])

        mock_extract_ids.assert_not_called()
        assert ids == set()

    def test_dbk_suffix_is_included(self, tmp_path: Path) -> None:
        f = tmp_path / "chapter.dbk"
        f.write_text(
            '<?xml version="1.0"?>\n'
            '<chapter xmlns="http://docbook.org/ns/docbook">'
            '<title>T</title><sect1 id="dbk-id"><title>S</title></sect1>'
            "</chapter>\n"
        )

        ids = _collect_docbook_ids([f])

        assert "dbk-id" in ids

    @pytest.mark.asyncio
    async def test_run_scan_passes_docbook_ids_to_dispatch(self, tmp_path: Path) -> None:
        config = Config()

        with patch("linksanity.scanner.dispatch", new=_mock_dispatch()) as mock_dispatch:
            await run_scan(
                [str(DOCBOOK_BOOK_DIR / "chapter-1.xml"), str(DOCBOOK_BOOK_DIR / "chapter-2.xml")],
                config,
            )

        assert mock_dispatch.await_count == 1
        _, kwargs = mock_dispatch.await_args
        assert kwargs["docbook_ids"] == {"install-step"}
