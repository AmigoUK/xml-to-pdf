"""
Shared fixtures: font directories, synthetic invoice XML, PDF geometry probes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS_DIR = os.path.join(PROJECT_ROOT, "configs")

SYSTEM_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    r"C:\Windows\Fonts",
]


def _find_system_font(filename: str) -> str | None:
    for d in SYSTEM_FONT_DIRS:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            return path
    return None


@pytest.fixture(scope="session")
def core_fonts_dir(tmp_path_factory) -> str:
    """A font dir holding only Regular + Bold, as Debian's fonts-dejavu-core ships."""
    regular = _find_system_font("DejaVuSans.ttf")
    bold = _find_system_font("DejaVuSans-Bold.ttf")
    if not regular or not bold:
        pytest.skip("DejaVu Sans Regular/Bold not installed on this system")

    d = tmp_path_factory.mktemp("fonts_core")
    shutil.copy(regular, os.path.join(d, "DejaVuSans.ttf"))
    shutil.copy(bold, os.path.join(d, "DejaVuSans-Bold.ttf"))
    return str(d)


@pytest.fixture(scope="session")
def fonts_dir(core_fonts_dir) -> str:
    """Default font dir for render tests — deliberately without the italic faces."""
    return core_fonts_dir


# ── Invoice XML building ─────────────────────────────────────

HEADER_FIELDS = {
    "SupplierName": "Test Supplier Ltd",
    "SupplierStreet": "1 Test Street",
    "SupplierCity": "London",
    "SupplierPostalCode": "W1 1AA",
    "SupplierVatNumber": "GB 111",
    "BuyerName": "Test Buyer Ltd",
    "BuyerStreet": "2 Buy Road",
    "BuyerCity": "Bristol",
    "BuyerPostalCode": "BS1 1AA",
    "BuyerVatNumber": "GB 222",
    "InvoiceNumber": "INV-TEST",
    "IssueDate": "2026-03-10",
    "DueDate": "2026-04-09",
    "PaymentMethod": "Bank Transfer",
    "Currency": "GBP",
    "DeliveryNote": "DN/1",
    "NetTotal": "100.00",
    "VatTotal": "20.00",
    "GrossTotal": "120.00",
}

ITEM_DESCRIPTION = "Product number {i} with a reasonably long description"


def _item_fields(i: int, with_ean128: bool) -> dict[str, str]:
    fields = {
        "ProductCode": f"PC-{i:04d}",
        "ProductName": ITEM_DESCRIPTION.format(i=i),
        "Quantity": str(i),
        "Unit": "box",
        "UnitPrice": "1.50",
        "VatRate": "20%",
        "NetAmount": f"{i * 1.5:.2f}",
        "LotNumber": f"LOT-{i:04d}",
        "ExpiryDate": "2029-01-31",
        "EanCode": f"50604127800{i % 100:02d}",
    }
    if with_ean128:
        fields["Ean128Code"] = f"(01)0506041278{i:04d}(17)290131(10)LOT-{i:04d}"
    return fields


def build_invoice_xml(
    path: str,
    items: int = 3,
    items_with_barcode: int | None = None,
    header_overrides: dict[str, str] | None = None,
    item_overrides: dict[str, str] | None = None,
    namespace: str | None = None,
) -> str:
    """Write a British-English invoice XML and return its path.

    items_with_barcode: how many of the leading items carry Ean128Code (default: all).
    """
    header = dict(HEADER_FIELDS)
    header.update(header_overrides or {})
    if items_with_barcode is None:
        items_with_barcode = items

    ns_attr = f' xmlns="{namespace}"' if namespace else ""

    def esc(v: str) -> str:
        return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    header_xml = "".join(
        f"      <{k}>{esc(v)}</{k}>\n" for k, v in header.items()
    )

    items_xml = ""
    for i in range(1, items + 1):
        fields = _item_fields(i, with_ean128=i <= items_with_barcode)
        fields.update(item_overrides or {})
        body = "".join(f"        <{k}>{esc(v)}</{k}>\n" for k, v in fields.items())
        items_xml += f"      <Item>\n{body}      </Item>\n"

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Document{ns_attr}>\n  <Invoice>\n"
        f"    <Header>\n{header_xml}    </Header>\n"
        f"    <Items>\n{items_xml}    </Items>\n"
        "  </Invoice>\n</Document>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


@pytest.fixture
def make_invoice(tmp_path):
    """Factory writing an invoice XML into tmp_path."""
    counter = {"n": 0}

    def _make(**kwargs) -> str:
        counter["n"] += 1
        path = str(tmp_path / f"invoice_{counter['n']}.xml")
        return build_invoice_xml(path, **kwargs)

    return _make


@pytest.fixture
def british_config():
    """A fresh copy of the shipped British English mapping config."""
    from mapping import load_config

    return load_config(os.path.join(CONFIGS_DIR, "british_english.json"))


# ── PDF inspection ───────────────────────────────────────────

class Word:
    __slots__ = ("page", "text", "xmin", "ymin", "xmax", "ymax")

    def __init__(self, page, text, xmin, ymin, xmax, ymax):
        self.page = page
        self.text = text
        self.xmin = xmin
        self.ymin = ymin  # distance from page TOP, in points
        self.xmax = xmax
        self.ymax = ymax

    def __repr__(self):
        return f"<Word p{self.page} {self.text!r} y={self.ymin:.1f}..{self.ymax:.1f}>"


def pdf_words(pdf_path: str) -> list[Word]:
    """Extract every word with its bounding box via `pdftotext -bbox`.

    Coordinates are in PDF points with the origin at the top-left of the page.
    """
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext (poppler-utils) not installed")

    out = subprocess.run(
        ["pdftotext", "-bbox", pdf_path, "-"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")

    root = ET.fromstring(out)
    ns = {"h": "http://www.w3.org/1999/xhtml"}
    words: list[Word] = []
    for page_num, page in enumerate(root.iter(f"{{{ns['h']}}}page"), 1):
        for w in page.iter(f"{{{ns['h']}}}word"):
            words.append(Word(
                page_num,
                (w.text or "").strip(),
                float(w.get("xMin")), float(w.get("yMin")),
                float(w.get("xMax")), float(w.get("yMax")),
            ))
    return words


def pdf_page_count(pdf_path: str) -> int:
    """Page count via `pdfinfo`, falling back to counting bbox pages."""
    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", pdf_path], capture_output=True,
                             check=True).stdout.decode()
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    return max((w.page for w in pdf_words(pdf_path)), default=0)
