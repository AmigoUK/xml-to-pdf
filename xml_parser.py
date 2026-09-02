"""
xml_parser.py
=============
Invoice XML parsing and field discovery.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def _strip_namespaces(root: ET.Element) -> ET.Element:
    """Drop namespace prefixes from every tag, in place.

    Invoice schemas such as UBL declare a default namespace on the root, which
    turns every tag into "{urn:...}Header" and makes plain-name XPaths (and the
    tag names shown in the GUI) miss. Since the mapping works on local names
    only, flattening the tree once here keeps everything downstream simple.
    """
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_invoice_tree(xml_path: str) -> ET.Element:
    """Parse an invoice XML and return its namespace-free root element.

    Documents carrying a DOCTYPE are refused: an invoice has no need for a DTD,
    and rejecting it here means entity-expansion and external-entity payloads
    never reach the parser regardless of the Python version in use.
    """
    with open(xml_path, "rb") as f:
        head = f.read(8192)
    if _DOCTYPE.search(head):
        raise ValueError(
            f"{xml_path} carries a DOCTYPE declaration (DTD/ENTITY) and was "
            "refused. Invoices need no DTD, and entity declarations can be "
            "malicious."
        )

    return _strip_namespaces(ET.parse(xml_path).getroot())


@dataclass
class DiscoveredSchema:
    """Result of XML structure discovery."""
    header_xpath: str                              # e.g. ".//Naglowek"
    item_xpath: str                                # e.g. ".//Pozycja"
    header_tags: list[str]                         # leaf tags under header
    item_tags: list[str]                           # leaf tags under one item
    item_count: int                                # number of items found
    sample_values: dict[str, str] = field(default_factory=dict)  # tag -> first non-empty text


class InvoiceData:
    """Invoice data parsed from XML."""

    def __init__(self, xml_path: str, header_xpath: str = ".//Naglowek",
                 item_xpath: str = ".//Pozycja"):
        root = parse_invoice_tree(xml_path)
        self.header = root.find(header_xpath)
        # An invoice with no lines is unusual but legal (a credit note, for
        # instance), so it renders with empty tables rather than failing.
        self.items = root.findall(item_xpath)

        if self.header is None:
            raise ValueError(
                f"No element at xpath '{header_xpath}' in {xml_path}")

    def h(self, tag: str) -> str:
        """Read a value from the invoice header."""
        el = self.header.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def item_val(item, tag: str) -> str:
        """Read a value from an invoice line item."""
        el = item.find(tag)
        return el.text.strip() if el is not None and el.text else ""


def _collect_leaf_tags(element: ET.Element) -> list[str]:
    """Return tag names of direct children that are leaf nodes (have text, no sub-elements)."""
    tags = []
    for child in element:
        if len(child) == 0:  # leaf node
            tags.append(child.tag)
    return tags


def _collect_sample_values(element: ET.Element) -> dict[str, str]:
    """Collect first non-empty text value for each leaf child."""
    samples: dict[str, str] = {}
    for child in element:
        if len(child) == 0 and child.text and child.text.strip():
            if child.tag not in samples:
                samples[child.tag] = child.text.strip()
    return samples


def _find_repeating_group(root: ET.Element) -> tuple[ET.Element | None, str | None]:
    """Find the element group that holds the invoice line items.

    Every repeating group in the document is scored and the richest one wins.
    Taking the first group found in breadth-first order was not good enough: a
    <Taxes> or <Contacts> block sitting before <Items> would be picked as the
    line items, and the items table then rendered empty.

    Line items carry far more fields than an incidental repeating block, so the
    number of leaf tags on a member decides, with the repeat count breaking
    ties.

    Returns (parent_element, repeating_tag) or (None, None) if there is none.
    """
    best: tuple[int, int, ET.Element, str] | None = None

    queue = [root]
    while queue:
        parent = queue.pop(0)
        tag_counts = Counter(child.tag for child in parent)
        for tag, count in tag_counts.items():
            if count < 2:
                continue
            member = next(child for child in parent if child.tag == tag)
            score = (len(_collect_leaf_tags(member)), count)
            if best is None or score > best[:2]:
                best = (score[0], score[1], parent, tag)
        for child in parent:
            if len(child) > 0:
                queue.append(child)

    if best is None:
        return None, None
    return best[2], best[3]


def discover_fields(xml_path: str) -> DiscoveredSchema:
    """Walk an invoice XML and return discovered schema with field names grouped by section.

    Algorithm:
    1. Fast path: if Naglowek/Pozycja exist, use them (backward compat)
    2. Generic: detect repeating group (items) and header by tree walking
    3. Collect sample values for heuristic matching
    """
    root = parse_invoice_tree(xml_path)

    # Fast path: try known Polish invoice tags. The element with the most fields
    # wins, and its XPath is built the same unambiguous way as on the generic
    # path — returning a bare ".//Naglowek" would resolve to whichever element
    # of that name comes first, which need not be the one read here.
    naglowki = root.findall(".//Naglowek")
    pozycje = root.findall(".//Pozycja")

    if naglowki and pozycje:
        header_el = max(naglowki, key=lambda el: len(_collect_leaf_tags(el)))
        first_item = pozycje[0]

        header_tags = _collect_leaf_tags(header_el)
        item_tags = _collect_leaf_tags(first_item)

        # Collect sample values from both header and first item
        sample_values = _collect_sample_values(header_el)
        sample_values.update(_collect_sample_values(first_item))

        item_parent = _find_parent(root, first_item)
        item_xpath = (_build_xpath(root, item_parent, "Pozycja")
                      if item_parent is not None else ".//Pozycja")

        return DiscoveredSchema(
            header_xpath=_build_element_xpath(root, header_el),
            item_xpath=item_xpath,
            header_tags=header_tags,
            item_tags=item_tags,
            item_count=len(root.findall(item_xpath)),
            sample_values=sample_values,
        )

    # Generic path: find repeating group
    items_parent, item_tag = _find_repeating_group(root)

    if items_parent is not None and item_tag is not None:
        # Build xpath for items
        item_elements = [child for child in items_parent if child.tag == item_tag]
        item_count = len(item_elements)
        first_item_el = item_elements[0]
        item_tags = _collect_leaf_tags(first_item_el)

        # Build xpath: find path from root to items_parent, then add item_tag
        item_xpath = _build_xpath(root, items_parent, item_tag)

        # Header: look for sibling of items_parent or items_parent itself minus items
        header_el, header_xpath = _find_header(root, items_parent, item_tag)
        header_tags = _collect_leaf_tags(header_el) if header_el is not None else []

        # Collect sample values
        sample_values = {}
        if header_el is not None:
            sample_values = _collect_sample_values(header_el)
        sample_values.update(_collect_sample_values(first_item_el))

        return DiscoveredSchema(
            header_xpath=header_xpath or "",
            item_xpath=item_xpath,
            header_tags=header_tags,
            item_tags=item_tags,
            item_count=item_count,
            sample_values=sample_values,
        )

    # Fallback: return empty schema
    return DiscoveredSchema(
        header_xpath="",
        item_xpath="",
        header_tags=[],
        item_tags=[],
        item_count=0,
        sample_values={},
    )


def _build_xpath(root: ET.Element, parent: ET.Element, child_tag: str) -> str:
    """Build an XPath selecting parent's children named child_tag."""
    if parent is root:
        return f"./{child_tag}"
    return f"{_build_element_xpath(root, parent)}/{child_tag}"


