"""Tests for init.py — pure documentation-directory detection."""

from __future__ import annotations

from pathlib import Path

from linksanity.init import DetectionResult, Proposal, detect_paths


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _paths(result: DetectionResult) -> set[str]:
    return {p.path for p in result.proposals}


def test_denylist_prunes_node_modules(tmp_path: Path) -> None:
    _write(tmp_path / "node_modules" / "x.md")

    result = detect_paths(tmp_path)

    assert result.proposals == []
    assert result.refused == []


def test_prose_gate_rejects_xml_only_repo(tmp_path: Path) -> None:
    _write(tmp_path / "pom.xml")

    result = detect_paths(tmp_path)

    assert result.proposals == []


def test_rollup_collapses_nested_files_to_one_directory(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "a" / "b.md")
    _write(tmp_path / "docs" / "c.md")

    result = detect_paths(tmp_path)

    assert _paths(result) == {"docs/"}
    assert result.proposals == [Proposal(path="docs/", file_count=2)]


def test_root_readme_is_always_included(tmp_path: Path) -> None:
    _write(tmp_path / "README.md")

    result = detect_paths(tmp_path)

    assert "README.md" in _paths(result)


def test_root_readme_included_alongside_other_directories(tmp_path: Path) -> None:
    _write(tmp_path / "README.md")
    _write(tmp_path / "docs" / "guide.md")

    result = detect_paths(tmp_path)

    assert "README.md" in _paths(result)
    assert "docs/" in _paths(result)


def test_empty_repo_reports_nothing_found(tmp_path: Path) -> None:
    result = detect_paths(tmp_path)

    assert result == DetectionResult(proposals=[], refused=[], used_html_fallback=False)


def test_denylist_is_case_insensitive(tmp_path: Path) -> None:
    _write(tmp_path / "Build" / "x.md")
    _write(tmp_path / "Vendor" / "y.md")

    result = detect_paths(tmp_path)

    assert result.proposals == []


def test_html_fallback_proposes_all_html_docs_tree(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "index.html")
    _write(tmp_path / "docs" / "page.htm")

    result = detect_paths(tmp_path)

    assert _paths(result) == {"docs/"}
    assert result.used_html_fallback is True


def test_html_fallback_not_used_when_prose_exists_elsewhere(tmp_path: Path) -> None:
    _write(tmp_path / "README.md")
    _write(tmp_path / "docs" / "index.html")

    result = detect_paths(tmp_path)

    # No prose anywhere in the html-only directory itself, and prose exists
    # globally (README.md), so the html-only directory does not get proposed
    # via the fallback path.
    assert "docs/" not in _paths(result)
    assert result.used_html_fallback is False


def test_unrepresentable_directory_name_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "my docs" / "guide.md")

    result = detect_paths(tmp_path)

    assert _paths(result) == set()
    assert len(result.refused) == 1
    assert result.refused[0].path == "my docs/"
    assert result.refused[0].reason


def test_never_proposes_repo_root_when_all_files_sit_at_root(tmp_path: Path) -> None:
    _write(tmp_path / "README.md")
    _write(tmp_path / "notes.md")
    _write(tmp_path / "changelog.md")

    result = detect_paths(tmp_path)

    proposed = _paths(result)
    assert "." not in proposed
    assert "./" not in proposed
    assert "" not in proposed
    assert proposed == {"README.md", "notes.md", "changelog.md"}


def test_results_ranked_by_file_count_descending(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "a.md")
    _write(tmp_path / "docs" / "b.md")
    _write(tmp_path / "docs" / "c.md")
    _write(tmp_path / "guides" / "d.md")

    result = detect_paths(tmp_path)

    assert [p.path for p in result.proposals] == ["docs/", "guides/"]
