"""End-to-end integration tests for the `linksanity scan` command."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from linksanity.cli import app
from linksanity.config import Config
from linksanity.queue import LinkStatus
from linksanity.scanner import run_scan

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


# ── HTTP edge cases (mocked via respx) ────────────────────────────────────────

class TestScanHTTPEdgeCases:
    @respx.mock
    def test_redirect_detected(self, tmp_path: Path) -> None:
        # Mock a redirect: /redirect → /final, both resolve via head
        respx.head("https://example.com/redirect").mock(
            return_value=httpx.Response(301, headers={"location": "https://example.com/final"})
        )
        respx.head("https://example.com/final").mock(return_value=httpx.Response(200))

        f = tmp_path / "a.md"
        f.write_text("[link](https://example.com/redirect)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output  # redirect is not a broken link
        assert "REDIRECT" in result.output

    @respx.mock
    def test_404_is_broken(self, tmp_path: Path) -> None:
        # Mock a 404 response
        respx.head("https://example.com/missing").mock(return_value=httpx.Response(404))

        f = tmp_path / "a.md"
        f.write_text("[link](https://example.com/missing)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1

    @respx.mock
    def test_head_405_fallback_to_get(self, tmp_path: Path) -> None:
        # /405 returns 405 for HEAD, 200 for GET — should resolve as OK
        respx.head("https://example.com/405").mock(return_value=httpx.Response(405))
        respx.get("https://example.com/405").mock(return_value=httpx.Response(200))

        f = tmp_path / "a.md"
        f.write_text("[link](https://example.com/405)\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output


# ── Baseline diffing ──────────────────────────────────────────────────────────

class TestScanBaseline:
    def test_known_broken_link_exits_0_against_baseline(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")

        baseline = tmp_path / "baseline.json"
        runner.invoke(app, ["scan", str(f), "--format", "json", "--output", str(baseline)])
        assert json.loads(baseline.read_text())[0]["status"] == "broken"

        result = runner.invoke(app, ["scan", str(f), "--baseline", str(baseline)])
        assert result.exit_code == 0, result.output

    def test_new_broken_link_still_exits_1(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")

        baseline = tmp_path / "baseline.json"
        runner.invoke(app, ["scan", str(f), "--format", "json", "--output", str(baseline)])

        f.write_text("[broken](missing.md)\n[new-broken](also-missing.md)\n")
        result = runner.invoke(app, ["scan", str(f), "--baseline", str(baseline)])
        assert result.exit_code == 1
        assert "also-missing.md" in result.output
        assert "gone.md" not in result.output

    def test_missing_baseline_file_reports_everything(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("[broken](missing.md)\n")
        result = runner.invoke(
            app, ["scan", str(f), "--baseline", str(tmp_path / "no-such-file.json")]
        )
        assert result.exit_code == 1


# ── New format wiring (Task 29) ────────────────────────────────────────────────
#
# All fixture content below uses internal (relative) links only, so these
# tests never touch the network -- they exercise _expand_paths()/_parse()
# suffix dispatch and filesystem.check(), nothing more.

_DOCBOOK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns="http://docbook.org/ns/docbook" xmlns:xlink="http://www.w3.org/1999/xlink">
  <title>Doc</title>
  <sect1>
    <title>Section</title>
    <para><link xlink:href="{target}">x</link></para>
  </sect1>
</article>
"""


