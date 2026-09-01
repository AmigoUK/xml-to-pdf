"""A discovered XPath must resolve back to the element discovery actually read.

Reported symptom: the GUI shows every field mapped, yet the PDF comes out with
empty boxes. Discovery walked the tree, found the real header/items and listed
their tags — but emitted a simplified `.//Tag` XPath that resolves to a
different element of the same name, so the renderer read nothing.
"""

import xml.etree.ElementTree as ET

import pytest

from conftest import pdf_words
from mapping import MappingConfig, auto_match_fields, all_slots
from pdf_renderer import xml_to_pdf
from xml_parser import InvoiceData, discover_fields, parse_invoice_tree

HEADER = {
    "SupplierName": "Test Supplier Ltd", "SupplierStreet": "1 Test St",
    "SupplierCity": "London", "SupplierPostalCode": "W1 1AA",
    "SupplierVatNumber": "GB 1", "BuyerName": "Buyer Ltd",
    "BuyerStreet": "2 Buy Rd", "BuyerCity": "Bristol",
    "BuyerPostalCode": "BS1 1AA", "BuyerVatNumber": "GB 2",
    "InvoiceNumber": "INV-9", "IssueDate": "2026-03-10", "DueDate": "2026-04-09",
    "PaymentMethod": "Bank Transfer", "Currency": "GBP", "DeliveryNote": "DN/1",
    "NetTotal": "100.00", "VatTotal": "20.00", "GrossTotal": "120.00",
}
ITEM = {
    "ProductCode": "PC-1", "ProductName": "Widget", "Quantity": "2",
    "Unit": "box", "UnitPrice": "1.50", "VatRate": "20%", "NetAmount": "3.00",
    "LotNumber": "LOT-1", "ExpiryDate": "2029-01-31", "EanCode": "5060412780011",
    "Ean128Code": "(01)05060412780011(17)290131(10)LOT-1",
}


def _tags(mapping):
    return "".join(f"<{k}>{v}</{k}>" for k, v in mapping.items())


def _items(count=3, tag="Item"):
    return "".join(f"<{tag}>{_tags(ITEM)}</{tag}>" for _ in range(count))


SHAPES = {
    # The reported failure: a decoy <Header> earlier in document order.
    "duplicate_header":
        f"<Document><Meta><Header><Note>metadata</Note></Header></Meta>"
        f"<Invoice><Header>{_tags(HEADER)}</Header>"
        f"<Items>{_items()}</Items></Invoice></Document>",
    # A repeating group that appears before the real items.
    "repeating_group_before_items":
        f"<Document><Invoice><Header>{_tags(HEADER)}</Header>"
        f"<Taxes><Tax><Rate>20</Rate></Tax><Tax><Rate>5</Rate></Tax></Taxes>"
        f"<Items>{_items()}</Items></Invoice></Document>",
    # Both at once.
    "decoy_header_and_repeating_group":
        f"<Document><Meta><Header><Note>x</Note></Header></Meta>"
        f"<Invoice><Header>{_tags(HEADER)}</Header>"
        f"<Contacts><Contact><Name>a</Name></Contact>"
        f"<Contact><Name>b</Name></Contact></Contacts>"
        f"<Items>{_items()}</Items></Invoice></Document>",
    # Shapes that already worked and must keep working.
    "baseline":
        f"<Document><Invoice><Header>{_tags(HEADER)}</Header>"
        f"<Items>{_items()}</Items></Invoice></Document>",
    "items_at_root":
        f"<Invoice><Header>{_tags(HEADER)}</Header>{_items()}</Invoice>",
    "header_after_items":
        f"<Document><Invoice><Items>{_items()}</Items>"
        f"<Header>{_tags(HEADER)}</Header></Invoice></Document>",
    # The Polish fast path must be as robust as the generic one.
    "polish_with_decoy_header":
        "<Dokument><Archiwum><Naglowek><Uwaga>stare</Uwaga></Naglowek></Archiwum>"
        "<Faktura><Naglowek><DostawcaNazwa>Test Supplier Ltd</DostawcaNazwa>"
        "<FakturaNumer>INV-9</FakturaNumer></Naglowek><Pozycje>"
        + "".join("<Pozycja><TowarKod>PC-1</TowarKod>"
                  "<TowarNazwa>Widget</TowarNazwa></Pozycja>" for _ in range(3))
        + "</Pozycje></Faktura></Dokument>",
    "namespaced":
        f'<Document xmlns="urn:x:1"><Invoice><Header>{_tags(HEADER)}</Header>'
        f"<Items>{_items()}</Items></Invoice></Document>",
}


