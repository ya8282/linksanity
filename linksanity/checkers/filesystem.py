"""Check internal links and anchor fragments against the local filesystem."""

from __future__ import annotations

import re
from pathlib import Path

from linksanity.queue import LinkResult, LinkStatus, LinkType


def check(
    url: str,
    source_file: str,
    line: int,
    link_type: LinkType,
    *,
    check_anchors: bool = False,
) -> LinkResult:
    """Resolve and validate an internal or anchor link.

    For ANCHOR links (#fragment), validates the fragment exists in the source
    file when check_anchors is True.
    For INTERNAL links (./path or ../path), validates the target file exists.
    """
    source_path = Path(source_file)

    # Split path and fragment
    fragment: str | None = None
    path_part = url
    if "#" in url:
        path_part, fragment = url.split("#", 1)

    # Resolve the target file
    if link_type == LinkType.ANCHOR or not path_part:
        target_path = source_path
    else:
        target_path = (source_path.parent / path_part).resolve()

    # Check file existence for non-pure-anchor links
    if path_part and not target_path.exists():
        return LinkResult(
            source_file=source_file,
            line=line,
            url=url,
            link_type=link_type,
            status=LinkStatus.BROKEN,
            error=f"file not found: {target_path}",
        )

    # Optionally validate anchor fragment
    if fragment and check_anchors and not _anchor_exists(target_path, fragment):
        return LinkResult(
            source_file=source_file,
            line=line,
            url=url,
            link_type=link_type,
            status=LinkStatus.BROKEN,
            error=f"anchor '#{fragment}' not found in {target_path.name}",
        )

    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=link_type,
        status=LinkStatus.OK,
    )


def _anchor_exists(path: Path, fragment: str) -> bool:
    """Return True if fragment matches a heading/ID in the file."""
    suffix = path.suffix.lower()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if suffix == ".md":
        return fragment in _md_anchors(content)
    if suffix == ".rst":
        return fragment in _rst_anchors(content)
    if suffix in (".html", ".htm"):
        return fragment in _html_ids(content)
    return False


def _md_anchors(content: str) -> set[str]:
    """Extract GitHub-style anchor slugs from Markdown headings."""
    anchors: set[str] = set()
    for line in content.splitlines():
        # ATX headings: # Heading, ## Heading, etc.
        m = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if m:
            anchors.add(_gh_slug(m.group(1)))
    return anchors


def _gh_slug(text: str) -> str:
    """Convert heading text to a GitHub Markdown anchor slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)   # remove special chars except - and _
    text = re.sub(r"\s+", "-", text.strip())
    return text


def _rst_anchors(content: str) -> set[str]:
    """Extract docutils-style IDs from all RST nodes that carry ids."""
    from io import StringIO

    from docutils.core import publish_doctree
    from docutils.utils import Reporter

    anchors: set[str] = set()
    try:
        doc = publish_doctree(
            content,
            settings_overrides={
                "report_level": Reporter.SEVERE_LEVEL,
                "halt_level": Reporter.SEVERE_LEVEL,
                "warning_stream": StringIO(),
            },
        )
        # Walk every Element node — titles, sections, and targets all carry ids
        from docutils.nodes import Element
        for node in doc.findall(Element):
            for id_ in node.get("ids", []):
                if isinstance(id_, str):
                    anchors.add(id_)
    except Exception:  # noqa: BLE001
        pass
    return anchors


def _html_ids(content: str) -> set[str]:
    """Extract all id= attribute values from HTML."""
    return set(re.findall(r'\bid=["\']([^"\']+)["\']', content))
