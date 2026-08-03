"""Smoke tests for scripts/bootstrap_linkcheck.py.

Placed under tests/unit (not scripts/) to mirror the existing convention
for scripts/case_study.py's test file (tests/unit/test_case_study.py).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap_linkcheck.py"

_spec = importlib.util.spec_from_file_location("bootstrap_linkcheck", SCRIPT)
assert _spec is not None and _spec.loader is not None
bootstrap_linkcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap_linkcheck)


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_yes_mode_writes_expected_workflow(tmp_path: Path) -> None:
    result = _run(["--repo", str(tmp_path), "--yes", "--url", "https://example.com"])
    assert result.returncode == 0, result.stderr

    workflow_path = tmp_path / ".github" / "workflows" / "linkcheck.yml"
    assert workflow_path.exists()

    text = workflow_path.read_text(encoding="utf-8")
    assert "https://example.com" in text
    assert "--max-pages 200" in text
    assert "--block-analytics" in text
    assert 'cron: "0 8 * * 1"' in text

    # crawl --check-anchors exists from 0.2.0, which is now the default pin,
    # so the default workflow must emit it.
    assert "--check-anchors" in text

    # The install must be pinned, not floating on latest.
    assert (
        f'pip install "linksanity[browser]=={bootstrap_linkcheck.DEFAULT_LINKSANITY_VERSION}"'
        in text
    )

    # `cache: pip` makes setup-python fail in repos with no Python manifest,
    # which is most sites this workflow gets bootstrapped into.
    assert "cache: pip" not in text


def test_rerun_without_force_fails_and_does_not_modify(tmp_path: Path) -> None:
    first = _run(["--repo", str(tmp_path), "--yes", "--url", "https://example.com"])
    assert first.returncode == 0, first.stderr

    workflow_path = tmp_path / ".github" / "workflows" / "linkcheck.yml"
    original_text = workflow_path.read_text(encoding="utf-8")

    second = _run(["--repo", str(tmp_path), "--yes", "--url", "https://other.example.com"])
    assert second.returncode != 0
    assert workflow_path.read_text(encoding="utf-8") == original_text


def test_workflow_includes_broken_link_reporting_step() -> None:
    """linksanity 0.1.1 has no --annotations flag / github_annotations reporter
    (both are unreleased 0.2.0-only), so the generated workflow must report
    failing links itself from crawl-results.json rather than depending on them.
    """
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )

    assert "name: Report failing links" in yaml_text
    assert "crawl-results.json" in yaml_text
    assert "GITHUB_STEP_SUMMARY" in yaml_text
    assert "broken" in yaml_text and '"error"' in yaml_text

    # 0.1.1 has no --annotations flag; the reporting step must not depend on it.
    assert "--annotations" not in yaml_text

    # In crawl mode `source_file` is the page URL a link was found on, not a
    # repo path, so this step must not emit file=/line= annotation attributes
    # (those are only meaningful for the scan action's real repo paths).
    assert "file=" not in yaml_text
    assert "line=" not in yaml_text

    # The reporting step must run even when the crawl step fails -- it is
    # itself the source of the job's pass/fail verdict now (linksanity-4cx),
    # so it has to see the results regardless of the crawl step's own exit.
    report_step_index = yaml_text.index("name: Report failing links")
    preceding_lines = yaml_text[:report_step_index].splitlines()
    following_lines = yaml_text[report_step_index:].splitlines()
    assert any("if: always()" in line for line in following_lines[:3])

    # It must be placed after the crawl step and before the upload step.
    crawl_index = yaml_text.index("name: Crawl https://example.com")
    upload_index = yaml_text.index("name: Upload results")
    assert crawl_index < report_step_index < upload_index
    assert preceding_lines  # sanity: report step isn't the very first line


def test_workflow_pins_node24_era_actions() -> None:
    """GitHub force-runs node20 actions on Node 24 with a deprecation
    annotation; node20 support is being removed. The generated workflow must
    pin the node24-era majors, not the older node20 ones."""
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )

    assert "actions/checkout@v7" in yaml_text
    assert "actions/setup-python@v7" in yaml_text
    assert "actions/upload-artifact@v7" in yaml_text
    assert "@v4" not in yaml_text
    assert "@v5" not in yaml_text

    # The trailing comment on the checkout line must survive the version bump.
    checkout_line = next(
        line for line in yaml_text.splitlines() if "actions/checkout@v7" in line
    )
    assert "only needed if you keep a .linksanity-skip file" in checkout_line


def test_jq_filters_include_too_many_redirects() -> None:
    """linksanity-4cx: a redirect-loop-only run (status=too_many_redirects) must
    not be silently omitted from the count, the annotations, or the summary
    table -- all three jq select() sites must key off the same status set."""
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )

    select_count = yaml_text.count("too_many_redirects")
    # Three jq select() sites (count, annotations, summary table) each embed
    # the status value once; failing to widen any one of them regresses this.
    assert select_count >= 3, (
        f"expected 'too_many_redirects' in all three jq filters, found "
        f"{select_count} occurrences"
    )

    for line in yaml_text.splitlines():
        if "select(" in line and ".status==" in line:
            assert "too_many_redirects" in line, f"jq select missing too_many_redirects: {line!r}"


def test_summary_wording_says_failing_not_broken() -> None:
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )

    assert "failing link(s) found" in yaml_text
    assert "broken link(s) found" not in yaml_text
    assert "failing_count" in yaml_text
    assert "broken_count" not in yaml_text


def test_rendered_workflow_yaml_is_still_parseable() -> None:
    """The report step's jq programs are embedded in a YAML block scalar
    (the `run: |` heredoc-like literal block). Guard against a stray quote or
    indentation slip in the jq edit breaking the YAML's block structure.

    PyYAML is not a project dependency, so this asserts structurally instead
    of actually parsing the YAML.
    """
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=True,
        block_analytics=True,
    )

    lines = yaml_text.splitlines()

    # Every top-level key in the document starts at column 0 with no leading
    # whitespace; if a block scalar under `run: |` swallowed a following
    # top-level key (e.g. because indentation dropped to column 0 inside the
    # literal block by mistake), these lines would only appear once each.
    top_level_keys = ["name:", "on:", "permissions:", "jobs:"]
    for key in top_level_keys:
        matching = [line for line in lines if line == key or line.startswith(key + " ")]
        assert len(matching) == 1, f"expected exactly one top-level {key!r}, found {matching}"

    # The report step's `run: |` block must stay indented under the step,
    # not dedent to top level -- if it had, "run:" would show up at column 0.
    assert not any(line == "run:" for line in lines)

    # Sanity: the file must not have accidentally introduced an unbalanced
    # single-quote inside a jq program (jq strings are single-quoted in the
    # shell), which would break the surrounding YAML literal block scalar by
    # looking like the shell heredoc terminated early.
    assert yaml_text.count("'") % 2 == 0


def test_no_check_anchors_no_block_analytics_omits_flags() -> None:
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=False,
    )
    assert "--check-anchors" not in yaml_text
    assert "--block-analytics" not in yaml_text
    assert "linksanity crawl https://example.com" in yaml_text


def test_check_anchors_rejected_against_old_pin(tmp_path: Path) -> None:
    """The exact failure that broke the chrischo.org run: crawl --check-anchors
    emitted against a linksanity that has it on `scan` only."""
    result = _run(
        [
            "--repo",
            str(tmp_path),
            "--yes",
            "--url",
            "https://example.com",
            "--check-anchors",
            "--linksanity-version",
            "0.1.1",
        ]
    )
    assert result.returncode == 2
    assert "0.2.0" in result.stderr
    assert not (tmp_path / ".github" / "workflows" / "linkcheck.yml").exists()


def test_check_anchors_allowed_against_new_enough_pin(tmp_path: Path) -> None:
    result = _run(
        [
            "--repo",
            str(tmp_path),
            "--yes",
            "--url",
            "https://example.com",
            "--check-anchors",
            "--linksanity-version",
            "0.2.0",
        ]
    )
    assert result.returncode == 0, result.stderr
    text = (tmp_path / ".github" / "workflows" / "linkcheck.yml").read_text(encoding="utf-8")
    assert "--check-anchors" in text
    assert 'pip install "linksanity[browser]==0.2.0"' in text


def test_version_tuple_orders_releases() -> None:
    vt = bootstrap_linkcheck._version_tuple
    assert vt("0.1.1") < vt("0.2.0")
    assert vt("0.2.0") < vt("0.10.0")
    assert vt("0.2.0rc1") == vt("0.2.0")


def test_yes_requires_url(tmp_path: Path) -> None:
    result = _run(["--repo", str(tmp_path), "--yes"])
    assert result.returncode != 0
    assert "--url" in result.stderr


# --- linksanity-4cx follow-up: the report step now owns the pass/fail verdict ---
#
# Rationale: DEFAULT_LINKSANITY_VERSION (0.2.0) is a published release whose
# `crawl` exit code is `broken + error` only -- `too_many_redirects` only
# started failing crawl's own exit on `main`, which is unreleased. Under the
# 0.2.0 pin a redirect-loop-only run would exit 0 from `crawl` itself, so the
# workflow must decide its own verdict from the results JSON instead of
# trusting the crawl step's exit code.


def _report_step_run_block(yaml_text: str) -> str:
    """Slice out and dedent the `run: |` shell block of the "Report failing
    links" step, so it can be executed directly with bash in a test sandbox.

    Uses simple string slicing rather than a YAML parser (PyYAML is not a
    project dependency) -- this mirrors the structural assumptions already
    checked by test_rendered_workflow_yaml_is_still_parseable.
    """
    start = yaml_text.index("name: Report failing links")
    run_marker = "run: |\n"
    run_start = yaml_text.index(run_marker, start) + len(run_marker)
    end_marker = "\n\n      - name: Upload results"
    end = yaml_text.index(end_marker, run_start)
    block = yaml_text[run_start:end]

    dedented: list[str] = []
    for line in block.splitlines():
        if line.strip() == "":
            dedented.append("")
        elif line.startswith(" " * 10):
            dedented.append(line[10:])
        else:
            raise AssertionError(f"unexpected report-step indentation: {line!r}")
    return "\n".join(dedented)


def _find_jq() -> str | None:
    homebrew_jq = Path("/opt/homebrew/bin/jq")
    if homebrew_jq.exists():
        return str(homebrew_jq)
    return shutil.which("jq")


def _run_report_step(script: str, tmp_path: Path, results_content: str) -> subprocess.CompletedProcess:
    (tmp_path / "crawl-results.json").write_text(results_content, encoding="utf-8")
    summary_path = tmp_path / "step-summary.md"

    jq_path = _find_jq()
    assert jq_path is not None  # caller must have already skipped if jq is absent
    env = dict(os.environ)
    env["PATH"] = f"{Path(jq_path).parent}{os.pathsep}{env.get('PATH', '')}"
    env["GITHUB_STEP_SUMMARY"] = str(summary_path)

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    result.summary_path = summary_path  # type: ignore[attr-defined]
    return result


def test_report_step_source_no_longer_claims_it_cannot_fail_the_job() -> None:
    """linksanity-4cx: the step now decides the job's verdict itself, so the
    stale "this step must never fail the job" comment must be gone."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "must never fail the job itself" not in source
    assert "the crawl step's own exit code already decides pass/fail" not in source

    # Replacement must explain *why* the workflow, not linksanity's exit code,
    # owns the verdict: the too_many_redirects/0.2.0 release-lag rationale.
    assert "too_many_redirects" in source
    assert "0.2.0" in source


