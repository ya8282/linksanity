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
    link_style: str | None = None,
    cell: int | None = None,
) -> LinkResult:
    """Resolve and validate an internal or anchor link.

    For ANCHOR links (#fragment), validates the fragment exists in the source
    file when check_anchors is True.
    For INTERNAL links (./path or ../path), validates the target file exists.
    If the direct path doesn't exist and link_style is set (mkdocs, docusaurus,
    sphinx), also tries that SSG's built-URL conventions (extensionless links,
    directory-index links) against the source files on disk.
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
        resolved = _resolve_via_preset(source_path.parent, path_part, link_style)
        if resolved is not None:
            target_path = resolved
        else:
            return LinkResult(
                source_file=source_file,
                line=line,
                url=url,
                link_type=link_type,
                status=LinkStatus.BROKEN,
                error=f"file not found: {target_path}",
                cell=cell,
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
            cell=cell,
        )

    return LinkResult(
        source_file=source_file,
        line=line,
        url=url,
        link_type=link_type,
        status=LinkStatus.OK,
        cell=cell,
    )


def _resolve_via_preset(base_dir: Path, path_part: str, link_style: str | None) -> Path | None:
    """Try SSG built-URL conventions for a relative link that didn't resolve directly.

    Docs authors often write links the way the built site serves them
    (extensionless, or as a directory), not as the raw source-file path.
    Returns the first candidate source file that exists, or None.
    """
    if not link_style:
        return None

    stripped = path_part.rstrip("/")
    candidates: list[str]
    if link_style == "mkdocs":
        candidates = [f"{stripped}.md", f"{stripped}/index.md"]
    elif link_style == "docusaurus":
        candidates = [f"{stripped}.md", f"{stripped}.mdx", f"{stripped}/index.md"]
    elif link_style == "sphinx":
        if stripped.endswith(".html"):
            base = stripped[: -len(".html")]
            candidates = [f"{base}.rst", f"{base}.md", f"{base}/index.rst"]
        else:
            candidates = [f"{stripped}.rst", f"{stripped}/index.rst"]
    else:
        return None

    for candidate in candidates:
        candidate_path = (base_dir / candidate).resolve()
        if candidate_path.exists():
            return candidate_path
    return None


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
