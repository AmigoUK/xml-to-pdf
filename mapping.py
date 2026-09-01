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
    "supplier_name": "SupplierName",
    "supplier_street": "SupplierStreet",
    "supplier_city": "SupplierCity",
    "supplier_postal_code": "SupplierPostalCode",
    "supplier_nip": "SupplierVatNumber",
    # Buyer
    "buyer_name": "BuyerName",
    "buyer_street": "BuyerStreet",
    "buyer_city": "BuyerCity",
    "buyer_postal_code": "BuyerPostalCode",
    "buyer_nip": "BuyerVatNumber",
    # Invoice Details
    "invoice_number": "InvoiceNumber",
    "issue_date": "IssueDate",
    "due_date": "DueDate",
    "payment_type": "PaymentMethod",
    "currency": "Currency",
    "delivery_note": "DeliveryNote",
    # Totals
    "net_total": "NetTotal",
    "vat_total": "VatTotal",
    "gross_total": "GrossTotal",
    # Items Table
    "item_code": "ProductCode",
    "item_name": "ProductName",
    "item_qty": "Quantity",
    "item_unit": "Unit",
    "item_unit_price": "UnitPrice",
    "item_vat_rate": "VatRate",
    "item_net_total": "NetAmount",
    # Batch Details
    "batch_product_name": "ProductName",
    "batch_lot_number": "LotNumber",
    "batch_expiry_date": "ExpiryDate",
    # Barcodes
    "barcode_ean128": "Ean128Code",
    "barcode_ean": "EanCode",
    "barcode_product_name": "ProductName",
    "barcode_product_code": "ProductCode",
    "barcode_batch": "LotNumber",
    "barcode_expiry": "ExpiryDate",
}


# ── Keyword-based fuzzy matching ─────────────────────────────
# slot -> lowercase substrings to look for inside a tag name.
#
# Several slots describe the same real-world field seen from different sections
# (a product name appears in the items table, the batch table and on the barcode
# card). Those share one vocabulary below instead of keeping near-copies that
# drift apart — the copies used to be shorter than the original, which is why
# German ArtikelBezeichnung and Dutch ArtikelNaam matched item_name but not
# batch_product_name.

_PRODUCT_NAME = [
    "productname", "itemname", "description", "artikelname", "bezeichnung",
    "artikelbezeichnung", "nomarticle", "designationproduit", "nombreproducto",
    "descripcion", "nomeprodotto", "descrizione", "productnaam", "artikelnaam",
    "omschrijving", "towarnazwa",
]
_PRODUCT_CODE = [
    "productcode", "itemcode", "sku", "artikelnr", "artnr", "artikelnummer",
    "codearticle", "codeproduit", "codigoproducto", "codigoarticulo",
    "codiceprodotto", "codicearticolo", "artikelcode", "towarkod",
]
_LOT_NUMBER = [
    "lotnumber", "lotno", "batchnumber", "chargennr", "chargenummer", "numerolot",
    "numerolote", "numerolotto", "lotnummer", "partijnummer",
    "towardostawanumerserii", "numerpartii",
]
_EXPIRY_DATE = [
    "expirydate", "expdate", "bestbefore", "verfallsdatum", "mindesthaltbarkeit",
    "mhd", "haltbarkeitsdatum", "dateperemption", "dluo", "fechacaducidad",
    "fechavencimiento", "datascadenza", "houdbaarheidsdatum", "vervaldatum",
    "towardostawadatawaznosci", "datawaznosci",
]


def _keywords(*groups) -> list[str]:
    """Merge keyword groups, dropping duplicates but keeping the order."""
    merged: list[str] = []
    for group in groups:
        items = [group] if isinstance(group, str) else group
        for kw in items:
            if kw not in merged:
                merged.append(kw)
    return merged


