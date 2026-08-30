"""Tests for init.py — pure documentation-directory detection, estimate, and render."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from linksanity._meta import VERSION
from linksanity.cli import app
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
from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType

runner = CliRunner()


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
    # this keeps passing unchanged regardless of how _CI_OVERHEAD_SECONDS
    # is calibrated.
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


# --- `linksanity init` CLI --------------------------------------------------
#
# `typer.testing.CliRunner` always replaces stdin with a non-terminal stream,
# even when `input=` is given -- so every test that needs to walk through an
# interactive prompt monkeypatches `linksanity.cli._stdin_is_tty` to `True`.
# The one test that exercises the real "no TTY" gate deliberately leaves it
# alone. `linksanity.cli.run_scan` is always stubbed: no test may hit the
# network or run a real scan.

_WORKFLOW_PATH = Path(".github/workflows/linkcheck.yml")
_BASELINE_PATH = Path(".linksanity-baseline.json")


class _FakeScan:
    """Stand-in for `linksanity.cli.run_scan`: async, no network, no filesystem walk."""

    def __init__(
        self, results: list[LinkResult], corpus_files: list[Path] | None = None
    ) -> None:
        self._results = results
        self._corpus_files = corpus_files or []

    async def __call__(self, patterns: list[str], config: object) -> LinkQueue:
        queue = LinkQueue()
        queue.corpus_files = list(self._corpus_files)
        for result in self._results:
            queue.record(result)
        return queue


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("run_scan must not be called")


class _FailingScan:
    """Stand-in for `linksanity.cli.run_scan` that raises, simulating a scan
    failure (e.g. a network error) to verify it still surfaces as exit 2
    now that `_timed_scan` drives `run_scan` via `asyncio.create_task`
    instead of a background thread."""

    async def __call__(self, patterns: list[str], config: object) -> LinkQueue:
        raise RuntimeError("boom")


def _ok_result(url: str = "https://example.com/") -> LinkResult:
    return LinkResult(
        source_file="docs/a.md",
        line=1,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=LinkStatus.OK,
    )


def _broken_result(url: str = "https://example.com/dead") -> LinkResult:
    return LinkResult(
        source_file="docs/a.md",
        line=2,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=LinkStatus.BROKEN,
    )


def _too_many_redirects_result(url: str = "https://example.com/loop") -> LinkResult:
    return LinkResult(
        source_file="docs/a.md",
        line=3,
        url=url,
        link_type=LinkType.EXTERNAL,
        status=LinkStatus.TOO_MANY_REDIRECTS,
    )


def test_init_cli_overwrite_workflow_interactive_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_ok_result()]))
    _WORKFLOW_PATH.parent.mkdir(parents=True)
    _WORKFLOW_PATH.write_text("OLD CONTENT\n")

    result = runner.invoke(app, ["init", "--paths", "docs/"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "already exists" in result.output
    new_content = _WORKFLOW_PATH.read_text()
    assert new_content != "OLD CONTENT\n"
    assert "Link check" in new_content


def test_init_cli_overwrite_workflow_under_yes_errors_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _fail_if_called)
    _WORKFLOW_PATH.parent.mkdir(parents=True)
    _WORKFLOW_PATH.write_text("OLD CONTENT\n")

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 2
    # Not just "it exited nonzero" -- the file on disk must be byte-identical
    # to what was there before the refused run.
    assert _WORKFLOW_PATH.read_text() == "OLD CONTENT\n"


def test_init_cli_overwrite_baseline_interactive_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_broken_result()]))
    _BASELINE_PATH.write_text("OLD BASELINE\n")

    # First "y" accepts the baseline offer, second "y" confirms overwriting
    # the existing baseline file.
    result = runner.invoke(app, ["init", "--paths", "docs/"], input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert "already exists" in result.output
    new_content = _BASELINE_PATH.read_text()
    assert new_content != "OLD BASELINE\n"
    assert "docs/a.md" in new_content


def test_init_cli_overwrite_baseline_under_yes_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_broken_result()]))
    _BASELINE_PATH.write_text("OLD BASELINE\n")

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 2
    assert _BASELINE_PATH.read_text() == "OLD BASELINE\n"
    assert not _WORKFLOW_PATH.exists()


def test_init_cli_yes_writes_baseline_by_default_when_breakage_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_broken_result()]))

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 0, result.output
    assert _BASELINE_PATH.exists()
    assert "baseline: .linksanity-baseline.json" in _WORKFLOW_PATH.read_text()


def test_init_cli_yes_no_baseline_skips_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_broken_result()]))

    result = runner.invoke(
        app, ["init", "--yes", "--paths", "docs/", "--no-baseline"]
    )

    assert result.exit_code == 0, result.output
    assert not _BASELINE_PATH.exists()
    assert "baseline:" not in _WORKFLOW_PATH.read_text()


def test_init_cli_redirect_only_breakage_triggers_baseline_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The baseline offer must fire on `too_many_redirects` alone, not just
    on `broken`/`error` -- see queue.FAILING_STATUSES."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "linksanity.cli.run_scan", _FakeScan([_too_many_redirects_result()])
    )

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 0, result.output
    assert _BASELINE_PATH.exists()


def test_init_cli_competing_checker_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_ok_result()]))
    workflows_dir = Path(".github/workflows")
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "lychee.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - uses: lycheeverse/lychee-action@v1\n"
    )

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 0, result.output
    assert "lychee" in result.stderr
    assert "warning" in result.stderr.lower()


def test_init_cli_dry_run_writes_nothing_prints_workflow_full_baseline_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_broken_result()]))

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not _WORKFLOW_PATH.exists()
    assert not _BASELINE_PATH.exists()
    # The workflow is printed in full...
    assert "name: Link check" in result.output
    assert "paths: docs/" in result.output
    assert "baseline: .linksanity-baseline.json" in result.output
    # ...but the baseline is only a one-line count-and-path summary, never
    # the JSON results body.
    assert "docs/a.md" not in result.output
    assert "https://example.com/dead" not in result.output
    assert "1 known-broken link" in result.output
    assert str(_BASELINE_PATH) in result.output


def test_init_cli_no_measure_skips_scan_estimate_and_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _fail_if_called)

    result = runner.invoke(
        app, ["init", "--yes", "--paths", "docs/", "--no-measure"]
    )

    assert result.exit_code == 0, result.output
    assert "Measured locally" not in result.output
    assert "Estimated billed" not in result.output
    assert not _BASELINE_PATH.exists()
    assert _WORKFLOW_PATH.exists()
    assert "baseline:" not in _WORKFLOW_PATH.read_text()


@pytest.mark.parametrize("bad_name", ["../x.yml", "a/b.yml"])
def test_init_cli_workflow_name_rejects_path_separators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _fail_if_called)

    result = runner.invoke(
        app, ["init", "--yes", "--paths", "docs/", "--workflow-name", bad_name]
    )

    assert result.exit_code == 2
    assert "--workflow-name" in result.stderr
    assert not Path(".github").exists()


def test_init_cli_workflow_name_accepts_bare_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FakeScan([_ok_result()]))

    result = runner.invoke(
        app, ["init", "--yes", "--paths", "docs/", "--workflow-name", "check.yaml"]
    )

    assert result.exit_code == 0, result.output
    assert Path(".github/workflows/check.yaml").exists()


def test_init_cli_no_tty_without_yes_exits_2_with_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _fail_if_called)
    # _stdin_is_tty is deliberately left unpatched: CliRunner's stdin is
    # never a real terminal, which is exactly the condition under test.

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "--yes" in result.stderr
    assert "--paths" in result.stderr
    assert not Path(".github").exists()


def test_init_cli_scan_failure_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan failure (e.g. a raised exception from `run_scan`) must still
    surface as a clean exit 2, not an unhandled exception -- this exercises
    exception propagation through `_timed_scan`'s `asyncio.create_task` +
    `await task`, after the thread-based version was replaced."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("linksanity.cli.run_scan", _FailingScan())

    result = runner.invoke(app, ["init", "--yes", "--paths", "docs/"])

    assert result.exit_code == 2
    assert "measuring scan failed" in result.stderr
    assert "boom" in result.stderr
    assert not _WORKFLOW_PATH.exists()


def test_stdin_is_tty_returns_false_when_stdin_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sys.stdin` is `None` when a process is launched with stdin closed
    (e.g. `python -m linksanity init 0<&-`). `_stdin_is_tty` must treat that
    as "not a tty" instead of raising `AttributeError`."""
    from linksanity.cli import _stdin_is_tty

    monkeypatch.setattr(sys, "stdin", None)

    assert _stdin_is_tty() is False


def test_init_cli_closed_stdin_exits_2_out_of_process(tmp_path: Path) -> None:
    """Out-of-process proof for the closed-stdin fix: a real subprocess with
    fd 0 closed (mirroring `python -m linksanity init 0<&-`) must exit 2 with
    a clean message, not crash with a traceback. This deliberately does not
    go through the `_stdin_is_tty` monkeypatch seam used by the rest of this
    file -- that seam is exactly what hid the original bug."""
    result = subprocess.run(
        f"{sys.executable} -m linksanity init 0<&-",
        shell=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stderr
    assert "--yes" in result.stderr
    assert "--paths" in result.stderr
    assert "Traceback" not in result.stderr


def test_init_cli_malformed_config_exits_2_no_traceback(tmp_path: Path) -> None:
    """A syntactically invalid `linksanity.toml` must exit 2 with a clean
    message, matching every other command's ConfigError handling -- not
    exit 1 with a raw traceback."""
    (tmp_path / "linksanity.toml").write_text("this is [not valid toml\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x\n")

    result = subprocess.run(
        [sys.executable, "-m", "linksanity", "init", "--yes", "--paths", "docs/"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / ".github").exists()
