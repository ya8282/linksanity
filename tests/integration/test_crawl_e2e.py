"""End-to-end integration tests for the `linksanity crawl` command.

Requires playwright to be installed; skipped otherwise.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linksanity.cli import app

pytest.importorskip("playwright", reason="playwright not installed — skipping")

SITE_DIR = Path(__file__).parent.parent / "fixtures" / "site"
runner = CliRunner()


def _start_server(port: int) -> HTTPServer:
    handler = lambda *a, **kw: SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(SITE_DIR), **kw
    )
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server


def _domains_file(domains: list[str]) -> str:
    """Write a temp domains file and return its path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(domains) + "\n")
        return f.name


@pytest.fixture(scope="module")
def site_url() -> str:  # type: ignore[return]
    server = _start_server(18433)
    yield "http://127.0.0.1:18433"
    server.shutdown()


# ── Crawl tests ───────────────────────────────────────────────────────────────

class TestCrawlBasic:
    def test_broken_link_exits_1(self, site_url: str) -> None:
        # page2.html links to /missing.html (404) — Playwright crawls it and sees 404
        ignore = _domains_file(["external.example.com"])
        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--ignore-domains", ignore],
        )
        assert result.exit_code == 1, result.output

    def test_broken_url_in_output(self, site_url: str) -> None:
        ignore = _domains_file(["external.example.com"])
        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--ignore-domains", ignore],
        )
        assert "missing" in result.output

    def test_summary_line_present(self, site_url: str) -> None:
        ignore = _domains_file(["external.example.com"])
        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--ignore-domains", ignore],
        )
        assert "broken=" in result.output

    def test_max_pages_1_limits_crawl(self, site_url: str) -> None:
        # Only index.html is crawled; external link is ignored; exit 0
        ignore = _domains_file(["external.example.com"])
        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--max-pages", "1",
             "--ignore-domains", ignore],
        )
        # index.html itself is reachable (OK), and we skip external links
        assert result.exit_code == 0, result.output

    def test_output_written_to_file(self, site_url: str) -> None:
        ignore = _domains_file(["external.example.com"])
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as out_f:
            out_path = out_f.name
        runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--max-pages", "1",
             "--ignore-domains", ignore,
             "--output", out_path],
        )
        assert Path(out_path).exists()
        assert len(Path(out_path).read_text()) > 0


# ── --format validation (regression: crawl never checked --format) ─────────────

class TestCrawlFormatValidation:
    def test_bad_format_rejected_without_crawling(self) -> None:
        # The bad value must be rejected before any crawl/playwright work
        # starts, so this needs no server and no real network access.
        result = runner.invoke(app, ["crawl", "http://example.invalid", "--format", "bogus"])
        assert result.exit_code == 2
        assert "--format" in result.output

    def test_bad_format_writes_no_output_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            app,
            ["crawl", "http://example.invalid", "--format", "bogus", "--output", str(out)],
        )
        assert result.exit_code == 2
        assert not out.exists()

    def test_valid_format_still_works(self, site_url: str) -> None:
        # The HTTP server used by site_url logs access lines to stderr, which
        # CliRunner can interleave into captured output, so write to a file
        # instead of asserting on stdout being pure JSON.
        ignore = _domains_file(["external.example.com"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as out_f:
            out_path = out_f.name
        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--max-pages", "1",
             "--ignore-domains", ignore,
             "--format", "json",
             "--output", out_path],
        )
        assert result.exit_code == 0, result.output
        assert isinstance(json.loads(Path(out_path).read_text()), list)


# ── format precedence: linksanity.toml `format` key vs --format (linksanity-u65) ─

class TestCrawlFormatConfigPrecedence:
    def test_config_format_json_used_without_flag(
        self, site_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text('format = "json"\n')
        monkeypatch.chdir(tmp_path)
        ignore = _domains_file(["external.example.com"])
        out = tmp_path / "out.json"

        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--max-pages", "1",
             "--ignore-domains", ignore,
             "--output", str(out)],
        )

        assert result.exit_code == 0, result.stderr
        assert isinstance(json.loads(out.read_text()), list)

    def test_explicit_flag_overrides_config_format(
        self, site_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "linksanity.toml").write_text('format = "json"\n')
        monkeypatch.chdir(tmp_path)
        ignore = _domains_file(["external.example.com"])
        out = tmp_path / "out.txt"

        result = runner.invoke(
            app,
            ["crawl", f"{site_url}/index.html",
             "--max-pages", "1",
             "--ignore-domains", ignore,
             "--format", "console",
             "--output", str(out)],
        )

        assert result.exit_code == 0, result.stderr
        text = out.read_text()
        assert "broken=" in text
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)

    def test_bad_config_format_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No --format flag and no network/crawl work needed: format = "bogus"
        # from linksanity.toml must be caught right after load_config.
        (tmp_path / "linksanity.toml").write_text('format = "bogus"\n')
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["crawl", "http://example.invalid"])

        assert result.exit_code == 2
        assert "--format" in result.stderr