def test_rendered_header_comment_says_failing_not_broken() -> None:
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )
    header_line = yaml_text.splitlines()[0]
    assert header_line.startswith("# Crawls https://example.com and fails the job")
    assert "failing" in header_line
    assert "broken" not in header_line


def test_report_step_contains_exit_1_on_failing_path() -> None:
    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )
    report_index = yaml_text.index("name: Report failing links")
    upload_index = yaml_text.index("name: Upload results")
    report_section = yaml_text[report_index:upload_index]
    assert "exit 1" in report_section


def test_report_step_execution_too_many_redirects_fails_the_job(tmp_path: Path) -> None:
    """The real regression: a redirect-loop-only run must fail the job even
    though the published 0.2.0 pin's own `crawl` exit code would be 0."""
    if _find_jq() is None:
        pytest.skip("jq not available")

    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )
    script = _report_step_run_block(yaml_text)

    results = json.dumps(
        [
            {
                "status": "too_many_redirects",
                "source_file": "https://example.com/",
                "url": "https://example.com/loop",
                "http_code": None,
                "error": None,
            }
        ]
    )
    result = _run_report_step(script, tmp_path, results)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::" in result.stdout
    assert "too_many_redirects" in result.stdout
    summary_path = result.summary_path  # type: ignore[attr-defined]
    assert summary_path.exists()
    assert "failing link(s) found" in summary_path.read_text(encoding="utf-8")


def test_report_step_execution_all_ok_passes(tmp_path: Path) -> None:
    if _find_jq() is None:
        pytest.skip("jq not available")

    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )
    script = _report_step_run_block(yaml_text)

    results = json.dumps(
        [
            {
                "status": "ok",
                "source_file": "https://example.com/",
                "url": "https://example.com/",
                "http_code": 200,
                "error": None,
            }
        ]
    )
    result = _run_report_step(script, tmp_path, results)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error::" not in result.stdout


def test_report_step_execution_corrupt_results_fails_loudly_not_silently(tmp_path: Path) -> None:
    """A results file that isn't valid JSON must fail the step with a clear
    message -- it must never be swallowed into a silent "0 failing" green,
    which is what the old `2>/dev/null || echo 0` fallback used to do."""
    if _find_jq() is None:
        pytest.skip("jq not available")

    yaml_text = bootstrap_linkcheck.render_workflow(
        url="https://example.com",
        schedule="0 8 * * 1",
        max_pages=200,
        check_anchors=False,
        block_analytics=True,
    )
    script = _report_step_run_block(yaml_text)

    result = _run_report_step(script, tmp_path, "this is not json{{{")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "could not parse" in (result.stdout + result.stderr)
