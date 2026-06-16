"""Tests for LinkResult, LinkStatus, LinkType, and LinkQueue."""

import pytest

from linksanity.queue import LinkQueue, LinkResult, LinkStatus, LinkType


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
        assert values == {"ok", "broken", "redirect", "skipped", "error"}


class TestLinkType:
    def test_all_values_present(self) -> None:
        values = {t.value for t in LinkType}
        assert values == {"external", "internal", "anchor", "external_anchor"}


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

    def test_sources_unknown_url_returns_empty(self) -> None:
        q = LinkQueue()
        assert q.sources("https://never-added.com") == []