class TestScanNewFormatsDirect:
    """Each new suffix is dispatched to the right parser when scanned directly."""

    def test_adoc_file_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.adoc"
        f.write_text("An internal link: link:missing.adoc[Missing].\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.adoc" in result.output

    def test_asciidoc_alt_suffix_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.asciidoc"
        f.write_text("An internal link: link:missing.asciidoc[Missing].\n")
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.asciidoc" in result.output

    def test_mdx_file_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.mdx"
        f.write_text('[broken](missing.mdx)\n\n<a href="also-missing.mdx">x</a>\n')
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.mdx" in result.output
        assert "also-missing.mdx" in result.output

    def test_ipynb_file_scanned(self, tmp_path: Path) -> None:
        notebook = {
            "cells": [{"cell_type": "markdown", "source": "[broken](missing.md)\n"}]
        }
        f = tmp_path / "nb.ipynb"
        f.write_text(json.dumps(notebook))
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.md" in result.output

    def test_docbook_xml_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.xml"
        f.write_text(_DOCBOOK_XML.format(target="missing.html"))
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.html" in result.output

    def test_dbk_suffix_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.dbk"
        f.write_text(_DOCBOOK_XML.format(target="missing.html"))
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 1
        assert "missing.html" in result.output

    def test_nondocbook_xml_yields_no_links(self, tmp_path: Path) -> None:
        # Root tag isn't a recognized DocBook element -> extract_links() is a
        # no-op, so this must never trigger a real network check either.
        f = tmp_path / "config.xml"
        f.write_text(
            '<?xml version="1.0"?>\n<config>\n'
            '  <setting name="debug">true</setting>\n'
            '  <ulink url="https://example.com/should-not-be-found"/>\n'
            "</config>\n"
        )
        result = runner.invoke(app, ["scan", str(f)])
        assert result.exit_code == 0, result.output


class TestScanNewFormatsDirectoryMode:
    def test_directory_scan_picks_up_all_new_suffixes(self, tmp_path: Path) -> None:
        (tmp_path / "a.adoc").write_text("link:missing-adoc.md[x]\n")
        (tmp_path / "b.asciidoc").write_text("link:missing-asciidoc.md[x]\n")
        (tmp_path / "c.mdx").write_text("[x](missing-mdx.md)\n")
        (tmp_path / "d.ipynb").write_text(
            json.dumps(
                {"cells": [{"cell_type": "markdown", "source": "[x](missing-ipynb.md)\n"}]}
            )
        )
        (tmp_path / "e.xml").write_text(_DOCBOOK_XML.format(target="missing-xml.md"))
        (tmp_path / "f.dbk").write_text(_DOCBOOK_XML.format(target="missing-dbk.md"))

        result = runner.invoke(app, ["scan", str(tmp_path)])

        assert result.exit_code == 1
        for missing in (
            "missing-adoc.md",
            "missing-asciidoc.md",
            "missing-mdx.md",
            "missing-ipynb.md",
            "missing-xml.md",
            "missing-dbk.md",
        ):
            assert missing in result.output, f"{missing} not found in scan output"


class TestScanAllEightFormatsCombined:
    """DoD checkpoint: 'All 8 formats (md, rst, html + 5 new) scan correctly
    in one combined run.' TestScanNewFormatsDirectoryMode above proves the 5
    new formats work together, but never in the same run as the 3 original
    formats (md, rst, html) -- this test closes that gap by scanning a
    single directory containing all 8 at once, each with one deliberately
    broken internal link, and asserting every one is picked up."""

    def test_all_eight_formats_scanned_in_one_run(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[broken](missing-md.md)\n")
        (tmp_path / "b.rst").write_text("A `broken link <missing-rst.md>`_.\n")
        (tmp_path / "c.html").write_text(
            '<html><body><a href="missing-html.md">x</a></body></html>\n'
        )
        (tmp_path / "d.adoc").write_text("link:missing-adoc.md[Missing].\n")
        (tmp_path / "e.mdx").write_text(
            '[broken](missing-mdx.md)\n\n<a href="also-missing-mdx.md">x</a>\n'
        )
        (tmp_path / "f.ipynb").write_text(
            json.dumps(
                {"cells": [{"cell_type": "markdown", "source": "[x](missing-ipynb.md)\n"}]}
            )
        )
        (tmp_path / "g.xml").write_text(_DOCBOOK_XML.format(target="missing-xml.md"))
        (tmp_path / "h-myst.md").write_text(
            "See {doc}`missing-myst-target` for setup.\n"
        )

        result = runner.invoke(app, ["scan", str(tmp_path), "--myst"])

        assert result.exit_code == 1
        for missing in (
            "missing-md.md",
            "missing-rst.md",
            "missing-html.md",
            "missing-adoc.md",
            "missing-mdx.md",
            "also-missing-mdx.md",
            "missing-ipynb.md",
            "missing-xml.md",
            "missing-myst-target",
        ):
            assert missing in result.output, f"{missing} not found in scan output"


class TestNotebookCellWiring:
    """.ipynb goes through run_scan's direct queue.add(cell=...) path, not _parse()."""

    @pytest.mark.asyncio
    async def test_ipynb_links_queued_with_correct_cell_and_line(
        self, tmp_path: Path
    ) -> None:
        notebook = {
            "cells": [
                {"cell_type": "code", "source": "x = 1\n"},
                {
                    "cell_type": "markdown",
                    "source": "intro\n\n[a](missing-a.md)\n",
                },
                {"cell_type": "markdown", "source": "[b](missing-b.md)\n"},
            ]
        }
        f = tmp_path / "nb.ipynb"
        f.write_text(json.dumps(notebook))

        queue = await run_scan([str(f)], Config())
        results = {r.url: r for r in queue.results()}

        assert results["missing-a.md"].cell == 2
        assert results["missing-a.md"].line == 3
        assert results["missing-a.md"].status == LinkStatus.BROKEN

        assert results["missing-b.md"].cell == 3
        assert results["missing-b.md"].line == 1
        assert results["missing-b.md"].status == LinkStatus.BROKEN


class TestDocBookXrefResolution:
    """<xref> resolution against the corpus-wide id index (Task 31)."""

    def test_xref_sentinel_resolves_to_ok(self, tmp_path: Path) -> None:
        content = """<?xml version="1.0"?>
<article xmlns="http://docbook.org/ns/docbook" xmlns:xlink="http://www.w3.org/1999/xlink">
  <title>Doc</title>
  <sect1><title>S</title><para>See <xref linkend="setup-section"/>.</para></sect1>
  <sect1 id="setup-section"><title>Setup</title></sect1>
</article>
"""
        f = tmp_path / "doc.xml"
        f.write_text(content)
        result = runner.invoke(app, ["scan", str(f)])

        # "setup-section" is a valid id in this same document, and the
        # corpus-wide ID index (Task 30) plus the docbook-xref dispatch
        # branch (Task 31) now resolve it, so the scan succeeds cleanly.
        assert result.exit_code == 0
        assert "docbook-xref:setup-section" not in result.output

    def test_xref_sentinel_resolves_to_broken(self, tmp_path: Path) -> None:
        content = """<?xml version="1.0"?>
<article xmlns="http://docbook.org/ns/docbook" xmlns:xlink="http://www.w3.org/1999/xlink">
  <title>Doc</title>
  <sect1><title>S</title><para>See <xref linkend="does-not-exist"/>.</para></sect1>
</article>
"""
        f = tmp_path / "doc.xml"
        f.write_text(content)
        result = runner.invoke(app, ["scan", str(f)])

        # No id "does-not-exist" anywhere in the corpus, so this must be
        # reported BROKEN (exit 1), not silently SKIPPED — guards against
        # classify() ever mis-routing the docbook-xref: sentinel scheme.
        assert result.exit_code == 1
        assert "docbook-xref:does-not-exist" in result.output


class TestDocBookCorpusWideIdPrescan:
    """Task 30: pre-scan walks every .xml/.dbk file in the scan target once,
    merging ids into a corpus-wide set -- proven here with a two-file fixture
    where the id and the xref referencing it live in different files."""

    DOCBOOK_BOOK_DIR = Path(__file__).parent.parent / "fixtures" / "docbook-book"

    def test_xref_across_files_resolves_via_corpus_wide_index(self) -> None:
        # chapter-1.xml defines xml:id="install-step"; chapter-2.xml xrefs it.
        # The corpus-wide id set is computed and threaded through
        # dispatch()/filesystem.check() (Task 30), and filesystem.check()
        # now consumes it to resolve docbook-xref: sentinels (Task 31), so
        # the cross-file reference resolves cleanly even though the id and
        # the xref referencing it live in different files.
        result = runner.invoke(app, ["scan", str(self.DOCBOOK_BOOK_DIR)])

        assert result.exit_code == 0
        assert "docbook-xref:install-step" not in result.output


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_domains(tmp_path: Path, domains: list[str]) -> Path:
    p = tmp_path / "ignore.txt"
    p.write_text("\n".join(domains) + "\n")
    return p
