"""Tests for git_utils.py — exercised against a real throwaway git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from linksanity import git_utils


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.md").write_text("# A\n")
    _git(tmp_path, "add", "a.md")
    _git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


class TestOutsideRepo:
    def test_repo_root_none_outside_git(self, tmp_path: Path) -> None:
        assert git_utils.repo_root(tmp_path) is None

    def test_current_head_none_outside_git(self, tmp_path: Path) -> None:
        assert git_utils.current_head(tmp_path) is None

    def test_changed_files_none_outside_git(self, tmp_path: Path) -> None:
        assert git_utils.changed_files("HEAD", tmp_path) is None

    def test_is_dirty_none_outside_git(self, tmp_path: Path) -> None:
        assert git_utils.is_dirty([tmp_path / "a.md"], tmp_path) is None


class TestInsideRepo:
    def test_repo_root_resolves(self, repo: Path) -> None:
        assert git_utils.repo_root(repo) == repo.resolve()

    def test_current_head_returns_sha(self, repo: Path) -> None:
        head = git_utils.current_head(repo)
        assert head is not None
        assert len(head) == 40

    def test_changed_files_detects_new_commit(self, repo: Path) -> None:
        first_head = git_utils.current_head(repo)
        assert first_head is not None

        (repo / "b.md").write_text("# B\n")
        _git(repo, "add", "b.md")
        _git(repo, "commit", "-q", "-m", "second")

        changed = git_utils.changed_files(first_head, repo)
        assert changed == {(repo / "b.md").resolve()}

    def test_changed_files_empty_when_no_diff(self, repo: Path) -> None:
        head = git_utils.current_head(repo)
        assert head is not None
        assert git_utils.changed_files(head, repo) == set()

    def test_changed_files_bad_ref_returns_none(self, repo: Path) -> None:
        assert git_utils.changed_files("not-a-real-ref", repo) is None


class TestIsDirty:
    def test_clean_tree_is_not_dirty(self, repo: Path) -> None:
        assert git_utils.is_dirty([repo / "a.md"], repo) is False

    def test_uncommitted_edit_is_dirty(self, repo: Path) -> None:
        (repo / "a.md").write_text("# A changed\n")
        assert git_utils.is_dirty([repo / "a.md"], repo) is True

    def test_staged_but_uncommitted_edit_is_dirty(self, repo: Path) -> None:
        (repo / "a.md").write_text("# A changed\n")
        _git(repo, "add", "a.md")
        assert git_utils.is_dirty([repo / "a.md"], repo) is True

    def test_untracked_file_elsewhere_does_not_dirty_our_paths(self, repo: Path) -> None:
        # Only the files we are about to rewrite matter.
        (repo / "unrelated.md").write_text("# new\n")
        assert git_utils.is_dirty([repo / "a.md"], repo) is False

    def test_dirty_is_scoped_to_the_given_paths(self, repo: Path) -> None:
        (repo / "b.md").write_text("# B\n")
        _git(repo, "add", "b.md")
        _git(repo, "commit", "-q", "-m", "add b")
        (repo / "b.md").write_text("# B changed\n")

        assert git_utils.is_dirty([repo / "a.md"], repo) is False
        assert git_utils.is_dirty([repo / "b.md"], repo) is True
