"""Tests for json_reporter.py and csv_reporter.py."""

from __future__ import annotations

import csv
import io
import json

from linksanity.queue import LinkResult, LinkStatus, LinkType
from linksanity.reporters.csv_reporter import report as csv_report
from linksanity.reporters.json_reporter import report as json_report


def _result(
    status: LinkStatus = LinkStatus.OK,
    url: str = "https://example.com",
    source_file: str = "docs/index.md",
    line: int = 1,
    link_type: LinkType = LinkType.EXTERNAL,
    **kwargs: object,
) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=link_type,
        status=status,
        **kwargs,  # type: ignore[arg-type]
    )


# ── JSON reporter ─────────────────────────────────────────────────────────────

class TestJsonReporter:
    def test_empty_results_is_empty_array(self) -> None:
        buf = io.StringIO()
        json_report([], file=buf)
        assert json.loads(buf.getvalue()) == []

    def test_single_result_serialized(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        buf = io.StringIO()
        json_report([r], file=buf)
        data = json.loads(buf.getvalue())
        assert len(data) == 1
        assert data[0]["status"] == "broken"
        assert data[0]["http_code"] == 404
        assert data[0]["source_file"] == "docs/index.md"

    def test_redirect_codes_serialized_as_list(self) -> None:
        r = _result(LinkStatus.REDIRECT, http_code=200, redirect_codes=[301, 308])
        buf = io.StringIO()
        json_report([r], file=buf)
        assert json.loads(buf.getvalue())[0]["redirect_codes"] == [301, 308]

    def test_redirect_codes_null_when_absent(self) -> None:
        buf = io.StringIO()
        json_report([_result()], file=buf)
        assert json.loads(buf.getvalue())[0]["redirect_codes"] is None

    def test_all_fields_present(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            http_code=301,
            resolved_url="https://new.example.com",
        )
        buf = io.StringIO()
        json_report([r], file=buf)
        row = json.loads(buf.getvalue())[0]
        for field in ("source_file", "line", "url", "link_type", "status",
                      "http_code", "resolved_url", "error"):
            assert field in row

    def test_null_fields_are_none(self) -> None:
        r = _result(LinkStatus.OK)
        buf = io.StringIO()
        json_report([r], file=buf)
        row = json.loads(buf.getvalue())[0]
        assert row["http_code"] is None
        assert row["resolved_url"] is None
        assert row["error"] is None

    def test_cell_is_null_when_unset(self) -> None:
        r = _result(LinkStatus.OK)
        buf = io.StringIO()
        json_report([r], file=buf)
        row = json.loads(buf.getvalue())[0]
        assert row["cell"] is None

    def test_cell_is_integer_when_set(self) -> None:
        r = _result(LinkStatus.OK, cell=3)
        buf = io.StringIO()
        json_report([r], file=buf)
        row = json.loads(buf.getvalue())[0]
        assert row["cell"] == 3

    def test_link_type_as_string(self) -> None:
        r = _result(LinkStatus.OK, link_type=LinkType.INTERNAL)
        buf = io.StringIO()
        json_report([r], file=buf)
        assert json.loads(buf.getvalue())[0]["link_type"] == "internal"

    def test_multiple_results(self) -> None:
        results = [_result(LinkStatus.OK), _result(LinkStatus.BROKEN, http_code=404)]
        buf = io.StringIO()
        json_report(results, file=buf)
        assert len(json.loads(buf.getvalue())) == 2

    def test_output_ends_with_newline(self) -> None:
        buf = io.StringIO()
        json_report([], file=buf)
        assert buf.getvalue().endswith("\n")

    def test_non_ascii_url_preserved(self) -> None:
        r = _result(LinkStatus.OK, url="https://example.com/André")
        buf = io.StringIO()
        json_report([r], file=buf)
        assert "André" in buf.getvalue()


# ── CSV reporter ──────────────────────────────────────────────────────────────

class TestCsvReporter:
    def test_header_row_present(self) -> None:
        buf = io.StringIO()
        csv_report([], file=buf)
        reader = csv.reader(io.StringIO(buf.getvalue()))
        header = next(reader)
        assert "source_file" in header
        assert "status" in header

    def test_empty_results_only_header(self) -> None:
        buf = io.StringIO()
        csv_report([], file=buf)
        rows = list(csv.reader(io.StringIO(buf.getvalue())))
        assert len(rows) == 1  # just header

    def test_single_result_row(self) -> None:
        r = _result(LinkStatus.BROKEN, http_code=404)
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert len(rows) == 1
        assert rows[0]["status"] == "broken"
        assert rows[0]["http_code"] == "404"

    def test_none_fields_are_empty_string(self) -> None:
        r = _result(LinkStatus.OK)
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["http_code"] == ""
        assert rows[0]["resolved_url"] == ""
        assert rows[0]["error"] == ""

    def test_redirect_codes_joined_with_semicolons(self) -> None:
        r = _result(LinkStatus.REDIRECT, redirect_codes=[301, 308])
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["redirect_codes"] == "301;308"

    def test_redirect_codes_empty_string_when_unset(self) -> None:
        buf = io.StringIO()
        csv_report([_result(LinkStatus.OK)], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["redirect_codes"] == ""

    def test_cell_column_present_in_header(self) -> None:
        buf = io.StringIO()
        csv_report([], file=buf)
        reader = csv.reader(io.StringIO(buf.getvalue()))
        header = next(reader)
        assert "cell" in header

    def test_cell_empty_string_when_unset(self) -> None:
        r = _result(LinkStatus.OK)
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["cell"] == ""

    def test_cell_value_when_set(self) -> None:
        r = _result(LinkStatus.OK, cell=3)
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["cell"] == "3"

    def test_multiple_rows(self) -> None:
        results = [_result(LinkStatus.OK), _result(LinkStatus.BROKEN, http_code=404)]
        buf = io.StringIO()
        csv_report(results, file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert len(rows) == 2

    def test_redirect_row_has_resolved_url(self) -> None:
        r = _result(
            LinkStatus.REDIRECT,
            resolved_url="https://new.example.com",
            http_code=301,
        )
        buf = io.StringIO()
        csv_report([r], file=buf)
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        assert rows[0]["resolved_url"] == "https://new.example.com"
        assert rows[0]["http_code"] == "301"
