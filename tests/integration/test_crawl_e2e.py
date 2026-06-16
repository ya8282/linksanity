"""End-to-end integration tests for the `linksanity crawl` command.

Requires playwright to be installed; skipped otherwise.
"""

from __future__ import annotations

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
