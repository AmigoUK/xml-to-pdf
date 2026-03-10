"""
xml_parser.py
=============
Invoice XML parsing and field discovery.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field


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
    """Sparsowane dane faktury z XML."""

    def __init__(self, xml_path: str, header_xpath: str = ".//Naglowek",
                 item_xpath: str = ".//Pozycja"):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        self.header = root.find(header_xpath)
        self.items = root.findall(item_xpath)

        if self.header is None:
            raise ValueError(f"Brak elementu na xpath '{header_xpath}' w {xml_path}")
        if not self.items:
            raise ValueError(f"Brak elementow na xpath '{item_xpath}' w {xml_path}")

    def h(self, tag: str) -> str:
        """Pobiera wartosc z naglowka faktury."""
        el = self.header.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def item_val(item, tag: str) -> str:
        """Pobiera wartosc z pozycji faktury."""
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
    """Find the first element whose children contain a repeating tag (items group).

    Returns (parent_element, repeating_tag) or (None, None) if not found.
    """
    # BFS through the tree
    queue = [root]
    while queue:
        parent = queue.pop(0)
        child_tags = [child.tag for child in parent]
        tag_counts = Counter(child_tags)
        # Find tags that appear more than once
        for tag, count in tag_counts.items():
            if count > 1:
                return parent, tag
        # Go deeper
        for child in parent:
            if len(child) > 0:  # has sub-elements
                queue.append(child)
    return None, None


def discover_fields(xml_path: str) -> DiscoveredSchema:
    """Walk an invoice XML and return discovered schema with field names grouped by section.

    Algorithm:
    1. Fast path: if Naglowek/Pozycja exist, use them (backward compat)
    2. Generic: detect repeating group (items) and header by tree walking
    3. Collect sample values for heuristic matching
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Fast path: try known Polish invoice tags
    header_el = root.find(".//Naglowek")
    first_item = root.find(".//Pozycja")

    if header_el is not None and first_item is not None:
        header_tags = _collect_leaf_tags(header_el)
        item_tags = _collect_leaf_tags(first_item)
        item_count = len(root.findall(".//Pozycja"))

        # Collect sample values from both header and first item
        sample_values = _collect_sample_values(header_el)
        sample_values.update(_collect_sample_values(first_item))

        return DiscoveredSchema(
            header_xpath=".//Naglowek",
            item_xpath=".//Pozycja",
            header_tags=header_tags,
            item_tags=item_tags,
            item_count=item_count,
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
    """Build an XPath string from root to parent/child_tag."""
    path = _find_path(root, parent)
    if path:
        parts = [el.tag for el in path[1:]]  # skip root
        parts.append(child_tag)
        return ".//" + "/".join(parts) if not parts[:-1] else "./" + "/".join(parts)
    return f".//{child_tag}"


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
    """Build an XPath to reach a specific element from root."""
    path = _find_path(root, target)
    if path and len(path) > 1:
        parts = [el.tag for el in path[1:]]
        return ".//" + parts[-1]  # simplified xpath using deepest tag
    return f".//{target.tag}"


def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """Find the parent of target element in the tree."""
    for child in root:
        if child is target:
            return root
        result = _find_parent(child, target)
        if result is not None:
            return result
    return None