@pytest.fixture
def shape(tmp_path):
    def _write(name: str) -> str:
        path = tmp_path / f"{name}.xml"
        path.write_text('<?xml version="1.0" encoding="UTF-8"?>' + SHAPES[name],
                        encoding="utf-8")
        return str(path)
    return _write


ALL_SHAPES = sorted(SHAPES)
# Shapes carrying the full English field set, used by the render/mapping tests.
FULL_SHAPES = [n for n in ALL_SHAPES if n != "polish_with_decoy_header"]


@pytest.mark.parametrize("name", ALL_SHAPES)
def test_discovered_header_xpath_resolves_to_the_element_that_was_read(shape, name):
    """The XPath must find an element carrying the tags discovery reported."""
    path = shape(name)
    schema = discover_fields(path)
    root = parse_invoice_tree(path)

    found = root.find(schema.header_xpath)
    assert found is not None, f"header_xpath {schema.header_xpath!r} resolves to nothing"

    present = {child.tag for child in found}
    missing = [t for t in schema.header_tags if t not in present]
    assert not missing, (
        f"{schema.header_xpath!r} resolved to the wrong element; "
        f"it lacks {missing[:5]}"
    )


@pytest.mark.parametrize("name", ALL_SHAPES)
def test_discovered_item_xpath_resolves_to_the_elements_that_were_read(shape, name):
    path = shape(name)
    schema = discover_fields(path)
    root = parse_invoice_tree(path)

    found = root.findall(schema.item_xpath)
    assert found, f"item_xpath {schema.item_xpath!r} resolves to nothing"
    assert len(found) == schema.item_count

    present = {child.tag for child in found[0]}
    missing = [t for t in schema.item_tags if t not in present]
    assert not missing, (
        f"{schema.item_xpath!r} resolved to the wrong elements; it lacks {missing[:5]}"
    )


@pytest.mark.parametrize("name", FULL_SHAPES)
def test_the_real_items_group_is_chosen(shape, name):
    """A small repeating group elsewhere must not be mistaken for the line items."""
    schema = discover_fields(shape(name))
    assert "ProductCode" in schema.item_tags, (
        f"picked the wrong repeating group; got {schema.item_tags[:5]}"
    )
    assert schema.item_count == 3


@pytest.mark.parametrize("name", FULL_SHAPES)
def test_a_fully_mapped_invoice_renders_its_values(shape, fonts_dir, tmp_path, name):
    """Auto-match reporting every slot mapped must mean a populated PDF."""
    path = shape(name)
    schema = discover_fields(path)
    matched, _ = auto_match_fields(schema)
    assert len(matched) == len(all_slots()), "fixture should map every slot"

    config = MappingConfig(mappings=matched, header_xpath=schema.header_xpath,
                           item_xpath=schema.item_xpath)
    out = str(tmp_path / f"{name}.pdf")
    xml_to_pdf(path, out, mapping_config=config, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    for expected in ("Test", "Supplier", "INV-9", "PC-1", "Widget"):
        assert expected in text, f"{expected!r} missing from the PDF for shape {name}"


def test_a_decoy_header_does_not_win(shape):
    """Narrow regression test for the reported bug."""
    path = shape("duplicate_header")
    schema = discover_fields(path)
    header = parse_invoice_tree(path).find(schema.header_xpath)

    assert header.find("SupplierName") is not None
    assert header.find("Note") is None, "resolved to the <Meta> decoy"


def test_invoice_data_reads_the_header_through_the_discovered_xpath(shape):
    path = shape("duplicate_header")
    schema = discover_fields(path)

    inv = InvoiceData(path, header_xpath=schema.header_xpath,
                      item_xpath=schema.item_xpath)
    assert inv.h("SupplierName") == "Test Supplier Ltd"
    assert inv.h("InvoiceNumber") == "INV-9"
    assert len(inv.items) == 3


def test_the_polish_fast_path_also_avoids_a_decoy_header(shape):
    """The Naglowek/Pozycja shortcut must not hand back an ambiguous XPath."""
    path = shape("polish_with_decoy_header")
    schema = discover_fields(path)
    header = parse_invoice_tree(path).find(schema.header_xpath)

    assert header is not None
    assert header.find("DostawcaNazwa") is not None
    assert header.find("Uwaga") is None, "resolved to the <Archiwum> decoy"

    inv = InvoiceData(path, header_xpath=schema.header_xpath,
                      item_xpath=schema.item_xpath)
    assert inv.h("DostawcaNazwa") == "Test Supplier Ltd"
    assert len(inv.items) == 3