def _find_path(root: ET.Element, target: ET.Element) -> list[ET.Element] | None:
    """Find the path from root to target element (list of elements)."""
    if root is target:
        return [root]
    for child in root:
        result = _find_path(child, target)
        if result is not None:
            return [root] + result
    return None


def _find_header(root: ET.Element, items_parent: ET.Element,
                 item_tag: str) -> tuple[ET.Element | None, str | None]:
    """Find the header element — a sibling of the item group or the parent minus items.

    Strategy:
    1. If items_parent has non-item children with leaf nodes, use items_parent as header
    2. Otherwise look for siblings of items_parent that have leaf children
    """
    # Check if items_parent has non-item leaf children
    non_item_leaves = [child for child in items_parent
                       if child.tag != item_tag and len(child) == 0]
    if non_item_leaves:
        return items_parent, _build_element_xpath(root, items_parent)

    # Check for non-item child elements that have their own leaves
    for child in items_parent:
        if child.tag != item_tag and len(child) > 0 and _collect_leaf_tags(child):
            return child, _build_element_xpath(root, child)

    # Look at parent of items_parent
    parent_of_parent = _find_parent(root, items_parent)
    if parent_of_parent is not None:
        for sibling in parent_of_parent:
            if sibling is not items_parent and _collect_leaf_tags(sibling):
                return sibling, _build_element_xpath(root, sibling)

    return None, None


def _build_element_xpath(root: ET.Element, target: ET.Element) -> str:
    """Build an XPath that resolves to exactly this element, and no other.

    The full path from the root is spelled out, with a positional predicate
    wherever a tag repeats among its siblings. The previous version returned
    the deepest tag alone (".//Header"), which resolves to whichever element of
    that name comes first in the document — so a decoy <Header> elsewhere in
    the file silently won, and every header field on the PDF came out empty
    even though discovery had read the right element.
    """
    path = _find_path(root, target)
    if not path or len(path) < 2:
        return f".//{target.tag}"

    parts = []
    for parent, child in zip(path, path[1:]):
        siblings = [c for c in parent if c.tag == child.tag]
        if len(siblings) > 1:
            parts.append(f"{child.tag}[{siblings.index(child) + 1}]")
        else:
            parts.append(child.tag)
    return "./" + "/".join(parts)


def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """Find the parent of target element in the tree."""
    for child in root:
        if child is target:
            return root
        result = _find_parent(child, target)
        if result is not None:
            return result
    return None
