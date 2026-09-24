"""Tests for LinkResult, LinkStatus, LinkType, and LinkQueue."""

import pytest

from linksanity.queue import (
    FAILING_STATUSES,
    LinkQueue,
    LinkResult,
    LinkStatus,
    LinkType,
    classify_status,
)


def make_result(**kwargs: object) -> LinkResult:
    defaults: dict[str, object] = {
        "source_file": "docs/index.md",
        "line": 1,
        "url": "https://example.com",
        "link_type": LinkType.EXTERNAL,
        "status": LinkStatus.OK,
        "http_code": 200,
        "resolved_url": None,
        "error": None,
    }
    defaults.update(kwargs)
    return LinkResult(**defaults)  # type: ignore[arg-type]


class TestLinkStatus:
    def test_all_values_present(self) -> None:
        values = {s.value for s in LinkStatus}
        assert values == {
            "ok", "broken", "redirect", "too_many_redirects", "skipped", "error",
            "blocked",
        }


class TestClassifyStatus:
    def test_401_is_blocked(self) -> None:
        assert classify_status(401, False) == LinkStatus.BLOCKED

    def test_403_is_blocked(self) -> None:
        assert classify_status(403, False) == LinkStatus.BLOCKED

    def test_404_is_broken(self) -> None:
        assert classify_status(404, False) == LinkStatus.BROKEN

    def test_500_is_broken(self) -> None:
        assert classify_status(500, False) == LinkStatus.BROKEN

    def test_redirect_still_detected(self) -> None:
        assert classify_status(200, True) == LinkStatus.REDIRECT

    def test_blocked_not_in_failing_statuses(self) -> None:
        assert LinkStatus.BLOCKED not in FAILING_STATUSES


class TestLinkType:
    def test_all_values_present(self) -> None:
        values = {t.value for t in LinkType}
        assert values == {
            "external", "internal", "anchor", "external_anchor", "non_http_scheme",
        }


class TestLinkResult:
    def test_instantiation_with_defaults(self) -> None:
        r = make_result()
        assert r.source_file == "docs/index.md"
        assert r.http_code == 200
        assert r.resolved_url is None
        assert r.error is None

    @pytest.mark.parametrize("status", list(LinkStatus))
    def test_all_statuses(self, status: LinkStatus) -> None:
        r = make_result(status=status)
        assert r.status == status

    @pytest.mark.parametrize("link_type", list(LinkType))
    def test_all_link_types(self, link_type: LinkType) -> None:
        r = make_result(link_type=link_type)
        assert r.link_type == link_type


class TestLinkQueue:
    def test_new_url_returns_true(self) -> None:
        q = LinkQueue()
        assert q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL) is True

    def test_duplicate_url_returns_false(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL)
        assert q.add("https://a.com", "b.md", 5, LinkType.EXTERNAL) is False

    def test_duplicate_records_both_sources(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL)
        q.add("https://a.com", "b.md", 5, LinkType.EXTERNAL)
        sources = q.sources("https://a.com")
        assert ("a.md", 1) in sources
        assert ("b.md", 5) in sources

    def test_results_returns_recorded(self) -> None:
        q = LinkQueue()
        r = make_result(url="https://a.com")
        q.record(r)
        assert q.results() == [r]

    def test_summary_counts_by_status(self) -> None:
        q = LinkQueue()
        q.record(make_result(status=LinkStatus.OK))
        q.record(make_result(status=LinkStatus.OK))
        q.record(make_result(status=LinkStatus.BROKEN))
        summary = q.summary()
        assert summary["ok"] == 2
        assert summary["broken"] == 1
        assert summary["redirect"] == 0

    def test_summary_counts_blocked(self) -> None:
        q = LinkQueue()
        q.record(make_result(status=LinkStatus.BLOCKED))
        q.record(make_result(status=LinkStatus.BLOCKED))
        q.record(make_result(status=LinkStatus.OK))
        summary = q.summary()
        assert summary["blocked"] == 2
        assert summary["ok"] == 1

    def test_sources_unknown_url_returns_empty(self) -> None:
        q = LinkQueue()
        assert q.sources("https://never-added.com") == []

    def test_docbook_xref_dedupes_across_source_directories(self) -> None:
        # docbook-xref: sentinels are id lookups against the corpus-wide id
        # set -- filesystem.check short-circuits on them before any path
        # resolution, so unlike a real INTERNAL link they must not fall into
        # the source-dependent dedupe branch (linksanity-rml).
        q = LinkQueue()
        assert q.add("docbook-xref:install-step", "a/page.dbk", 1, LinkType.INTERNAL) is True
        assert q.add("docbook-xref:install-step", "b/page.dbk", 9, LinkType.INTERNAL) is False
        assert len(q.pending()) == 1


class TestLinkResultCell:
    def test_cell_defaults_to_none(self) -> None:
        r = make_result()
        assert r.cell is None

    def test_cell_can_be_set(self) -> None:
        r = make_result(cell=3)
        assert r.cell == 3


class TestLinkQueueCell:
    def test_pending_returns_five_tuples(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL)
        pending = q.pending()
        assert len(pending) == 1
        assert len(pending[0]) == 5

    def test_pending_cell_defaults_to_none(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL)
        url, source_file, line, link_type, cell = q.pending()[0]
        assert cell is None

    def test_add_stores_cell_and_pending_returns_it(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL, cell=7)
        url, source_file, line, link_type, cell = q.pending()[0]
        assert cell == 7

    def test_duplicate_url_keeps_first_cell(self) -> None:
        q = LinkQueue()
        q.add("https://a.com", "a.md", 1, LinkType.EXTERNAL, cell=1)
        q.add("https://a.com", "b.md", 5, LinkType.EXTERNAL, cell=99)
        url, source_file, line, link_type, cell = q.pending()[0]
        assert cell == 1
