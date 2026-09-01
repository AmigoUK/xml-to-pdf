"""Text blocks must stay inside the boxes they are given."""

import pytest
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from conftest import pdf_words
from pdf_renderer import H, W, draw_para, fit_paragraph, register_fonts, xml_to_pdf

LONG_NAME = ("Pemberton Whitfield Marchmont Holdings International Group of "
             "Companies Limited Trading Division Europe and Overseas Branches")


@pytest.fixture
def style(core_fonts_dir):
    register_fonts(core_fonts_dir)
    return ParagraphStyle("T", fontName="DJV", fontSize=9.5, leading=11)


def test_fit_paragraph_never_exceeds_the_box(style):
    _, height = fit_paragraph(LONG_NAME, style, max_w=60 * mm, max_h=16 * mm)
    assert height <= 16 * mm


def test_fit_paragraph_keeps_short_text_untouched(style):
    para, height = fit_paragraph("Short Ltd", style, max_w=60 * mm, max_h=16 * mm)
    assert 0 < height <= 16 * mm
    assert "Short Ltd" in para.text


def test_fit_paragraph_marks_dropped_text_with_an_ellipsis(style):
    para, _ = fit_paragraph(LONG_NAME, style, max_w=40 * mm, max_h=11)
    assert para.text.endswith("…") or para.text.endswith("...")


def test_draw_para_reports_a_height_within_the_box(style, tmp_path):
    c = canvas.Canvas(str(tmp_path / "x.pdf"))
    used = draw_para(c, LONG_NAME, 20 * mm, 200 * mm, 60 * mm, style, max_h=16 * mm)
    assert used <= 16 * mm


def test_long_supplier_name_stays_inside_the_header_bar(
        make_invoice, fonts_dir, tmp_path):
    """The navy bar is 28mm tall; an over-long name used to spill above the page."""
    xml = make_invoice(items=3, header_overrides={"SupplierName": LONG_NAME})
    out = str(tmp_path / "long.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    for w in pdf_words(out):
        assert w.ymin >= 0, f"drawn above the page top: {w}"


def test_all_four_header_badges_are_drawn_side_by_side(make_invoice, fonts_dir, tmp_path):
    """The currency badge used to be laid out on top of the payment badge."""
    xml = make_invoice(items=3)
    out = str(tmp_path / "badges.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    words = [w for w in pdf_words(out) if w.page == 1]
    badges = {}
    for label in ("ISSUE", "DUE", "PAYMENT", "CURRENCY"):
        hits = [w for w in words if w.text == label]
        assert len(hits) == 1, f"expected one {label!r} badge label, found {len(hits)}"
        badges[label] = hits[0]

    spans = sorted((w.xmin, w.xmax, label) for label, w in badges.items())
    for (_, prev_max, prev_label), (next_min, _, next_label) in zip(spans, spans[1:]):
        assert prev_max <= next_min, f"{prev_label} badge overlaps {next_label}"

    # And the values must survive, not just the labels.
    text = " ".join(w.text for w in words)
    assert "Bank" in text and "GBP" in text


def _overlapping_pairs(words, tolerance=1.0):
    """Pairs of words whose bounding boxes genuinely overlap (i.e. overprint)."""
    pairs = []
    for i, a in enumerate(words):
        for b in words[i + 1:]:
            x_overlap = min(a.xmax, b.xmax) - max(a.xmin, b.xmin)
            y_overlap = min(a.ymax, b.ymax) - max(a.ymin, b.ymin)
            if x_overlap > tolerance and y_overlap > tolerance:
                pairs.append((a, b))
    return pairs


def test_long_party_names_do_not_overprint_the_address_lines(
        make_invoice, fonts_dir, tmp_path):
    """An over-long name used to spill past its 16mm slot and print over the street."""
    xml = make_invoice(items=3, header_overrides={
        "SupplierName": LONG_NAME, "BuyerName": LONG_NAME + " And More Words Still",
    })
    out = str(tmp_path / "boxes.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    words = [w for w in pdf_words(out) if w.page == 1]
    table_header = [w for w in words if w.text == "Description"]
    assert table_header, "items table header not found"
    header_top = min(w.ymin for w in table_header)

    # Everything above the items table: the navy bar, the badges, the party boxes.
    upper = [w for w in words if w.ymax < header_top]
    offenders = _overlapping_pairs(upper)
    assert not offenders, f"{len(offenders)} overprinted word pairs, e.g. {offenders[:3]}"
