"""
mapping.py
==========
MappingConfig dataclass, default field mappings, and JSON persistence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xml_parser import DiscoveredSchema


# Slot categories for the GUI grouping
SLOT_CATEGORIES = {
    "Supplier": [
        "supplier_name",
        "supplier_street",
        "supplier_city",
        "supplier_postal_code",
        "supplier_nip",
    ],
    "Buyer": [
        "buyer_name",
        "buyer_street",
        "buyer_city",
        "buyer_postal_code",
        "buyer_nip",
    ],
    "Invoice Details": [
        "invoice_number",
        "issue_date",
        "due_date",
        "payment_type",
        "currency",
        "delivery_note",
    ],
    "Totals": [
        "net_total",
        "vat_total",
        "gross_total",
    ],
    "Items Table": [
        "item_code",
        "item_name",
        "item_qty",
        "item_unit",
        "item_unit_price",
        "item_vat_rate",
        "item_net_total",
    ],
    "Batch Details": [
        "batch_product_name",
        "batch_lot_number",
        "batch_expiry_date",
    ],
    "Barcodes": [
        "barcode_ean128",
        "barcode_ean",
        "barcode_product_name",
        "barcode_product_code",
        "barcode_batch",
        "barcode_expiry",
    ],
}

# Which slots read from header vs item elements
HEADER_SLOTS = set()
ITEM_SLOTS = set()
for cat, slots in SLOT_CATEGORIES.items():
    for s in slots:
        if cat in ("Items Table", "Batch Details", "Barcodes"):
            ITEM_SLOTS.add(s)
        else:
            HEADER_SLOTS.add(s)

# Default mapping: slot_id -> XML tag name (current hardcoded behavior)
DEFAULT_MAPPINGS: dict[str, str] = {
    # Supplier
    "supplier_name": "DostawcaNazwa",
    "supplier_street": "DostawcaAdresUlica",
    "supplier_city": "DostawcaAdresMiejscowosc",
    "supplier_postal_code": "DostawcaAdresKodPocztowy",
    "supplier_nip": "DostawcaNIP",
    # Buyer
    "buyer_name": "NabywcaNazwa",
    "buyer_street": "NabywcaAdresUlica",
    "buyer_city": "NabywcaAdresMiejscowosc",
    "buyer_postal_code": "NabywcaAdresKodPocztowy",
    "buyer_nip": "NabywcaNIP",
    # Invoice Details
    "invoice_number": "FakturaNumer",
    "issue_date": "FakturaDataWystawienia",
    "due_date": "FakturaDataPlatnosci",
    "payment_type": "FakturaTypPlatnosci",
    "currency": "FakturaWaluta",
    "delivery_note": "FakturaNumeryWZ",
    # Totals
    "net_total": "FakturaWartoscNetto",
    "vat_total": "FakturaWartoscVat",
    "gross_total": "FakturaWartoscBrutto",
    # Items Table
    "item_code": "TowarKod",
    "item_name": "TowarNazwa",
    "item_qty": "Ilosc",
    "item_unit": "TowarJm",
    "item_unit_price": "CenaNetto",
    "item_vat_rate": "StawkaVat",
    "item_net_total": "WartoscNetto",
    # Batch Details
    "batch_product_name": "TowarNazwa",
    "batch_lot_number": "TowarDostawaNumerSerii",
    "batch_expiry_date": "TowarDostawaDataWaznosci",
    # Barcodes
    "barcode_ean128": "TowarKodEan128",
    "barcode_ean": "TowarKodEan",
    "barcode_product_name": "TowarNazwa",
    "barcode_product_code": "TowarKod",
    "barcode_batch": "TowarDostawaNumerSerii",
    "barcode_expiry": "TowarDostawaDataWaznosci",
}


# Keyword-based fuzzy matching: slot -> list of lowercase substrings to look for in tags
SLOT_KEYWORDS: dict[str, list[str]] = {
    # Supplier
    "supplier_name": ["dostawcanazwa", "suppliername", "vendorname", "sprzedawcanazwa", "sellername"],
    "supplier_street": ["dostawcaadresulica", "supplierstreet", "vendorstreet", "sprzedawcaulica"],
    "supplier_city": ["dostawcaadresmiejscowosc", "suppliercity", "vendorcity", "sprzedawcamiasto"],
    "supplier_postal_code": ["dostawcaadrescodpocztowy", "supplierpostal", "vendorpostal", "sprzedawcakod"],
    "supplier_nip": ["dostawcanip", "suppliernip", "suppliervatnumber", "vendornip", "sprzedawcanip"],
    # Buyer
    "buyer_name": ["nabywcanazwa", "buyername", "customername", "odbiorca", "purchasername"],
    "buyer_street": ["nabywcaadresulica", "buyerstreet", "customerstreet", "odbiorcaulica"],
    "buyer_city": ["nabywcaadresmiejscowosc", "buyercity", "customercity", "odbiorcamiasto"],
    "buyer_postal_code": ["nabywcaadrescodpocztowy", "buyerpostal", "customerpostal", "odbiorcakod"],
    "buyer_nip": ["nabywcanip", "buyernip", "buyervatnumber", "customernip", "odbiorcnip"],
    # Invoice Details
    "invoice_number": ["fakturanumer", "invoicenumber", "invoiceno", "nrdokumentu", "docnumber"],
    "issue_date": ["fakturadatawystawienia", "issuedate", "invoicedate", "datadokumentu", "datawystawienia"],
    "due_date": ["fakturadataplatnosci", "duedate", "paymentdate", "dataplatnosci", "terminplatnosci"],
    "payment_type": ["fakturatypplatnosci", "paymenttype", "paymentmethod", "formaplat", "typplatnosci"],
    "currency": ["fakturawaluta", "currency", "waluta", "currencycode"],
    "delivery_note": ["fakturanumerywz", "deliverynote", "wznumber", "numerywz", "lieferschein"],
    # Totals
    "net_total": ["fakturawartoscnetto", "nettotal", "totalnet", "wartoscnetto", "summanetto"],
    "vat_total": ["fakturawartoscvat", "vattotal", "totalvat", "wartoscvat", "summavat", "totaltax"],
    "gross_total": ["fakturawartoscbrutto", "grosstotal", "totalbrutto", "wartoscbrutto", "summabrutto", "totaldue"],
    # Items Table
    "item_code": ["towarkod", "itemcode", "productcode", "sku", "artnr", "artikelnr"],
    "item_name": ["towarnazwa", "itemname", "productname", "description", "artikelname", "bezeichnung"],
    "item_qty": ["ilosc", "quantity", "qty", "menge", "itemqty"],
    "item_unit": ["towarjm", "itemunit", "uom", "einheit", "jednostka"],
    "item_unit_price": ["cenanetto", "unitprice", "priceperunit", "einzelpreis", "cenajed"],
    "item_vat_rate": ["stawkavat", "vatrate", "taxrate", "mwst", "steuersatz"],
    "item_net_total": ["wartoscnetto", "netamount", "linetotal", "nettowert", "linenet"],
    # Batch Details
    "batch_product_name": ["towarnazwa", "batchproduct", "productname"],
    "batch_lot_number": ["towardostawanumerserii", "lotnumber", "batchnumber", "chargennr", "numerpartii", "lotno"],
    "batch_expiry_date": ["towardostawadatawaznosci", "expirydate", "expdate", "bestbefore", "datawaznosci", "mhd"],
    # Barcodes
    "barcode_ean128": ["towarkodean128", "ean128", "gs1128", "gs1barcode"],
    "barcode_ean": ["towarkodean", "eancode", "ean13", "gtin"],
    "barcode_product_name": ["towarnazwa"],
    "barcode_product_code": ["towarkod", "productcode"],
    "barcode_batch": ["towardostawanumerserii", "batchnumber", "lotnumber"],
    "barcode_expiry": ["towardostawadatawaznosci", "expirydate", "expdate"],
}


@dataclass
class MappingConfig:
    name: str = "Default Polish Invoice"
    mappings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MAPPINGS))
    include_barcodes: bool = True
    font_dir: str | None = None
    header_xpath: str = ".//Naglowek"
    item_xpath: str = ".//Pozycja"

    def get(self, slot_id: str) -> str:
        """Return the XML tag mapped to a slot, or empty string if unmapped."""
        return self.mappings.get(slot_id, "")


def auto_match_fields(schema: DiscoveredSchema) -> tuple[dict[str, str], dict[str, str]]:
    """Intelligently match discovered XML tags to PDF slots.

    Priority:
    1. Exact match — DEFAULT_MAPPINGS[slot] exists literally in discovered tags
    2. Keyword match — normalize tag to lowercase, check substring matching
    3. Section awareness — header slots match header tags, item slots match item tags

    Returns:
        (matched_mappings, match_reasons) — reasons dict explains why each slot matched
    """
    header_set = set(schema.header_tags)
    item_set = set(schema.item_tags)
    all_tags = header_set | item_set

    matched: dict[str, str] = {}
    reasons: dict[str, str] = {}

    for slot in _all_slots():
        default_tag = DEFAULT_MAPPINGS.get(slot, "")

        # Determine which tags this slot should match against (section-aware)
        if slot in HEADER_SLOTS:
            section_tags = header_set
            section_name = "header"
        else:
            section_tags = item_set
            section_name = "item"

        # Priority 1: Exact match with default mapping
        if default_tag and default_tag in section_tags:
            matched[slot] = default_tag
            reasons[slot] = "exact"
            continue

        # Also check if exact match exists in all tags (cross-section)
        if default_tag and default_tag in all_tags:
            matched[slot] = default_tag
            reasons[slot] = "exact (cross-section)"
            continue

        # Priority 2: Keyword-based fuzzy match
        keywords = SLOT_KEYWORDS.get(slot, [])
        if keywords:
            best_match = _keyword_match(keywords, section_tags)
            if best_match:
                matched[slot] = best_match
                reasons[slot] = "keyword"
                continue

            # Try cross-section keyword match
            best_match = _keyword_match(keywords, all_tags)
            if best_match:
                matched[slot] = best_match
                reasons[slot] = "keyword (cross-section)"
                continue

    return matched, reasons


def _keyword_match(keywords: list[str], tags: set[str]) -> str | None:
    """Find best keyword match among tags. Longest keyword match wins."""
    best_tag = None
    best_keyword_len = 0

    for tag in tags:
        tag_lower = tag.lower()
        for keyword in keywords:
            if keyword in tag_lower and len(keyword) > best_keyword_len:
                best_keyword_len = len(keyword)
                best_tag = tag

    return best_tag


def _all_slots() -> list[str]:
    """Return all slot IDs in order."""
    slots = []
    for _cat, cat_slots in SLOT_CATEGORIES.items():
        slots.extend(cat_slots)
    return slots


def save_config(path: str, config: MappingConfig) -> None:
    """Save a MappingConfig to a JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = asdict(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_config(path: str) -> MappingConfig:
    """Load a MappingConfig from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return MappingConfig(
        name=data.get("name", "Unnamed"),
        mappings=data.get("mappings", dict(DEFAULT_MAPPINGS)),
        include_barcodes=data.get("include_barcodes", True),
        font_dir=data.get("font_dir"),
        header_xpath=data.get("header_xpath", ".//Naglowek"),
        item_xpath=data.get("item_xpath", ".//Pozycja"),
    )