SLOT_KEYWORDS: dict[str, list[str]] = {
    # Supplier — EN, DE, FR, ES, IT, NL, PL
    "supplier_name": ["suppliername", "vendorname", "sellername", "lieferantname", "lieferantename", "fournisseurnom", "nomfournisseur", "proveedornombre", "nombreproveedor", "fornitorenome", "nomefornito", "leveranciernaam", "dostawcanazwa", "sprzedawcanazwa"],
    "supplier_street": ["supplierstreet", "supplieraddress", "vendorstreet", "lieferantstrasse", "fournisseurrue", "proveedorcalle", "fornitorevia", "leverancierstraat", "dostawcaadresulica", "sprzedawcaulica"],
    "supplier_city": ["suppliercity", "vendorcity", "lieferantstadt", "lieferantort", "fournisseurville", "proveedorciudad", "fornitorecitt", "leverancierstad", "dostawcaadresmiejscowosc", "sprzedawcamiasto"],
    "supplier_postal_code": ["supplierpostal", "supplierpostcode", "vendorpostal", "lieferantplz", "fournisseurcodepostal", "proveedorcodigopostal", "fornitorecap", "leverancierpostcode", "dostawcaadreskodpocztowy", "sprzedawcakodpocztowy", "sprzedawcakod"],
    "supplier_nip": ["suppliervatnumber", "suppliervat", "suppliernip", "vendornip", "lieferantumsatzsteuer", "lieferantsteuernr", "lieferantustid", "fournisseurtva", "proveedornif", "proveedorcif", "fornitoreiva", "fornitorecodicefiscale", "leverancierbtw", "dostawcanip", "sprzedawcanip"],
    # Buyer — EN, DE, FR, ES, IT, NL, PL
    "buyer_name": ["buyername", "customername", "purchasername", "kaeufername", "kaeufer", "kundenname", "empfaengername", "acheteurnom", "nomacheteur", "clientnom", "compradornombre", "compradornom", "nombrecomprador", "clientenombre", "acquirentenome", "nomeacquirente", "clientenome", "kopernaam", "klantnaam", "nabywcanazwa", "odbiorcanazwa", "odbiorca"],
    "buyer_street": ["buyerstreet", "customerstreet", "kaeuferstrasse", "kundenstrasse", "acheteurrue", "compradorcalle", "acquirentevia", "koperstraat", "nabywcaadresulica", "odbiorcaulica"],
    "buyer_city": ["buyercity", "customercity", "kaeuferstadt", "kundenort", "acheteurville", "compradorciudad", "acquirentecitt", "koperstad", "nabywcaadresmiejscowosc", "odbiorcamiasto"],
    "buyer_postal_code": ["buyerpostal", "buyerpostcode", "customerpostal", "kaeuferplz", "kundenplz", "acheteurcodepostal", "compradorcodigopostal", "acquirentecap", "koperpostcode", "nabywcaadreskodpocztowy", "odbiorcakodpocztowy", "odbiorcakod"],
    "buyer_nip": ["buyervatnumber", "buyervat", "buyernip", "customernip", "kaeuferumsatzsteuer", "kaeferustid", "kundensteuernr", "acheteurtva", "compradornif", "compradorcif", "acquirenteiva", "koperbtw", "nabywcanip", "odbiorcanip"],
    # Invoice Details — EN, DE, FR, ES, IT, NL, PL
    "invoice_number": ["invoicenumber", "invoiceno", "rechnungsnummer", "rechnungnr", "numerofacture", "facturenumero", "numerofactura", "facturanumero", "numerofattura", "fatturanumero", "factuurnummer", "fakturanumer", "nrdokumentu", "docnumber"],
    "issue_date": ["issuedate", "invoicedate", "rechnungsdatum", "ausstellungsdatum", "datefacture", "dateemission", "fechafactura", "fechaemision", "datafattura", "dataemissione", "factuurdatum", "fakturadatawystawienia", "datadokumentu", "datawystawienia"],
    "due_date": ["duedate", "paymentdate", "paymentdue", "faelligkeitsdatum", "zahlungsdatum", "dateecheance", "datepaiement", "fechavencimiento", "scadenza", "datascadenza", "vervaldatum", "betaaldatum", "fakturadataplatnosci", "dataplatnosci", "terminplatnosci"],
    "payment_type": ["paymentmethod", "paymenttype", "zahlungsart", "zahlungsmethode", "modepaiement", "moyenpaiement", "formadepago", "formapago", "metodopagamento", "modalitapagamento", "betaalwijze", "betaalmethode", "fakturatypplatnosci", "formaplat", "typplatnosci"],
    "currency": ["currency", "currencycode", "waehrung", "devise", "moneda", "divisa", "valuta", "munteenheid", "fakturawaluta", "waluta"],
    "delivery_note": ["deliverynote", "deliverynumber", "lieferschein", "lieferscheinnr", "bonlivraison", "albaranentrega", "albaran", "bolladiconsegna", "pakbon", "leveringsbon", "fakturanumerywz", "numerywz", "wznumber"],
    # Totals — EN, DE, FR, ES, IT, NL, PL
    "net_total": ["nettotal", "totalnet", "nettogesamt", "nettobetrag", "gesamtnetto", "totalhorsttaxe", "totalht", "totalneto", "importeneto", "totalenetto", "importonetto", "nettototaal", "totaalnetto", "fakturawartoscnetto", "wartoscnetto", "summanetto"],
    "vat_total": ["vattotal", "totalvat", "totaltax", "mwstgesamt", "gesamtmwst", "umsatzsteuergesamt", "gesamtumsatzsteuer", "totaltva", "montanttva", "totaliva", "importeiva", "totaleiva", "importoiva", "btwtotaal", "totaalbtw", "fakturawartoscvat", "wartoscvat", "summavat"],
    "gross_total": ["grosstotal", "totalbrutto", "totaldue", "grandtotal", "bruttogesamt", "gesamtbrutto", "totalttc", "montantttc", "totalbruto", "importebruto", "totalelordo", "importolordo", "brutototaal", "totaalbruto", "fakturawartoscbrutto", "wartoscbrutto", "summabrutto"],
    # Items Table — EN, DE, FR, ES, IT, NL, PL
    "item_code": _PRODUCT_CODE,
    "item_name": _PRODUCT_NAME,
    "item_qty": ["quantity", "qty", "menge", "anzahl", "quantite", "cantidad", "quantita", "aantal", "hoeveelheid", "ilosc"],
    "item_unit": ["unit", "uom", "unitofmeasure", "einheit", "mengeneinheit", "unite", "unidad", "unita", "eenheid", "towarjm", "jednostka"],
    "item_unit_price": ["unitprice", "priceperunit", "einzelpreis", "stueckpreis", "prixunitaire", "preciounitario", "prezzounitario", "eenheidsprijs", "stuksprijs", "cenanetto", "cenajed"],
    "item_vat_rate": ["vatrate", "taxrate", "mwstsatz", "mwst", "steuersatz", "tauxtva", "tipoiva", "aliquotaiva", "btwpercentage", "btwtarief", "stawkavat"],
    "item_net_total": ["netamount", "linetotal", "linenet", "nettowert", "positionsnetto", "montantnet", "importeneto", "importonetto", "nettobedrag", "regelbedrag", "wartoscnetto"],
    # Batch Details — share the product/lot/expiry vocabularies
    "batch_product_name": _keywords("batchproduct", _PRODUCT_NAME),
    "batch_lot_number": _LOT_NUMBER,
    "batch_expiry_date": _EXPIRY_DATE,
    # Barcodes — share the same vocabularies again
    "barcode_ean128": ["ean128code", "ean128", "gs1128", "gs1barcode", "towarkodean128"],
    "barcode_ean": ["eancode", "ean13", "gtin", "ean", "towarkodean"],
    "barcode_product_name": _PRODUCT_NAME,
    "barcode_product_code": _PRODUCT_CODE,
    "barcode_batch": _LOT_NUMBER,
    "barcode_expiry": _EXPIRY_DATE,
}


