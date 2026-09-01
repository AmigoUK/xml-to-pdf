"""Pagination must keep every row inside the printable area and count pages honestly."""

import re

import pytest
from reportlab.lib.units import mm

from conftest import pdf_page_count, pdf_words
from pdf_renderer import FOOTER_MARGIN_Y, H, xml_to_pdf

# In `pdftotext -bbox` space the origin is the page's top-left corner, so the
# footer margin measured from the bottom becomes this distance from the top.
CONTENT_BOTTOM_LIMIT = H - FOOTER_MARGIN_Y


def _table_words(words):
    """Words that can only come from an items/batch table row (the product code)."""
    return [w for w in words if w.text.startswith("PC-") or w.text.startswith("LOT-")]


def _declared_totals(words):
    """Every "Page X of Y" pair found in the footers, as (x, y) ints."""
    pairs = []
    for page in sorted({w.page for w in words}):
        line = " ".join(w.text for w in words if w.page == page)
        for m in re.finditer(r"Page\s+(\d+)\s+of\s+(\d+)", line):
            pairs.append((int(m.group(1)), int(m.group(2))))
    return pairs


@pytest.mark.parametrize("items", [13, 40, 60, 80])
def test_table_rows_never_cross_the_footer_margin(make_invoice, fonts_dir, tmp_path, items):
    """Row heights are measured with the same style used to draw, so nothing overflows."""
    xml = make_invoice(items=items)
    out = str(tmp_path / "p.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    offenders = [w for w in _table_words(pdf_words(out)) if w.ymax > CONTENT_BOTTOM_LIMIT]
    assert not offenders, (
        f"{len(offenders)} table words drawn below the footer margin, e.g. {offenders[:3]}"
    )


@pytest.mark.parametrize("items", [13, 60])
def test_nothing_is_drawn_outside_the_page(make_invoice, fonts_dir, tmp_path, items):
    xml = make_invoice(items=items)
    out = str(tmp_path / "p.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    for w in pdf_words(out):
        assert w.ymin >= 0, f"drawn above the page top: {w}"
        assert w.ymax <= H, f"drawn below the page bottom: {w}"


def test_declared_page_total_matches_the_real_page_count(make_invoice, fonts_dir, tmp_path):
    """Footers must not claim "Page 5 of 4"."""
    xml = make_invoice(items=20, items_with_barcode=5)
    out = str(tmp_path / "p.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    real = pdf_page_count(out)
    pairs = _declared_totals(pdf_words(out))
    assert pairs, "no page footers found"
    assert all(total == real for _, total in pairs), (
        f"real page count {real}, footers declare {sorted({t for _, t in pairs})}"
    )
    assert [num for num, _ in pairs] == list(range(1, real + 1))


def test_no_blank_barcode_page_when_only_some_items_have_codes(
        make_invoice, fonts_dir, tmp_path):
    """20 items, 5 with Ean128Code — the 5 cards fit one page, so no empty page follows."""
    xml = make_invoice(items=20, items_with_barcode=5)
    out = str(tmp_path / "p.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    words = pdf_words(out)
    header_band = 20 * mm  # the navy title bar at the top of a continuation page
    for page in sorted({w.page for w in words}):
        body = [w for w in words if w.page == page
                and w.ymin > header_band and w.ymax < CONTENT_BOTTOM_LIMIT]
        assert body, f"page {page} carries nothing but a header and a footer"


def test_every_item_with_a_code_gets_a_barcode_card(make_invoice, fonts_dir, tmp_path):
    xml = make_invoice(items=12, items_with_barcode=12)
    out = str(tmp_path / "p.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert text.count("GS1-128:") == 12
