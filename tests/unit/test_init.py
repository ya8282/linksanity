"""Tests for init.py — pure documentation-directory detection, estimate, and render."""

from __future__ import annotations

from pathlib import Path

import yaml

from linksanity._meta import VERSION
from linksanity.init import (
    DetectionResult,
    Proposal,
    _format_duration,
    count_divergence_warning,
    detect_paths,
    estimate_billed_minutes,
    measuring_config,
    render_estimate,
    render_workflow,
)


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


# --- estimate --------------------------------------------------------------


def test_estimate_rounds_up_to_whole_billed_minute() -> None:
    # 61s measured + 40s overhead = 101s -> ceil(101/60) = 2 billed minutes.
    # overhead is passed explicitly (not read from the module constant) so
    # this keeps passing unchanged once _CI_OVERHEAD_UNCALIBRATED is
    # calibrated and renamed in a later bead.
    assert estimate_billed_minutes(61, overhead_seconds=40) == 2


def test_estimate_cache_off_preserves_rest_of_config(tmp_path: Path) -> None:
    toml_path = tmp_path / "linksanity.toml"
    toml_path.write_text(
        'cache_file = ".cache/linksanity.json"\n'
        "timeout = 42\n"
        'js_domains = ["example.com"]\n'
        'skip_urls = ["https://example.com/private/*"]\n'
        'baseline = ".linksanity-baseline.json"\n'
        "incremental = true\n"
        'since = "2024-01-01"\n'
    )

    cfg = measuring_config(toml_path)

    # The cache override must win regardless of what linksanity.toml sets.
    assert cfg.cache_file is None
    # These three would otherwise filter which URLs the measuring scan
    # visits, shrinking both the estimate and the baseline it feeds --
    # same completeness hazard as cache_file (spec section 5).
    assert cfg.baseline is None
    assert cfg.incremental is False
    assert cfg.since is None
    # But the rest of the file's settings must survive -- proving this
    # builds on load_config()'s result rather than a from-scratch Config.
    assert cfg.timeout == 42
    assert cfg.js_domains == {"example.com"}
    assert cfg.skip_urls == {"https://example.com/private/*"}


def test_format_duration_sub_minute() -> None:
    assert _format_duration(40) == "40s"


def test_format_duration_exactly_one_minute() -> None:
    assert _format_duration(60) == "1m 0s"


def test_format_duration_minutes_and_seconds() -> None:
    assert _format_duration(112) == "1m 52s"


def test_format_duration_zero() -> None:
    assert _format_duration(0) == "0s"


def test_format_duration_rounds_before_dividing() -> None:
    # round(59.6) == 60, so this crosses into the minutes branch rather than
    # rendering "59.6s" or "60s" as a sub-minute value.
    assert _format_duration(59.6) == "1m 0s"


def test_render_estimate_measured_and_overhead_are_separate_lines() -> None:
    lines = render_estimate(61, unique_urls=5, unique_domains=2, overhead_seconds=40)

    measured_lines = [line for line in lines if line.startswith("Measured locally:")]
    overhead_lines = [line for line in lines if line.startswith("CI overhead:")]

    # Locked per spec section 8 / Assumption 11: the measured wall time and
    # the modelled CI overhead must never be collapsed into one confident
    # figure -- this assertion fails the instant someone merges them.
    assert len(measured_lines) == 1
    assert len(overhead_lines) == 1
    measured_line, overhead_line = measured_lines[0], overhead_lines[0]
    assert measured_line != overhead_line
    assert "1m 1s" in measured_line
    assert "40s" in overhead_line
    assert "1m 1s" not in overhead_line
    assert "5 unique URLs" in measured_line
    assert "2 domains" in measured_line


def test_render_estimate_version_note_matches_project_version() -> None:
    lines = render_estimate(61, unique_urls=1, unique_domains=1, overhead_seconds=40)

    assert (
        f"Measured with linksanity {VERSION} locally; CI installs the latest release."
        in lines
    )


def test_render_estimate_billing_lines_present() -> None:
    lines = render_estimate(61, unique_urls=1, unique_domains=1, overhead_seconds=40)
    text = "\n".join(lines)

    assert "Public repo:  free" in lines
    assert "Private repo:" in text
    assert "min/mo" in text
    assert "illustrative" in text


# --- count divergence -------------------------------------------------------


def test_count_divergence_warns_above_threshold() -> None:
    warning = count_divergence_warning(detected_file_count=10, measured_file_count=21)

    assert warning is not None
    assert "21" in warning
    assert "10" in warning


def test_count_divergence_silent_below_threshold() -> None:
    assert count_divergence_warning(detected_file_count=10, measured_file_count=15) is None


def test_count_divergence_exact_2x_boundary_does_not_warn() -> None:
    # Documented boundary: exactly 2x does not warn, only strictly more than
    # 2x does.
    assert count_divergence_warning(detected_file_count=10, measured_file_count=20) is None
    assert count_divergence_warning(detected_file_count=10, measured_file_count=21) is not None


# --- render ------------------------------------------------------------------


def test_render_workflow_omits_baseline_line_when_absent() -> None:
    text = render_workflow(["docs/"])

    assert "baseline:" not in text


def test_render_workflow_includes_baseline_line_when_present() -> None:
    text = render_workflow(["docs/"], baseline_path=".linksanity-baseline.json")

    assert "baseline: .linksanity-baseline.json" in text


def test_render_workflow_multiple_paths_are_space_separated() -> None:
    text = render_workflow(["docs/", "README.md"])

    assert "paths: docs/ README.md" in text


def test_render_workflow_round_trips_through_yaml_safe_load() -> None:
    text = render_workflow(["docs/", "README.md"], baseline_path=".linksanity-baseline.json")

    parsed = yaml.safe_load(text)

    # PyYAML follows YAML 1.1, which parses the bare scalar "on" as the
    # boolean True (the well-known GitHub-Actions-YAML gotcha) rather than
    # the string key "on" -- this is a YAML-parser quirk, not a rendering
    # bug, so the test looks the key up as parsed.
    assert parsed[True] == ["pull_request"]
    assert parsed["permissions"] == {"contents": "read"}
    steps = parsed["jobs"]["linkcheck"]["steps"]
    assert steps[0]["uses"] == "actions/checkout@v4"
    with_block = steps[1]["with"]
    assert with_block["paths"] == "docs/ README.md"
    assert with_block["baseline"] == ".linksanity-baseline.json"
