"""End-to-end integration tests for the `linksanity scan` command."""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import app

DOCS_DIR = Path(__file__).parent.parent / "fixtures" / "docs"

runner = CliRunner()


class TestScanExitCodes:
    def test_clean_docs_exits_0(self) -> None:
        # index.md and guide.md reference each other — both exist
        result = runner.invoke(app, ["scan", str(DOCS_DIR / "index.md")])
        assert result.exit_code == 0, result.output

    def test_broken_internal_link_exits_1(self) -> None:
        result = runner.invoke(app, ["scan", str(DOCS_DIR / "broken.md")])
        assert result.exit_code == 1

    def test_external_links_ignored_exits_0(self, tmp_path: Path) -> None:
        f = tmp_path / "ext.md"
        f.write_text("[link](https://example.com/page)\n")
        result = runner.invoke(
            app,
            ["scan", str(f), "--ignore-domains", str(_write_domains(tmp_path, ["example.com"]))],
        )
        assert result.exit_code == 0, result.output

    def test_no_links_exits_0(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("# Just text, no links\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output


class TestScanDirectoryMode:
    def test_directory_scan_finds_broken(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[broken](gone.md)\n")
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 1

    def test_directory_scan_clean_exits_0(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[b](b.md)\n")
        (tmp_path / "b.md").write_text("# B\n")
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_multiple_paths_merged(self, tmp_path: Path) -> None:
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("[broken](missing.md)\n")
        b.write_text("# B\n")
        result = runner.invoke(app, ["scan", str(a), str(b)])
        assert result.exit_code == 1

    def test_rst_files_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.rst"
        # RST with no links — should exit 0
        f.write_text("Title\n=====\n\nJust text.\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output

    def test_html_files_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "page.html"
        f.write_text('<html><body><a href="missing.html">x</a></body></html>\n')
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1


class TestScanOutput:
    def test_output_contains_broken_url(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert "missing.md" in result.output

    def test_output_written_to_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        out = tmp_path / "out.txt"
        result = runner.invoke(app, ["scan", str(f), "--output", str(out)])
        assert result.exit_code == 1
        assert out.exists()
        assert "missing.md" in out.read_text()

    def test_summary_line_present(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](gone.md)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert "broken=" in result.output


class TestScanCheckAnchors:
    def test_bad_anchor_broken_when_flag_set(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("# Real Heading\n\n[bad](#nonexistent)\n")
        result = runner.invoke(app, ["scan", str(f), "--check-anchors"])
        assert result.exit_code == 1

    def test_good_anchor_ok_when_flag_set(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("# Real Heading\n\n[good](#real-heading)\n")
        result = runner.invoke(app, ["scan", str(f), "--check-anchors"])
        assert result.exit_code == 0, result.output


class TestScanGlob:
    def test_glob_pattern_matches_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[broken](gone.md)\n")
        (tmp_path / "b.md").write_text("# clean\n")
        # Pass glob pattern — shell does NOT expand it here, so pass as string
        import glob
        matches = glob.glob(str(tmp_path / "*.md"))
        result = runner.invoke(app, ["scan"] + matches)
        assert result.exit_code == 1


class TestScanFlags:
    def test_workers_flag_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# hi\n")
        result = runner.invoke(app, ["scan", str(f), "--workers", "1"])
        assert result.exit_code == 0, result.output

    def test_missing_repo_with_github_issue_exits_2(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.md"
        f.write_text("# hi\n")
        result = runner.invoke(app, ["scan", str(f), "--github-issue"])
        assert result.exit_code == 2


# ── Output format tests ──────────────────────────────────────────────────────

class TestScanOutputFormats:
    def test_json_output_is_valid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        out = tmp_path / "out.json"
        runner.invoke(app, ["scan", str(f), "--format", "json", "--output", str(out)])
        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert data[0]["status"] == "broken"

    def test_csv_output_has_header_and_row(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        out = tmp_path / "out.csv"
        runner.invoke(app, ["scan", str(f), "--format", "csv", "--output", str(out)])
        rows = list(csv.DictReader(io.StringIO(out.read_text())))
        assert len(rows) == 1
        assert rows[0]["status"] == "broken"

    def test_report_flag_creates_markdown_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        report_file = tmp_path / "report.md"
        runner.invoke(app, ["scan", str(f), "--report", str(report_file)])
        content = report_file.read_text()
        assert "# linksanity" in content
        assert "broken" in content

    def test_json_stdout_when_no_output_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(app, ["scan", str(f), "--format", "json"])
        data = json.loads(result.output)
        assert data[0]["status"] == "broken"


# ── HTTP edge cases (local server) ────────────────────────────────────────────

class _SilentHandler(BaseHTTPRequestHandler):
    """Handles HEAD/GET; routes /redirect → 301, /final → 200, /405 → 405, * → 404."""

    def _send(self, code: int, location: str = "") -> None:
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.end_headers()

    def do_HEAD(self) -> None:
        base = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        if self.path == "/redirect":
            self._send(301, f"{base}/final")
        elif self.path == "/final":
            self._send(200)
        elif self.path == "/405":
            self._send(405)
        else:
            self._send(404)

    def do_GET(self) -> None:
        if self.path == "/405":
            self._send(200)
        else:
            self._send(404)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def http_server() -> str:  # type: ignore[return]
    server = HTTPServer(("127.0.0.1", 0), _SilentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestScanHTTPEdgeCases:
    def test_redirect_detected(self, tmp_path: Path, http_server: str) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"[link]({http_server}/redirect)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output  # redirect is not a broken link
        assert "REDIRECT" in result.output

    def test_404_is_broken(self, tmp_path: Path, http_server: str) -> None:
        f = tmp_path / "a.md"
        f.write_text(f"[link]({http_server}/missing)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1

    def test_head_405_fallback_to_get(self, tmp_path: Path, http_server: str) -> None:
        # /405 returns 405 for HEAD, 200 for GET — should resolve as OK
        f = tmp_path / "a.md"
        f.write_text(f"[link]({http_server}/405)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_domains(tmp_path: Path, domains: list[str]) -> Path:
    p = tmp_path / "ignore.txt"
    p.write_text("\n".join(domains) + "\n")
    return p
