"""
pdf_renderer.py
===============
PDF drawing functions for invoice generation, parameterized by MappingConfig.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import replace
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import code128

from paths import font_search_paths
from xml_parser import InvoiceData
from mapping import MappingConfig, DEFAULT_MAPPINGS

# ── Colors ──────────────────────────────────────────────────
NAVY     = HexColor("#1B2A4A")
ACCENT   = HexColor("#2E86DE")
LIGHT_BG = HexColor("#F0F4F8")
MID_GRAY = HexColor("#6B7B8D")
DARK_TXT = HexColor("#1A1A2E")
LINE_GRY = HexColor("#D5DDE5")
ROW_ALT  = HexColor("#F7F9FC")
WHITE    = white

FONT   = "DJV"
FONT_B = "DJV-Bold"

# Kept for backwards compatibility; paths.font_search_paths() is the live list
# and additionally covers a frozen bundle's own directory.
FONT_SEARCH_PATHS = font_search_paths()

W, H = A4

# ── Pagination constants ─────────────────────────────────────
FOOTER_MARGIN_Y = 30 * mm
CONT_HEADER_H = 20 * mm
CONT_TOP_Y = H - CONT_HEADER_H - 18 * mm
TOTALS_BLOCK_H = 50 * mm

# ── Barcode page layout ──────────────────────────────────────
BARCODE_HEADER_H = 20 * mm
BARCODE_TOP_Y = H - BARCODE_HEADER_H - 18 * mm
BARCODE_CARD_H = 40 * mm
BARCODE_CARD_GAP = 3 * mm
BARCODE_BOTTOM_LIMIT = 30 * mm

# Width reserved for the invoice number in the header bar, and the width the
# supplier name gets to wrap in beside it.
INVOICE_NUMBER_MAX_W = 165


# Faces the renderer actually draws with. The italic ones are a bonus: nothing in
# the layout uses them, so a Debian fonts-dejavu-core install (Regular + Bold only)
# must be enough to produce a PDF.
REQUIRED_FONTS = {
    "DJV":      "DejaVuSans.ttf",
    "DJV-Bold": "DejaVuSans-Bold.ttf",
}
OPTIONAL_FONTS = {
    "DJV-Oblique":     "DejaVuSans-Oblique.ttf",
    "DJV-BoldOblique": "DejaVuSans-BoldOblique.ttf",
}


def register_fonts(font_dir: str | None = None) -> bool:
    """Register DejaVu Sans fonts with full Unicode (incl. Polish) support.

    Raises FileNotFoundError if a required face cannot be found — failing here
    with a readable message beats crashing later inside ReportLab.
    """
    search = font_search_paths(font_dir)

    def locate(filename: str) -> str | None:
        for d in search:
            if not d:
                continue
            path = os.path.join(d, filename)
            if os.path.isfile(path):
                return path
        return None

    resolved = {}
    for name, filename in REQUIRED_FONTS.items():
        path = locate(filename)
        if path is None:
            raise FileNotFoundError(
                f"Required font {filename} not found.\n"
                f"Searched: {search}\n"
                f"Use --font-dir <path> to point at a directory with DejaVuSans*.ttf"
            )
        resolved[name] = path

    for name, filename in OPTIONAL_FONTS.items():
        path = locate(filename)
        if path is not None:
            resolved[name] = path

    for name, path in resolved.items():
        pdfmetrics.registerFont(TTFont(name, path))

    # Fall back to the upright faces when the italic ones are unavailable, so the
    # family mapping is always complete and ps2tt() can resolve every style.
    italic = "DJV-Oblique" if "DJV-Oblique" in resolved else "DJV"
    bold_italic = "DJV-BoldOblique" if "DJV-BoldOblique" in resolved else "DJV-Bold"

    from reportlab.lib.fonts import addMapping
    addMapping("DJV", 0, 0, "DJV")
    addMapping("DJV", 1, 0, "DJV-Bold")
    addMapping("DJV", 0, 1, italic)
    addMapping("DJV", 1, 1, bold_italic)
    return True


# ── Helper drawing functions ─────────────────────────────────

def draw_rounded_rect(c, x, y, w, h, r, fill_color=None, stroke_color=None):
    """Draw a rectangle with rounded corners."""
    p = c.beginPath()
    p.roundRect(x, y, w, h, r)
    if fill_color:
        c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(0.5)
    c.drawPath(p, fill=fill_color is not None, stroke=stroke_color is not None)


def _hval(inv: InvoiceData, cfg: MappingConfig, slot: str) -> str:
    """Get a header value via the mapping config."""
    tag = cfg.get(slot)
    return inv.h(tag) if tag else ""


def _ival(item, cfg: MappingConfig, slot: str) -> str:
    """Get an item value via the mapping config."""
    tag = cfg.get(slot)
    return InvoiceData.item_val(item, tag) if tag else ""


_NON_NUMERIC = re.compile(r"[^\d,.\-]")


def parse_amount(value) -> float:
    """Parse a monetary value written in any of the formats invoices use.

    Handles the decimal comma (1,50), thousands separators of either kind
    (1 234,56 / 1,234.56 / 1.234,56), non-breaking spaces and trailing currency
    codes. Anything unparseable becomes 0.0 — one malformed cell must not cost
    the user the whole document.

    A lone comma followed by exactly three digits is read as a thousands
    separator (1,234 -> 1234); one or two trailing digits mean a decimal comma.
    """
    if value is None:
        return 0.0

    text = _NON_NUMERIC.sub("", str(value))
    if not text.strip("-.,"):
        return 0.0

    last_dot, last_comma = text.rfind("."), text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # Whichever comes last is the decimal separator; the other groups digits.
        if last_dot > last_comma:
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif last_comma >= 0:
        tail = text[last_comma + 1:]
        if len(tail) == 3 and tail.isdigit():
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

    if text.count(".") > 1:
        # A number has at most one decimal separator, so these all group digits.
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return 0.0


def format_amount(value) -> str:
    """Render a monetary value with two decimals, tolerating any input format."""
    return f"{parse_amount(value):.2f}"


# ── GS1-128 encoding ─────────────────────────────────────────

# Application Identifiers of predefined length (GS1 General Specifications,
# section 3.2): their data field has a fixed size, so no separator follows it.
# Identified by the first two digits, which also covers the four-digit AIs in
# the 31xx-36xx measurement range.
GS1_PREDEFINED_LENGTH_PREFIXES = frozenset({
    "00", "01", "02", "03", "04",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "31", "32", "33", "34", "35", "36", "41",
})

FNC1 = "\xf1"  # ReportLab's escape for the FNC1 function character

_GS1_ELEMENT = re.compile(r"\(\s*(\d{2,4})\s*\)([^(]*)")


def gs1_encode(value: str) -> str:
    """Turn a human-readable GS1 element string into Code 128 input data.

    "(01)05060412780011(17)280930(10)LOT1" becomes FNC1 + "01…" + "17…" + "10LOT1":
    a conformant GS1-128 payload. The parentheses belong to the human-readable
    interpretation printed below the symbol, never inside it — encoding them
    literally (as this code used to) produces a plain Code 128 whose data no GS1
    system will accept.

    An element with a variable-length data field is terminated with FNC1 when
    another element follows; predefined-length AIs need no separator. A value
    with no parentheses is returned untouched, because without the AI
    delimiters there is no safe way to infer where each field ends.
    """
    if not value:
        return value

    elements = _GS1_ELEMENT.findall(value)
    if not elements:
        return value

    parts = [FNC1]
    for i, (ai, data) in enumerate(elements):
        parts.append(ai + data.strip())
        is_last = i == len(elements) - 1
        if not is_last and ai[:2] not in GS1_PREDEFINED_LENGTH_PREFIXES:
            parts.append(FNC1)
    return "".join(parts)


def _truncate(text: str, font_name: str, font_size: float, max_w: float) -> str:
    """Return text truncated with '...' if it exceeds max_w."""
    if max_w <= 0:
        return text
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_w:
        return text
    ellipsis = "..."
    ew = pdfmetrics.stringWidth(ellipsis, font_name, font_size)
    for i in range(len(text), 0, -1):
        if pdfmetrics.stringWidth(text[:i], font_name, font_size) + ew <= max_w:
            return text[:i] + ellipsis
    return ellipsis


def draw_shrink_to_fit(c, text: str, right_x: float, y: float, max_w: float,
                       font_name: str, font_size: float,
                       min_font_size: float = 7) -> float:
    """Draw right-aligned text on a single line, shrinking it to fit max_w.

    Used for identifiers such as the invoice number: wrapping one across two
    lines splits the token in half ("INV-2026-0" / "03842"), which a reader can
    easily mistranscribe. The font shrinks down to min_font_size, and only then
    is the text truncated. Returns the font size used.
    """
    size = font_size
    while size > min_font_size and pdfmetrics.stringWidth(text, font_name, size) > max_w:
        size -= 0.5

    label = _truncate(text, font_name, size, max_w)
    c.setFont(font_name, size)
    c.drawRightString(right_x, y, label)
    return size


def fit_paragraph(text: str, style: ParagraphStyle, max_w: float,
                  max_h: float) -> tuple[Paragraph, float]:
    """Return a Paragraph that genuinely fits in (max_w x max_h), plus its height.

    Overlong text is shortened to the longest prefix that still fits, with an
    ellipsis marking what was dropped. Clamping the reported height without
    shortening the text (the previous behaviour) only hid the overflow: the
    surplus lines were still drawn, on top of whatever came next.
    """
    if max_w <= 0:
        max_w = 1
    text = str(text)

    para = Paragraph(escape(text), style)
    _, height = para.wrap(max_w, max_h)
    if height <= max_h:
        return para, height

    lo, hi = 0, len(text)
    best: tuple[Paragraph, float] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = Paragraph(escape(text[:mid].rstrip() + "…"), style)
        _, cand_h = candidate.wrap(max_w, max_h)
        if cand_h <= max_h:
            best = (candidate, cand_h)
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        # Not even an ellipsis fits — draw nothing rather than overflow.
        empty = Paragraph("", style)
        _, empty_h = empty.wrap(max_w, max_h)
        return empty, min(empty_h, max_h)
    return best


def draw_para(c, text: str, x: float, y_top: float, max_w: float,
              style: ParagraphStyle, max_h: float = 72) -> float:
    """Draw wrapped text as a Paragraph anchored at top-left (x, y_top).

    Text too long for max_h is shortened with an ellipsis, so the drawn block
    never reaches outside the box. Returns the height actually used.
    """
    p, ph = fit_paragraph(text, style, max_w, max_h)
    p.drawOn(c, x, y_top - ph)
    return ph


def draw_footer(c, inv: InvoiceData, cfg: MappingConfig, page_num: int, total_pages: int):
    """Draw page footer."""
    y = 18 * mm
    c.setStrokeColor(LINE_GRY)
    c.setLineWidth(0.5)
    c.line(20 * mm, y + 6 * mm, W - 20 * mm, y + 6 * mm)
    c.setFillColor(MID_GRAY)
    c.setFont(FONT, 7)
    supplier = _hval(inv, cfg, "supplier_name")
    addr = f"{_hval(inv, cfg, 'supplier_street')}, {_hval(inv, cfg, 'supplier_city')}, {_hval(inv, cfg, 'supplier_postal_code')}"
    vat = _hval(inv, cfg, "supplier_nip")
    inv_num = _hval(inv, cfg, "invoice_number")
    right_text = f"Invoice {inv_num}  |  Page {page_num} of {total_pages}"
    right_w = pdfmetrics.stringWidth(right_text, FONT, 7)
    usable_w = (W - 40 * mm) - right_w - 10 * mm  # 10mm gap between left and right
    left_text = _truncate(f"{supplier}  |  {addr}  |  VAT: {vat}", FONT, 7, usable_w)
    c.drawString(20 * mm, y, left_text)
    c.drawRightString(W - 20 * mm, y, right_text)


# ── Table data builders ──────────────────────────────────────

def _build_items_data(inv: InvoiceData, cfg: MappingConfig):
    """Build items table header, data rows, and column widths."""
    styles = getSampleStyleSheet()
    cs   = ParagraphStyle("C",  parent=styles["Normal"], fontSize=8, leading=10, textColor=DARK_TXT, fontName="DJV")
    cs_r = ParagraphStyle("CR", parent=cs, alignment=TA_RIGHT)
    cs_c = ParagraphStyle("CC", parent=cs, alignment=TA_CENTER)
    hs   = ParagraphStyle("H",  parent=styles["Normal"], fontSize=7, leading=9, textColor=WHITE, fontName="DJV-Bold")
    hs_r = ParagraphStyle("HR", parent=hs, alignment=TA_RIGHT)
    hs_c = ParagraphStyle("HC", parent=hs, alignment=TA_CENTER)

    header_row = [
        Paragraph("#", hs_c), Paragraph("Code", hs), Paragraph("Description", hs),
        Paragraph("Qty", hs_c), Paragraph("Unit", hs_c), Paragraph("Unit Price", hs_r),
        Paragraph("VAT", hs_c), Paragraph("Net Total", hs_r),
    ]

    data_rows = []
    for idx, item in enumerate(inv.items, 1):
        data_rows.append([
            Paragraph(str(idx), cs_c),
            Paragraph(_ival(item, cfg, "item_code"), cs),
            Paragraph(_ival(item, cfg, "item_name"), cs),
            Paragraph(_ival(item, cfg, "item_qty"), cs_c),
            Paragraph(_ival(item, cfg, "item_unit"), cs_c),
            Paragraph(format_amount(_ival(item, cfg, "item_unit_price")), cs_r),
            Paragraph(_ival(item, cfg, "item_vat_rate"), cs_c),
            Paragraph(format_amount(_ival(item, cfg, "item_net_total")), cs_r),
        ])

    col_widths = [8*mm, 18*mm, 60*mm, 12*mm, 12*mm, 22*mm, 14*mm, 25*mm]
    return header_row, data_rows, col_widths


def _build_batch_data(inv: InvoiceData, cfg: MappingConfig):
    """Build batch table header, data rows, and column widths."""
    styles = getSampleStyleSheet()
    ss   = ParagraphStyle("S",  parent=styles["Normal"], fontSize=7, leading=9, textColor=DARK_TXT, fontName="DJV")
    ss_c = ParagraphStyle("SC", parent=ss, alignment=TA_CENTER)
    sh   = ParagraphStyle("SH", parent=ss, fontName="DJV-Bold", textColor=WHITE, fontSize=6.5)
    sh_c = ParagraphStyle("SHC", parent=sh, alignment=TA_CENTER)

    header_row = [
        Paragraph("#", sh_c), Paragraph("Product", sh),
        Paragraph("Batch / Lot No.", sh), Paragraph("Expiry Date", sh),
    ]

    data_rows = []
    for idx, item in enumerate(inv.items, 1):
        data_rows.append([
            Paragraph(str(idx), ss_c),
            Paragraph(_ival(item, cfg, "batch_product_name"), ss),
            Paragraph(_ival(item, cfg, "batch_lot_number"), ss),
            Paragraph(_ival(item, cfg, "batch_expiry_date"), ss),
        ])

    col_widths = [8*mm, 70*mm, 45*mm, 30*mm]
    return header_row, data_rows, col_widths


# ── Table construction (shared by measuring and drawing) ─────

def _build_table(header_row, data_rows, col_widths, orig_start_idx=0, is_batch=False):
    """Build a fully styled items/batch table (header row + data rows).

    Both the measurement pass and the drawing pass go through here, so the row
    heights the paginator works with are the heights that end up on the page.
    """
    tbl = Table([header_row] + data_rows, colWidths=col_widths)

    pad = 3 if is_batch else 4
    hdr_fs = 6.5 if is_batch else 7
    lb_w = 0.8 if is_batch else 1
    corner = 3 if is_batch else 4

    style_cmds = [
        ("BACKGROUND",     (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0), WHITE),
        ("FONTNAME",       (0, 0), (-1, 0), "DJV-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0), hdr_fs),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), pad),
        ("LEFTPADDING",    (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 3),
        ("LINEBELOW",      (0, 0), (-1, 0), lb_w, ACCENT),
        ("LINEBELOW",      (0, 1), (-1, -1), 0.3, LINE_GRY),
        ("ROUNDEDCORNERS", [corner, corner, 0, 0]),
    ]
    for i in range(len(data_rows)):
        orig_idx = orig_start_idx + i  # 0-based original data row index
        tbl_row = i + 1               # row in sub-table (0 = header)
        if (orig_idx + 1) % 2 == 0:   # even table-row index in original
            style_cmds.append(("BACKGROUND", (0, tbl_row), (-1, tbl_row), ROW_ALT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── Measurement & splitting ──────────────────────────────────

def _measure_row_heights(header_row, data_rows, col_widths, table_width, is_batch=False):
    """Wrap a temporary table and return per-row heights (header + data).

    The table is styled exactly as it will be drawn — paddings and header font
    size change how cells wrap, so measuring an unstyled table would hand the
    splitter heights that do not match reality.
    """
    tbl = _build_table(header_row, data_rows, col_widths, 0, is_batch)
    tbl.wrap(table_width, 9999)
    return list(tbl._rowHeights)


def _split_table_rows(row_heights, header_h, first_avail_h, cont_avail_h):
    """Split data rows into page chunks via greedy packing.

    row_heights: heights for data rows only (not header).
    Returns list of (start_idx, end_idx) tuples (exclusive end).
    """
    if not row_heights:
        return []
    chunks = []
    i = 0
    n = len(row_heights)
    first = True
    while i < n:
        avail = first_avail_h if first else cont_avail_h
        avail -= header_h  # reserve space for repeated header
        first = False
        j = i
        used = 0.0
        while j < n and used + row_heights[j] <= avail:
            used += row_heights[j]
            j += 1
        if j == i:
            j = i + 1  # force at least 1 row per chunk
        chunks.append((i, j))
        i = j
    return chunks


# ── Drawing helpers ──────────────────────────────────────────

def _draw_table_chunk(c, header_row, data_rows, col_widths, y_top,
                      orig_start_idx, is_batch=False):
    """Draw a sub-table (header + data_rows slice) at y_top. Returns height drawn."""
    tbl = _build_table(header_row, data_rows, col_widths, orig_start_idx, is_batch)

    table_width = W - 40 * mm
    _, tbl_h = tbl.wrap(table_width, 9999)
    tbl.drawOn(c, 20 * mm, y_top - tbl_h)
    return tbl_h


def _draw_continuation_header(c, inv: InvoiceData, cfg: MappingConfig, label: str):
    """Draw a slim navy header bar on continuation pages. Returns y where content starts."""
    bar_h = CONT_HEADER_H
    c.setFillColor(NAVY)
    c.rect(0, H - bar_h, W, bar_h, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(FONT_B, 14)
    inv_num = _hval(inv, cfg, "invoice_number")
    text = _truncate(f"Invoice #{inv_num} \u2014 {label}", FONT_B, 14, W - 40 * mm)
    c.drawString(20 * mm, H - 14 * mm, text)
    c.setFillColor(ACCENT)
    c.rect(0, H - bar_h - 2.5, W, 2.5, fill=1, stroke=0)
    return CONT_TOP_Y


def _count_content_pages(inv: InvoiceData, cfg: MappingConfig):
    """Measurement pass: count how many pages the content section needs."""
    table_width = W - 40 * mm

    # Page 1 fixed layout positions
    bar_h = 28 * mm
    y_badges = H - bar_h - 28 * mm
    y_boxes = y_badges - 42 * mm
    y_wz = y_boxes - 8 * mm
    y_table_top = y_wz - 8 * mm

    first_avail = y_table_top - FOOTER_MARGIN_Y
    cont_avail = CONT_TOP_Y - FOOTER_MARGIN_Y

    # Items table
    items_header, items_rows, items_cols = _build_items_data(inv, cfg)
    items_rh = _measure_row_heights(items_header, items_rows, items_cols, table_width)
    items_header_h = items_rh[0]
    items_data_rh = items_rh[1:]

    items_chunks = _split_table_rows(items_data_rh, items_header_h, first_avail, cont_avail)
    pages = 1 + max(0, len(items_chunks) - 1)

    # y_cursor after items
    if not items_chunks:
        y_cursor = y_table_top
    elif len(items_chunks) == 1:
        start, end = items_chunks[0]
        y_cursor = y_table_top - items_header_h - sum(items_data_rh[start:end])
    else:
        start, end = items_chunks[-1]
        y_cursor = CONT_TOP_Y - items_header_h - sum(items_data_rh[start:end])

    # Totals
    if y_cursor - TOTALS_BLOCK_H < FOOTER_MARGIN_Y:
        pages += 1
        y_cursor = CONT_TOP_Y
    y_tot = y_cursor - 12 * mm
    y_cursor = y_tot - 46 * mm

    # Batch table
    batch_label_h = 8 * mm
    batch_header, batch_rows, batch_cols = _build_batch_data(inv, cfg)
    batch_rh = _measure_row_heights(batch_header, batch_rows, batch_cols, table_width,
                                    is_batch=True)
    batch_header_h = batch_rh[0]
    batch_data_rh = batch_rh[1:]

    batch_first_avail = y_cursor - batch_label_h - FOOTER_MARGIN_Y
    min_batch = batch_header_h + (batch_data_rh[0] if batch_data_rh else 0)
    if batch_first_avail < min_batch:
        pages += 1
        y_cursor = CONT_TOP_Y
        batch_first_avail = y_cursor - batch_label_h - FOOTER_MARGIN_Y

    batch_chunks = _split_table_rows(batch_data_rh, batch_header_h,
                                     batch_first_avail, cont_avail)
    pages += max(0, len(batch_chunks) - 1)

    return pages


def draw_content_pages(c, inv: InvoiceData, cfg: MappingConfig, total_pages: int):
    """Draw all content pages (header, items, totals, batch). Returns last page number."""

    # ── Header bar ──────────────────────────────────────
    bar_h = 28 * mm
    c.setFillColor(NAVY)
    c.rect(0, H - bar_h, W, bar_h, fill=1, stroke=0)

    # Supplier name (left) — wrapped, max width leaves 130pt for invoice block
    inv_num = _hval(inv, cfg, "invoice_number")
    header_name_max_w = W - 40 * mm - INVOICE_NUMBER_MAX_W - 10
    header_name_style = ParagraphStyle(
        "HeaderName", fontName=FONT_B, fontSize=18, leading=20, textColor=WHITE)
    draw_para(c, _hval(inv, cfg, "supplier_name").upper(),
              20 * mm, H - 5 * mm, header_name_max_w, header_name_style, max_h=bar_h - 6 * mm)

    # Invoice number (right) — one line, shrunk to fit rather than wrapped
    c.setFillColor(WHITE)
    c.setFont(FONT, 11)
    c.drawRightString(W - 20 * mm, H - 12 * mm, "INVOICE")
    c.setFillColor(WHITE)
    draw_shrink_to_fit(c, f"# {inv_num}", W - 20 * mm, H - 21 * mm,
                       INVOICE_NUMBER_MAX_W, FONT_B, 16)

    # Accent line
    c.setFillColor(ACCENT)
    c.rect(0, H - bar_h - 3, W, 3, fill=1, stroke=0)

    # ── Date badges ─────────────────────────────────────
    # Four badges share the printable width. The currency badge used to be
    # right-aligned at a fixed 52mm width, which landed it on top of the payment
    # badge; the width is now derived from the count so they cannot collide.
    y_badges = H - bar_h - 28 * mm
    badge_h = 16 * mm
    badge_gap = 6 * mm

    badges = [
        ("Issue Date", _hval(inv, cfg, "issue_date")),
        ("Due Date",   _hval(inv, cfg, "due_date")),
        ("Payment",    _hval(inv, cfg, "payment_type")),
        ("Currency",   _hval(inv, cfg, "currency")),
    ]
    badge_w = (W - 40 * mm - badge_gap * (len(badges) - 1)) / len(badges)
    badge_text_w = badge_w - 8 * mm

    for i, (label, value) in enumerate(badges):
        bx = 20 * mm + i * (badge_w + badge_gap)
        draw_rounded_rect(c, bx, y_badges, badge_w, badge_h, 3, fill_color=LIGHT_BG)
        c.setFillColor(MID_GRAY)
        c.setFont(FONT, 7)
        c.drawString(bx + 4 * mm, y_badges + badge_h - 5.5 * mm,
                     _truncate(label.upper(), FONT, 7, badge_text_w))
        c.setFillColor(DARK_TXT)
        c.setFont(FONT_B, 10)
        c.drawString(bx + 4 * mm, y_badges + 3 * mm,
                     _truncate(value, FONT_B, 10, badge_text_w))

    # ── Supplier / Buyer boxes ──────────────────────────
    y_boxes = y_badges - 42 * mm
    box_w = (W - 50 * mm) / 2
    box_h = 34 * mm

    box_inner_w = box_w - 8 * mm
    box_name_style = ParagraphStyle("BoxName", fontName=FONT_B, fontSize=9.5, leading=11, textColor=DARK_TXT)
    box_addr_style = ParagraphStyle("BoxAddr", fontName=FONT, fontSize=8, leading=10, textColor=MID_GRAY)

    # Supplier
    draw_rounded_rect(c, 20 * mm, y_boxes, box_w, box_h, 4, fill_color=LIGHT_BG)
    c.setFillColor(ACCENT)
    c.setFont(FONT_B, 8)
    c.drawString(24 * mm, y_boxes + box_h - 6 * mm, "SUPPLIER")

    sy = y_boxes + box_h - 8 * mm
    sh = draw_para(c, _hval(inv, cfg, "supplier_name"), 24 * mm, sy, box_inner_w, box_name_style, max_h=16 * mm)
    sy -= sh + 1 * mm
    sh = draw_para(c, _hval(inv, cfg, "supplier_street"), 24 * mm, sy, box_inner_w, box_addr_style, max_h=10 * mm)
    sy -= sh + 0.5 * mm
    sh = draw_para(c, f"{_hval(inv, cfg, 'supplier_city')}, {_hval(inv, cfg, 'supplier_postal_code')}",
                   24 * mm, sy, box_inner_w, box_addr_style, max_h=10 * mm)
    sy -= sh + 0.5 * mm
    draw_para(c, f"VAT: {_hval(inv, cfg, 'supplier_nip')}", 24 * mm, sy, box_inner_w, box_addr_style, max_h=10 * mm)

    # Buyer
    bx_b = 20 * mm + box_w + 10 * mm
    draw_rounded_rect(c, bx_b, y_boxes, box_w, box_h, 4, fill_color=LIGHT_BG)
    c.setFillColor(ACCENT)
    c.setFont(FONT_B, 8)
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 6 * mm, "BUYER")

    by = y_boxes + box_h - 8 * mm
    bh = draw_para(c, _hval(inv, cfg, "buyer_name"), bx_b + 4 * mm, by, box_inner_w, box_name_style, max_h=16 * mm)
    by -= bh + 1 * mm
    bh = draw_para(c, _hval(inv, cfg, "buyer_street"), bx_b + 4 * mm, by, box_inner_w, box_addr_style, max_h=10 * mm)
    by -= bh + 0.5 * mm
    bh = draw_para(c, f"{_hval(inv, cfg, 'buyer_city')}, {_hval(inv, cfg, 'buyer_postal_code')}",
                   bx_b + 4 * mm, by, box_inner_w, box_addr_style, max_h=10 * mm)
    by -= bh + 0.5 * mm
    draw_para(c, f"VAT: {_hval(inv, cfg, 'buyer_nip')}", bx_b + 4 * mm, by, box_inner_w, box_addr_style, max_h=10 * mm)

    # ── Delivery note (WZ) ──────────────────────────────
    y_wz = y_boxes - 8 * mm
    wz = _hval(inv, cfg, "delivery_note")
    if wz:
        c.setFillColor(MID_GRAY)
        c.setFont(FONT, 8)
        c.drawString(20 * mm, y_wz, f"Delivery Note: {wz}")

    # ── Paginated items table ────────────────────────────
    table_width = W - 40 * mm
    page_num = 1
    y_table_top = y_wz - 8 * mm

    items_header, items_rows, items_cols = _build_items_data(inv, cfg)
    items_rh = _measure_row_heights(items_header, items_rows, items_cols, table_width)
    items_header_h = items_rh[0]
    items_data_rh = items_rh[1:]

    first_avail = y_table_top - FOOTER_MARGIN_Y
    cont_avail = CONT_TOP_Y - FOOTER_MARGIN_Y

    items_chunks = _split_table_rows(items_data_rh, items_header_h, first_avail, cont_avail)

    y_cursor = y_table_top
    if items_chunks:
        for ci, (start, end) in enumerate(items_chunks):
            if ci > 0:
                draw_footer(c, inv, cfg, page_num, total_pages)
                c.showPage()
                page_num += 1
                y_cursor = _draw_continuation_header(
                    c, inv, cfg, f"Items table (continued from page {page_num - 1})")
            chunk_h = _draw_table_chunk(
                c, items_header, items_rows[start:end], items_cols, y_cursor, start)
            y_cursor -= chunk_h
    else:
        # No data rows — draw header-only table
        chunk_h = _draw_table_chunk(c, items_header, [], items_cols, y_cursor, 0)
        y_cursor -= chunk_h

    # ── Totals summary ──────────────────────────────────
    if y_cursor - TOTALS_BLOCK_H < FOOTER_MARGIN_Y:
        draw_footer(c, inv, cfg, page_num, total_pages)
        c.showPage()
        page_num += 1
        y_cursor = _draw_continuation_header(c, inv, cfg, "Invoice summary")

    y_tot = y_cursor - 12 * mm
    tw = 70 * mm
    tx = W - 20 * mm - tw
    currency = _hval(inv, cfg, "currency")

    draw_rounded_rect(c, tx, y_tot - 28 * mm, tw, 38 * mm, 4, fill_color=LIGHT_BG)

    c.setFillColor(MID_GRAY); c.setFont(FONT, 9)
    c.drawString(tx + 5 * mm, y_tot + 2 * mm, "Net Total:")
    c.setFillColor(DARK_TXT); c.setFont(FONT, 9)
    c.drawRightString(tx + tw - 5 * mm, y_tot + 2 * mm,
                      f"{currency} {format_amount(_hval(inv, cfg, 'net_total'))}")

    c.setFillColor(MID_GRAY); c.setFont(FONT, 9)
    c.drawString(tx + 5 * mm, y_tot - 6 * mm, "VAT:")
    c.setFillColor(DARK_TXT)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 6 * mm,
                      f"{currency} {format_amount(_hval(inv, cfg, 'vat_total'))}")

    c.setStrokeColor(ACCENT); c.setLineWidth(1)
    c.line(tx + 5 * mm, y_tot - 12 * mm, tx + tw - 5 * mm, y_tot - 12 * mm)

    c.setFillColor(NAVY); c.setFont(FONT_B, 12)
    c.drawString(tx + 5 * mm, y_tot - 22 * mm, "TOTAL:")
    c.setFillColor(ACCENT); c.setFont(FONT_B, 14)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 22 * mm,
                      f"{currency} {format_amount(_hval(inv, cfg, 'gross_total'))}")

    # ── Paginated batch / expiry table ───────────────────
    y_cursor = y_tot - 46 * mm
    batch_label_h = 8 * mm

    batch_header, batch_rows, batch_cols = _build_batch_data(inv, cfg)
    batch_rh = _measure_row_heights(batch_header, batch_rows, batch_cols, table_width,
                                    is_batch=True)
    batch_header_h = batch_rh[0]
    batch_data_rh = batch_rh[1:]

    batch_first_avail = y_cursor - batch_label_h - FOOTER_MARGIN_Y
    min_batch = batch_header_h + (batch_data_rh[0] if batch_data_rh else 0)
    if batch_first_avail < min_batch:
        draw_footer(c, inv, cfg, page_num, total_pages)
        c.showPage()
        page_num += 1
        y_cursor = _draw_continuation_header(c, inv, cfg, "Batch & expiry details")
        batch_first_avail = y_cursor - batch_label_h - FOOTER_MARGIN_Y

    batch_chunks = _split_table_rows(batch_data_rh, batch_header_h,
                                     batch_first_avail, cont_avail)

    if batch_chunks:
        for ci, (start, end) in enumerate(batch_chunks):
            if ci > 0:
                draw_footer(c, inv, cfg, page_num, total_pages)
                c.showPage()
                page_num += 1
                y_cursor = _draw_continuation_header(
                    c, inv, cfg, f"Batch & expiry details (continued from page {page_num - 1})")
            if ci == 0:
                c.setFillColor(MID_GRAY)
                c.setFont(FONT, 7)
                c.drawString(20 * mm, y_cursor - batch_label_h + 4 * mm,
                             "BATCH & EXPIRY DETAILS")
                y_cursor -= batch_label_h
            chunk_h = _draw_table_chunk(
                c, batch_header, batch_rows[start:end], batch_cols,
                y_cursor, start, is_batch=True)
            y_cursor -= chunk_h
    else:
        c.setFillColor(MID_GRAY)
        c.setFont(FONT, 7)
        c.drawString(20 * mm, y_cursor - batch_label_h + 4 * mm,
                     "BATCH & EXPIRY DETAILS")
        y_cursor -= batch_label_h
        chunk_h = _draw_table_chunk(
            c, batch_header, [], batch_cols, y_cursor, 0, is_batch=True)
        y_cursor -= chunk_h

    draw_footer(c, inv, cfg, page_num, total_pages)
    return page_num


def _coded_items(inv: InvoiceData, cfg: MappingConfig) -> list[tuple[int, object]]:
    """Items carrying an EAN-128 code, paired with their original 1-based number."""
    return [(idx, item) for idx, item in enumerate(inv.items, 1)
            if _ival(item, cfg, "barcode_ean128")]


def barcode_cards_per_page() -> int:
    """How many cards fit on a barcode page, derived from the layout constants.

    Mirrors the page-break rule in draw_barcode_pages() so the page count and the
    drawing can never disagree.
    """
    n = 0
    y = BARCODE_TOP_Y
    while True:
        n += 1
        y -= BARCODE_CARD_H + BARCODE_CARD_GAP
        if y - BARCODE_CARD_H < BARCODE_BOTTOM_LIMIT:
            return n


def draw_barcode_pages(c, inv: InvoiceData, cfg: MappingConfig,
                       total_pages: int, start_page_num: int = 2):
    """Draw EAN-128 / GS1-128 barcode pages for the items that carry a code."""

    coded = _coded_items(inv, cfg)
    if not coded:
        return

    c.showPage()
    page_num = start_page_num
    margin_x = 20 * mm
    card_w = W - 40 * mm
    card_h = BARCODE_CARD_H
    gap = BARCODE_CARD_GAP
    inv_num = _hval(inv, cfg, "invoice_number")

    def draw_barcode_header(title_suffix=""):
        bar_h2 = BARCODE_HEADER_H
        c.setFillColor(NAVY)
        c.rect(0, H - bar_h2, W, bar_h2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(FONT_B, 14)
        label = f"Invoice #{inv_num} — EAN-128 / GS1-128 Barcodes{title_suffix}"
        label = _truncate(label, FONT_B, 14, W - 40 * mm)
        c.drawString(20 * mm, H - 14 * mm, label)
        c.setFillColor(ACCENT)
        c.rect(0, H - bar_h2 - 2.5, W, 2.5, fill=1, stroke=0)
        return BARCODE_TOP_Y

    y_cursor = draw_barcode_header()

    bc_name_style = ParagraphStyle("BcName", fontName=FONT_B, fontSize=10, leading=12, textColor=DARK_TXT)

    for pos, (idx, item) in enumerate(coded):
        ean128 = _ival(item, cfg, "barcode_ean128")
        ean    = _ival(item, cfg, "barcode_ean")
        name   = _ival(item, cfg, "barcode_product_name")
        item_code = _ival(item, cfg, "barcode_product_code")
        batch  = _ival(item, cfg, "barcode_batch")
        expiry = _ival(item, cfg, "barcode_expiry")

        # Card
        draw_rounded_rect(c, margin_x, y_cursor - card_h, card_w, card_h, 4,
                          fill_color=LIGHT_BG, stroke_color=LINE_GRY)

        # Barcode — right-aligned (compute first to know available text width)
        bc_h = 18 * mm
        card_right = margin_x + card_w - 5 * mm
        bc = code128.Code128(gs1_encode(ean128), barWidth=0.26 * mm,
                             barHeight=bc_h, humanReadable=False)
        bc_x = card_right - bc.width
        bc_y = y_cursor - card_h + 6 * mm
        c.setFillColor(DARK_TXT)
        bc.drawOn(c, bc_x, bc_y)

        # GS1-128 number below barcode
        c.setFillColor(DARK_TXT); c.setFont(FONT, 5.5)
        c.drawRightString(card_right, bc_y - 4 * mm, f"GS1-128: {ean128}")

        # Info on left — constrained to not overlap barcode
        ix = margin_x + 5 * mm
        iy = y_cursor - 8 * mm
        text_max_w = max(bc_x - ix - 3 * mm, 20 * mm)

        c.setFillColor(ACCENT); c.setFont(FONT_B, 7)
        c.drawString(ix, iy, f"ITEM {idx}")
        draw_para(c, name, ix, iy - 2 * mm, text_max_w, bc_name_style, max_h=13)

        c.setFillColor(DARK_TXT); c.setFont(FONT, 7.5)
        code_ean = _truncate(f"Code: {item_code}    EAN: {ean}", FONT, 7.5, text_max_w)
        c.drawString(ix, iy - 15 * mm, code_ean)
        batch_exp = _truncate(f"Batch: {batch}    |    Expiry: {expiry}", FONT, 7.5, text_max_w)
        c.drawString(ix, iy - 20.5 * mm, batch_exp)

        y_cursor -= (card_h + gap)

        # New page if no room — only when another card still has to be drawn
        if y_cursor - card_h < BARCODE_BOTTOM_LIMIT and pos < len(coded) - 1:
            draw_footer(c, inv, cfg, page_num, total_pages)
            c.showPage()
            page_num += 1
            y_cursor = draw_barcode_header(" (cont.)")

    draw_footer(c, inv, cfg, page_num, total_pages)


def xml_to_pdf(xml_path: str, output_path: str | None = None,
               include_barcodes: bool | None = None, font_dir: str | None = None,
               mapping_config: MappingConfig | None = None) -> str:
    """Convert an invoice XML file to PDF.

    Args:
        xml_path:        Path to the invoice XML file
        output_path:     Output PDF path (default: same dir, .pdf extension)
        include_barcodes: Whether to generate barcode pages. None (the default)
                          keeps whatever the mapping config says — passing a
                          bool here is an explicit override.
        font_dir:        Optional directory containing DejaVuSans*.ttf fonts
        mapping_config:  Optional field mapping configuration

    Returns:
        Path to the generated PDF file
    """
    if not os.path.isfile(xml_path):
        raise FileNotFoundError(f"File not found: {xml_path}")

    if output_path is None:
        output_path = os.path.splitext(xml_path)[0] + ".pdf"

    if mapping_config is None:
        mapping_config = MappingConfig()

    # Work on a copy: callers (batch conversion, the GUI) reuse one config object
    # across files, so rendering must not leave its overrides behind.
    mapping_config = replace(mapping_config)
    if font_dir is not None:
        mapping_config.font_dir = font_dir
    if include_barcodes is not None:
        mapping_config.include_barcodes = include_barcodes

    register_fonts(mapping_config.font_dir)
    inv = InvoiceData(xml_path,
                      header_xpath=mapping_config.header_xpath,
                      item_xpath=mapping_config.item_xpath)

    # Two-pass: measure content pages, then draw
    content_pages = _count_content_pages(inv, mapping_config)
    barcode_pages = 0
    if mapping_config.include_barcodes:
        barcode_count = len(_coded_items(inv, mapping_config))
        if barcode_count > 0:
            barcode_pages = math.ceil(barcode_count / barcode_cards_per_page())
    total_pages = content_pages + barcode_pages

    c = canvas.Canvas(output_path, pagesize=A4)
    last_page = draw_content_pages(c, inv, mapping_config, total_pages)

    if mapping_config.include_barcodes:
        draw_barcode_pages(c, inv, mapping_config, total_pages, last_page + 1)

    c.save()
    return output_path
