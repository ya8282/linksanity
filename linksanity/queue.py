"""Link queue, result types, and aggregation."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LinkStatus(Enum):
    OK = "ok"
    BROKEN = "broken"
    REDIRECT = "redirect"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    SKIPPED = "skipped"
    ERROR = "error"


# What counts as a failure for exit codes and CI-facing reporters. A link
# that exceeds --max-redirects never resolved, so it's unusable — same as
# BROKEN/ERROR — even though it's reported separately from the "broken"
# count in human-facing summaries (see markdown_reporter / console reporter).
FAILING_STATUSES = frozenset(
    {LinkStatus.BROKEN, LinkStatus.ERROR, LinkStatus.TOO_MANY_REDIRECTS}
)


def classify_status(code: int, was_redirected: bool) -> LinkStatus:
    """Classify an HTTP outcome: a 4xx/5xx code beats a redirect."""
    if code >= 400:
        return LinkStatus.BROKEN
    if was_redirected:
        return LinkStatus.REDIRECT
    return LinkStatus.OK


class LinkType(Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    ANCHOR = "anchor"
    EXTERNAL_ANCHOR = "external_anchor"
    NON_HTTP_SCHEME = "non_http_scheme"


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
    redirect_chain: list[str] | None = None
    redirect_codes: list[int] | None = None
    cell: int | None = None


# Link types whose target does not depend on the file that referenced them
# (an external http(s) URL, with or without a fragment, names its own
# resolution -- 40 occurrences of the same URL are one check). Anything not
# in this set is source-dependent: see _dedupe_key.
_SOURCE_INDEPENDENT = frozenset(
    {LinkType.EXTERNAL, LinkType.EXTERNAL_ANCHOR, LinkType.NON_HTTP_SCHEME}
)

# A pending()-dispatch dedupe key: either the raw URL (source-independent
# link types), or (url, resolution_base) for link types whose target
# depends on where they were written.
_DedupeKey = str | tuple[str, str]


def _dedupe_key(
    url: str, source_file: str, link_type: LinkType, root: str | Path | None
) -> _DedupeKey:
    """Return the pending()-dispatch dedupe key for one URL occurrence.

    Mirrors checkers.filesystem.check's own resolution logic, so two
    occurrences only collapse when they'd actually check the same target:
    - ANCHOR ('#section') resolves against its own source file.
    - INTERNAL resolves against its source file's parent directory, unless
      it's root-relative ('/x'), in which case it resolves against `root`
      (falling back to the source's parent dir when root is unknown, same
      fallback filesystem.check itself uses).
    - Everything else (external http(s) links) is source-independent and
      keyed on the URL alone.
    """
    # filesystem.check short-circuits docbook-xref: sentinels against the
    # corpus-wide id set before any path resolution -- they never depend on
    # source_file or root, same as an external URL.
    if url.startswith("docbook-xref:"):
        return url
    if link_type not in _SOURCE_INDEPENDENT:
        if link_type == LinkType.ANCHOR:
            return (url, source_file)
        path_part = url.split("#", 1)[0]
        if path_part.startswith("/"):
            base = str(Path(root)) if root is not None else str(Path(source_file).parent)
        else:
            base = str(Path(source_file).parent)
        return (url, base)
    return url


@dataclass
class LinkQueue:
    """Deduplicates URLs across sources and aggregates results.

    Two dedupe granularities coexist. Occurrence tracking (`_seen`, surfaced
    via `sources()`) is keyed on the raw URL string alone: every
    (source_file, line) that ever wrote this exact URL text, used by the
    fixer to rewrite every occurrence regardless of how checking deduped it.

    Check dispatch (`_pending`, surfaced via `pending()`) is keyed more
    finely: see `_dedupe_key`. A relative link, a root-relative link, or a
    pure anchor can resolve to a different target -- and so a different
    result -- depending on the source file, so each distinct resolution
    gets its own pending() entry and its own checked result.
    """

    # Every file the scan expanded from its targets. The fixer's moved-file
    # resolver indexes this rather than walking the tree a second time.
    corpus_files: list[Path] = field(default_factory=list)
    _seen: dict[str, list[tuple[str, int]]] = field(default_factory=dict, repr=False)
    _pending: dict[_DedupeKey, tuple[str, str, int, LinkType, int | None]] = field(
        default_factory=dict, repr=False
    )
    # Every (source_file, line) that shares a dedupe key, keyed the same way
    # as _pending -- so the fixer can find exactly the occurrences a given
    # result speaks for, not every occurrence of the URL string (see
    # sources_for_result).
    _pending_sources: dict[_DedupeKey, list[tuple[str, int]]] = field(
        default_factory=dict, repr=False
    )
    # (url, representative source_file, representative line) -> the dedupe
    # key that occurrence produced. A LinkResult always carries exactly its
    # key's representative source_file/line (see pending()), so this maps a
    # result straight back to its key without recomputing it.
    _key_by_representative: dict[tuple[str, str, int], _DedupeKey] = field(
        default_factory=dict, repr=False
    )
    _results: list[LinkResult] = field(default_factory=list, repr=False)

    def add(
        self,
        url: str,
        source_file: str,
        line: int,
        link_type: LinkType,
        *,
        cell: int | None = None,
        root: str | Path | None = None,
    ) -> bool:
        """Register a URL occurrence.

        Returns True if this occurrence's dedupe key (see `_dedupe_key`) is
        new and so needs checking -- not merely whether the raw URL string
        has been seen before, since the same URL string can need more than
        one check when its resolution depends on the source file.
        """
        if url not in self._seen:
            self._seen[url] = [(source_file, line)]
        else:
            self._seen[url].append((source_file, line))

        key = _dedupe_key(url, source_file, link_type, root)
        self._pending_sources.setdefault(key, []).append((source_file, line))
        if key not in self._pending:
            self._pending[key] = (url, source_file, line, link_type, cell)
            self._key_by_representative[(url, source_file, line)] = key
            return True
        return False

    def pending(self) -> list[tuple[str, str, int, LinkType, int | None]]:
        """Return (url, source_file, first_line, link_type, cell) for every distinct check."""
        return list(self._pending.values())

    def sources_for_result(self, url: str, source_file: str, line: int) -> list[tuple[str, int]]:
        """All (source_file, line) occurrences that share one result's dedupe key.

        A LinkResult's (url, source_file, line) is always exactly the
        representative occurrence recorded for its dedupe key (see `add`),
        so this looks the key up directly rather than recomputing it --
        `_dedupe_key` needs `root`, which a LinkResult does not carry.

        Falls back to `sources(url)` (every occurrence of the raw URL
        string, regardless of dedupe key) when no matching key is found --
        e.g. a LinkResult built outside the add()/pending() pipeline, as
        some tests do directly.
        """
        key = self._key_by_representative.get((url, source_file, line))
        if key is None:
            return self.sources(url)
        return list(self._pending_sources.get(key, []))

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
