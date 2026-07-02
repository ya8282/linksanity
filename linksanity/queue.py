"""Link queue, result types, and aggregation."""

from dataclasses import dataclass, field
from enum import Enum


class LinkStatus(Enum):
    OK = "ok"
    BROKEN = "broken"
    REDIRECT = "redirect"
    SKIPPED = "skipped"
    ERROR = "error"


class LinkType(Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    ANCHOR = "anchor"
    EXTERNAL_ANCHOR = "external_anchor"


@dataclass
class LinkResult:
    source_file: str
    line: int
    url: str
    link_type: LinkType
    status: LinkStatus
    http_code: int | None = None
    resolved_url: str | None = None
    error: str | None = None
    cell: int | None = None


@dataclass
class LinkQueue:
    """Deduplicates URLs across sources and aggregates results."""

    _seen: dict[str, list[tuple[str, int]]] = field(default_factory=dict, repr=False)
    _link_types: dict[str, LinkType] = field(default_factory=dict, repr=False)
    _cells: dict[str, int | None] = field(default_factory=dict, repr=False)
    _results: list[LinkResult] = field(default_factory=list, repr=False)

    def add(
        self,
        url: str,
        source_file: str,
        line: int,
        link_type: LinkType,
        *,
        cell: int | None = None,
    ) -> bool:
        """Register a URL. Returns True if this URL is new (needs checking)."""
        if url not in self._seen:
            self._seen[url] = [(source_file, line)]
            self._link_types[url] = link_type
            self._cells[url] = cell
            return True
        self._seen[url].append((source_file, line))
        return False

    def pending(self) -> list[tuple[str, str, int, LinkType, int | None]]:
        """Return (url, source_file, first_line, link_type, cell) for every registered URL."""
        return [
            (url, sources[0][0], sources[0][1], self._link_types[url], self._cells[url])
            for url, sources in self._seen.items()
        ]

    def record(self, result: LinkResult) -> None:
        self._results.append(result)

    def results(self) -> list[LinkResult]:
        return list(self._results)

    def sources(self, url: str) -> list[tuple[str, int]]:
        """All (source_file, line) pairs that reference this URL."""
        return list(self._seen.get(url, []))

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in LinkStatus}
        for r in self._results:
            counts[r.status.value] += 1
        return counts
