"""Parsing must cope with namespaced documents, empty item lists and hostile input."""

import pytest

from conftest import pdf_words
from pdf_renderer import xml_to_pdf
from xml_parser import InvoiceData, discover_fields

NS = "urn:example:invoice:1.0"


def test_namespaced_invoice_is_parsed(make_invoice, british_config):
    """UBL-style documents declare a default namespace on the root element."""
    xml = make_invoice(items=3, namespace=NS)
    inv = InvoiceData(xml, header_xpath=british_config.header_xpath,
                      item_xpath=british_config.item_xpath)

    assert inv.h("InvoiceNumber") == "INV-TEST"
    assert len(inv.items) == 3
    assert InvoiceData.item_val(inv.items[0], "ProductCode") == "PC-0001"


def test_namespaced_invoice_renders(make_invoice, fonts_dir, tmp_path, british_config):
    xml = make_invoice(items=3, namespace=NS)
    out = str(tmp_path / "ns.pdf")

    xml_to_pdf(xml, out, mapping_config=british_config, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "INV-TEST" in text and "PC-0001" in text


def test_discover_fields_sees_through_a_namespace(make_invoice):
    xml = make_invoice(items=4, namespace=NS)
    schema = discover_fields(xml)

    assert schema.item_count == 4
    assert "InvoiceNumber" in schema.header_tags
    assert "ProductCode" in schema.item_tags
    assert "{" not in " ".join(schema.header_tags + schema.item_tags), (
        "tag names must be reported without namespace braces"
    )


def test_invoice_with_no_items_still_parses(make_invoice, british_config):
    """A credit note can legitimately carry zero lines."""
    xml = make_invoice(items=0)
    inv = InvoiceData(xml, header_xpath=british_config.header_xpath,
                      item_xpath=british_config.item_xpath)

    assert inv.items == []
    assert inv.h("InvoiceNumber") == "INV-TEST"


def test_invoice_with_no_items_renders_empty_tables(make_invoice, fonts_dir,
                                                    tmp_path, british_config):
    xml = make_invoice(items=0)
    out = str(tmp_path / "empty.pdf")

    xml_to_pdf(xml, out, mapping_config=british_config, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "Description" in text, "the items table header should still be drawn"
    assert "TOTAL:" in text


def test_missing_header_is_reported_clearly(make_invoice, british_config):
    xml = make_invoice(items=2)
    with pytest.raises(ValueError, match="NoSuchHeader"):
        InvoiceData(xml, header_xpath=".//NoSuchHeader",
                    item_xpath=british_config.item_xpath)


def test_entity_expansion_is_refused(tmp_path):
    """A billion-laughs payload must not be expanded."""
    entities = "\n".join(
        f'<!ENTITY a{i} "{"&a%d;" % (i - 1) * 10}">' for i in range(1, 9)
    )
    xml = (
        '<?xml version="1.0"?>\n<!DOCTYPE Document [\n<!ENTITY a0 "AAAAAAAAAA">\n'
        f"{entities}\n]>\n"
        "<Document><Invoice><Header><SupplierName>&a8;</SupplierName></Header>"
        "<Items><Item><ProductCode>A</ProductCode></Item></Items></Invoice></Document>"
    )
    path = tmp_path / "bomb.xml"
    path.write_text(xml, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        InvoiceData(str(path), header_xpath=".//Header",
                    item_xpath="./Invoice/Items/Item")
    assert "entit" in str(excinfo.value).lower() or "amplification" in str(excinfo.value).lower()


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    xml = (
        '<?xml version="1.0"?>\n<!DOCTYPE Document [\n'
        f'<!ENTITY xxe SYSTEM "file://{secret}">\n]>\n'
        "<Document><Invoice><Header><SupplierName>&xxe;</SupplierName></Header>"
        "<Items><Item><ProductCode>A</ProductCode></Item></Items></Invoice></Document>"
    )
    path = tmp_path / "xxe.xml"
    path.write_text(xml, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        InvoiceData(str(path), header_xpath=".//Header",
                    item_xpath="./Invoice/Items/Item")
    assert "TOP-SECRET" not in str(excinfo.value)
