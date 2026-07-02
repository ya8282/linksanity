"""Extract links and IDs from DocBook XML files using stdlib xml.parsers.expat.

Line numbers are obtained directly from expat's `CurrentLineNumber` during
element-start callbacks. `xml.etree.ElementTree.XMLParser` cannot be used for
this: on CPython its `XMLParser`/`TreeBuilder` classes are backed by the
`_elementtree` C accelerator, which calls expat's callbacks internally and
never invokes an overridden `_start`/`_end` method on a Python subclass (the
classic "subclass XMLParser, capture self.parser.CurrentLineNumber" recipe
silently no-ops under the accelerator). Driving `xml.parsers.expat` directly
sidesteps that and also avoids needing to store line numbers on Element
objects, which the C-accelerated Element type does not allow (no arbitrary
attribute assignment).
"""

from __future__ import annotations

import warnings
import xml.parsers.expat
from pathlib import Path

_DOCBOOK_NS = "http://docbook.org/ns/docbook"
_XLINK_HREF_ATTR = "{http://www.w3.org/1999/xlink}href"
_XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"

# Top-level DocBook elements. Namespace-stripped, so this covers both
# unnamespaced DocBook 4 and namespaced DocBook 5 documents.
_DOCBOOK_ROOT_TAGS = {
    "book",
    "article",
    "chapter",
    "section",
    "sect1",
    "sect2",
    "sect3",
    "sect4",
    "sect5",
    "part",
    "preface",
    "appendix",
    "glossary",
    "bibliography",
    "reference",
    "refentry",
    "set",
    "topic",
    "index",
}


def _fixname(name: str) -> str:
    """Convert expat's namespace-separated name to ElementTree's Clark notation.

    With `ParserCreate(None, "}")`, expat reports namespaced names as
    "uri}local". This mirrors ElementTree's own `_fixname` to turn that into
    "{uri}local".
    """
    if "}" in name:
        return "{" + name
    return name


def _local_name(tag: str) -> str:
    """Strip a Clark-notation namespace prefix, returning the local tag name."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _parse(path: Path) -> tuple[list[tuple[str, int]], set[str]] | None:
    """Parse a DocBook XML file, returning (links, ids), or None on failure.

    Failure covers: unreadable file, malformed XML, and well-formed XML whose
    root is not recognized as DocBook. Every failure path emits a
    `[linksanity]`-prefixed warning.
    """
    try:
        content = path.read_bytes()
    except OSError as e:
        warnings.warn(f"[linksanity] cannot read {path}: {e}", stacklevel=3)
        return None

    links: list[tuple[str, int]] = []
    ids: set[str] = set()
    state = {"root_seen": False, "is_docbook": False}

    parser = xml.parsers.expat.ParserCreate(None, "}")

    def start_element(name: str, attrs: dict[str, str]) -> None:
        tag = _fixname(name)
        local = _local_name(tag)
        fixed_attrs = {_fixname(k): v for k, v in attrs.items()}

        if not state["root_seen"]:
            state["root_seen"] = True
            state["is_docbook"] = local in _DOCBOOK_ROOT_TAGS or tag.startswith(
                f"{{{_DOCBOOK_NS}}}"
            )

        line = parser.CurrentLineNumber

        if local == "ulink":
            url = fixed_attrs.get("url")
            if url:
                links.append((url, line))
        elif local == "link":
            href = fixed_attrs.get(_XLINK_HREF_ATTR)
            if href:
                links.append((href, line))
        elif local == "xref":
            linkend = fixed_attrs.get("linkend")
            if linkend:
                links.append((f"docbook-xref:{linkend}", line))

        plain_id = fixed_attrs.get("id")
        if plain_id:
            ids.add(plain_id)
        xml_id = fixed_attrs.get(_XML_ID_ATTR)
        if xml_id:
            ids.add(xml_id)

    parser.StartElementHandler = start_element

    try:
        parser.Parse(content, True)
    except xml.parsers.expat.ExpatError as e:
        warnings.warn(f"[linksanity] DocBook XML parse error in {path}: {e}", stacklevel=3)
        return None

    if not state["is_docbook"]:
        warnings.warn(f"[linksanity] skipping {path}: not a DocBook XML document", stacklevel=3)
        return None

    return links, ids


def extract_links(path: Path) -> list[tuple[str, int]]:
    """Return (url, line) pairs extracted from a DocBook XML file.

    Extracts `<ulink url="...">` and `<link xlink:href="...">` as normal
    URLs. `<xref linkend="foo">` is returned as the sentinel string
    "docbook-xref:foo" for later corpus-wide ID resolution.

    Files that are not DocBook XML (unrecognized root element/namespace) and
    files that fail to parse emit a warning and return an empty list.
    """
    result = _parse(path)
    if result is None:
        return []
    links, _ = result
    return links


def extract_ids(path: Path) -> set[str]:
    """Return every `id`/`xml:id` attribute value found in a DocBook XML file.

    Files that are not DocBook XML (unrecognized root element/namespace) and
    files that fail to parse emit a warning and return an empty set.
    """
    result = _parse(path)
    if result is None:
        return set()
    _, ids = result
    return ids