# The single source of truth for the default XPaths. load_config() and the GUI
# both read these instead of repeating literals, which used to leave three
# different "defaults" in the codebase (.//Header, .//Naglowek, ./Invoice/...).
DEFAULT_HEADER_XPATH = ".//Header"
DEFAULT_ITEM_XPATH = "./Invoice/Items/Item"


@dataclass
class MappingConfig:
    name: str = "British English Invoice"
    mappings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MAPPINGS))
    include_barcodes: bool = True
    font_dir: str | None = None
    header_xpath: str = DEFAULT_HEADER_XPATH
    item_xpath: str = DEFAULT_ITEM_XPATH

    def get(self, slot_id: str) -> str:
        """Return the XML tag mapped to a slot, or empty string if unmapped."""
        return self.mappings.get(slot_id, "")


def resolve_xpaths(schema: DiscoveredSchema | None,
                   loaded: MappingConfig | None) -> tuple[str, str]:
    """Decide which header/item XPaths a config being built should carry.

    What the parser discovered in the loaded XML wins, because it describes the
    document actually being converted. Whatever it could not determine falls
    back to the config the user selected, and only then to the shared defaults.
    The GUI used to fall back to hardcoded Polish XPaths here, which silently
    overrode the XPaths of any config the user had loaded.
    """
    header = (schema.header_xpath if schema else "") or ""
    item = (schema.item_xpath if schema else "") or ""

    if not header:
        header = (loaded.header_xpath if loaded else "") or DEFAULT_HEADER_XPATH
    if not item:
        item = (loaded.item_xpath if loaded else "") or DEFAULT_ITEM_XPATH

    return header, item


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

    for slot in all_slots():
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


def _keyword_match(keywords: list[str], tags) -> str | None:
    """Find the best keyword match among tags.

    Ranked by: a keyword equal to the whole tag beats a mere substring hit, then
    the longer keyword, then the shorter tag. That last rule is what separates
    TowarKod from TowarKodEan128 and CodiceEan from CodiceEan128.

    Tags are iterated in sorted order and ties are resolved by the first one, so
    the result never depends on set iteration order — the previous version could
    return a different tag on every run because Python randomises string hashes.
    """
    best_rank: tuple[bool, int, int] | None = None
    best_tag: str | None = None

    for tag in sorted(tags):
        tag_lower = tag.lower()
        for keyword in keywords:
            if keyword not in tag_lower:
                continue
            rank = (keyword == tag_lower, len(keyword), -len(tag_lower))
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_tag = tag

    return best_tag


def all_slots() -> list[str]:
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
        header_xpath=data.get("header_xpath") or DEFAULT_HEADER_XPATH,
        item_xpath=data.get("item_xpath") or DEFAULT_ITEM_XPATH,
    )
