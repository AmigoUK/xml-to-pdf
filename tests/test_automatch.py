"""Auto-matching must be deterministic and must hit the tags the shipped configs use."""

import json
import os

import pytest

from conftest import CONFIGS_DIR
from mapping import (
    HEADER_SLOTS, all_slots, auto_match_fields, DEFAULT_MAPPINGS, SLOT_KEYWORDS,
)
from xml_parser import discover_fields

LANGUAGES = ["polish", "german", "french", "spanish", "italian", "dutch"]


def _write_xml_from_config(path: str, config_name: str) -> tuple[str, dict[str, str]]:
    """Build an XML whose tags are exactly those a shipped config expects."""
    with open(os.path.join(CONFIGS_DIR, f"{config_name}.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    mappings = cfg["mappings"]
    header_tag = cfg["header_xpath"].replace(".//", "").replace("./", "")
    item_tag = cfg["item_xpath"].rsplit("/", 1)[-1]

    header_tags = sorted({mappings[s] for s in mappings if s in HEADER_SLOTS})
    item_tags = sorted({mappings[s] for s in mappings if s not in HEADER_SLOTS})

    header = "".join(f"      <{t}>VAL</{t}>\n" for t in header_tags)
    item_body = "".join(f"        <{t}>1,00</{t}>\n" for t in item_tags)
    items = "".join(f"      <{item_tag}>\n{item_body}      </{item_tag}>\n"
                    for _ in range(3))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Doc>\n  <Inv>\n'
        f"    <{header_tag}>\n{header}    </{header_tag}>\n"
        f"    <Lines>\n{items}    </Lines>\n  </Inv>\n</Doc>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path, mappings


@pytest.mark.parametrize("language", LANGUAGES)
def test_auto_match_reproduces_the_shipped_mapping(tmp_path, language):
    """Given a config's own tag names, the matcher must rediscover that mapping."""
    path, expected = _write_xml_from_config(str(tmp_path / f"{language}.xml"), language)
    matched, _ = auto_match_fields(discover_fields(path))

    wrong = {slot: (matched.get(slot), tag)
             for slot, tag in expected.items() if matched.get(slot) != tag}
    assert not wrong, f"{language}: slot -> (matched, expected) {wrong}"


@pytest.mark.parametrize("language", LANGUAGES + ["british_english"])
def test_auto_match_is_deterministic(tmp_path, language):
    """Set iteration order must not leak into the result."""
    path, _ = _write_xml_from_config(str(tmp_path / f"{language}.xml"), language)
    schema = discover_fields(path)

    first, _ = auto_match_fields(schema)
    for _ in range(15):
        again, _ = auto_match_fields(schema)
        assert again == first


def test_exact_tag_match_beats_a_longer_tag_containing_it(tmp_path):
    """`TowarKod` must win over `TowarKodEan128` for the product-code slot."""
    xml = (
        '<?xml version="1.0"?>\n<Doc><Inv><Naglowek><FakturaNumer>1</FakturaNumer>'
        "</Naglowek><Lines>"
        + "".join(
            "<Pozycja><TowarKod>A</TowarKod><TowarKodEan>B</TowarKodEan>"
            "<TowarKodEan128>C</TowarKodEan128></Pozycja>" for _ in range(2)
        )
        + "</Lines></Inv></Doc>\n"
    )
    path = tmp_path / "ambiguous.xml"
    path.write_text(xml, encoding="utf-8")

    matched, _ = auto_match_fields(discover_fields(str(path)))
    assert matched["item_code"] == "TowarKod"
    assert matched["barcode_ean128"] == "TowarKodEan128"
    assert matched["barcode_ean"] == "TowarKodEan"


def test_shorter_invoice_number_tag_wins_over_delivery_note_tag(tmp_path):
    """`FakturaNumer` is the invoice number; `FakturaNumeryWZ` is the delivery note."""
    xml = (
        '<?xml version="1.0"?>\n<Doc><Inv><Naglowek>'
        "<FakturaNumer>1</FakturaNumer><FakturaNumeryWZ>WZ/1</FakturaNumeryWZ>"
        "</Naglowek><Lines>"
        + "".join("<Pozycja><TowarKod>A</TowarKod></Pozycja>" for _ in range(2))
        + "</Lines></Inv></Doc>\n"
    )
    path = tmp_path / "wz.xml"
    path.write_text(xml, encoding="utf-8")

    matched, _ = auto_match_fields(discover_fields(str(path)))
    assert matched["invoice_number"] == "FakturaNumer"
    assert matched["delivery_note"] == "FakturaNumeryWZ"


def test_no_keyword_contains_whitespace():
    """A keyword with a space can never match a tag name."""
    offenders = {slot: [k for k in kws if k != k.strip() or " " in k]
                 for slot, kws in SLOT_KEYWORDS.items()}
    offenders = {s: k for s, k in offenders.items() if k}
    assert not offenders, f"whitespace in keywords: {offenders}"


def test_keywords_are_lowercase_and_unique_per_slot():
    for slot, kws in SLOT_KEYWORDS.items():
        assert all(k == k.lower() for k in kws), f"{slot} has non-lowercase keywords"
        assert len(kws) == len(set(kws)), f"{slot} has duplicate keywords"


def test_product_name_slots_share_one_keyword_vocabulary():
    """batch_/barcode_ product-name slots must know every tag item_name knows."""
    base = set(SLOT_KEYWORDS["item_name"])
    for slot in ("batch_product_name", "barcode_product_name"):
        assert base <= set(SLOT_KEYWORDS[slot]), (
            f"{slot} is missing {sorted(base - set(SLOT_KEYWORDS[slot]))}"
        )


def test_expiry_slots_share_one_keyword_vocabulary():
    base = set(SLOT_KEYWORDS["batch_expiry_date"])
    assert base <= set(SLOT_KEYWORDS["barcode_expiry"]), (
        f"barcode_expiry is missing {sorted(base - set(SLOT_KEYWORDS['barcode_expiry']))}"
    )


def test_every_slot_has_keywords_and_a_default_tag():
    for slot in all_slots():
        assert SLOT_KEYWORDS.get(slot), f"{slot} has no keywords"
        assert DEFAULT_MAPPINGS.get(slot), f"{slot} has no default tag"
