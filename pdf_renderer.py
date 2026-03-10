"""
pdf_renderer.py
===============
PDF drawing functions for invoice generation, parameterized by MappingConfig.
"""

from __future__ import annotations

import math
import os
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

FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    r"C:\Windows\Fonts",
    os.path.dirname(os.path.abspath(__file__)),
]

W, H = A4

# ── Pagination constants ─────────────────────────────────────
FOOTER_MARGIN_Y = 30 * mm
CONT_HEADER_H = 20 * mm
CONT_TOP_Y = H - CONT_HEADER_H - 18 * mm
TOTALS_BLOCK_H = 50 * mm


def register_fonts(font_dir: str | None = None) -> bool:
    """Register DejaVu Sans fonts with Polish character support (UTF-8)."""
    search = [font_dir] if font_dir else FONT_SEARCH_PATHS

    font_files = {
        "DJV":             "DejaVuSans.ttf",
        "DJV-Bold":        "DejaVuSans-Bold.ttf",
        "DJV-Oblique":     "DejaVuSans-Oblique.ttf",
        "DJV-BoldOblique": "DejaVuSans-BoldOblique.ttf",
    }

    resolved = {}
    for name, filename in font_files.items():
        for d in search:
            path = os.path.join(d, filename)
            if os.path.isfile(path):
                resolved[name] = path
                break
        if name not in resolved:
            print(f"UWAGA: Nie znaleziono {filename}")
            print(f"       Szukano w: {search}")
            print(f"       Uzyj --font-dir <sciezka> aby wskazac katalog z DejaVuSans*.ttf")
            return False

    for name, path in resolved.items():
        pdfmetrics.registerFont(TTFont(name, path))

    from reportlab.lib.fonts import addMapping
    addMapping("DJV", 0, 0, "DJV")
    addMapping("DJV", 1, 0, "DJV-Bold")
    addMapping("DJV", 0, 1, "DJV-Oblique")
    addMapping("DJV", 1, 1, "DJV-BoldOblique")
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


def draw_para(c, text: str, x: float, y_top: float, max_w: float,
              style: ParagraphStyle, max_h: float = 72) -> float:
    """Draw wrapped text as a Paragraph anchored at top-left (x, y_top).

    Returns the actual height used.
    """
    if max_w <= 0:
        max_w = 1
    p = Paragraph(escape(str(text)), style)
    pw, ph = p.wrap(max_w, max_h)
    # Clip to max_h
    if ph > max_h:
        ph = max_h
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
            Paragraph(f"{float(_ival(item, cfg, 'item_unit_price') or 0):.2f}", cs_r),
            Paragraph(_ival(item, cfg, "item_vat_rate"), cs_c),
            Paragraph(f"{float(_ival(item, cfg, 'item_net_total') or 0):.2f}", cs_r),
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


# ── Measurement & splitting ──────────────────────────────────

def _measure_row_heights(header_row, data_rows, col_widths, table_width):
    """Wrap a temporary table and return per-row heights (header + data)."""
    all_rows = [header_row] + data_rows
    tbl = Table(all_rows, colWidths=col_widths)
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
    all_rows = [header_row] + data_rows
    tbl = Table(all_rows, colWidths=col_widths)

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
    batch_rh = _measure_row_heights(batch_header, batch_rows, batch_cols, table_width)
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
    header_name_max_w = W - 40 * mm - 130
    header_name_style = ParagraphStyle(
        "HeaderName", fontName=FONT_B, fontSize=18, leading=20, textColor=WHITE)
    draw_para(c, _hval(inv, cfg, "supplier_name").upper(),
              20 * mm, H - 5 * mm, header_name_max_w, header_name_style, max_h=bar_h - 6 * mm)

    # Invoice number (right)
    c.setFillColor(WHITE)
    c.setFont(FONT, 11)
    c.drawRightString(W - 20 * mm, H - 12 * mm, "INVOICE")
    inv_num_style = ParagraphStyle(
        "HeaderInv", fontName=FONT_B, fontSize=16, leading=18, textColor=WHITE, alignment=TA_RIGHT)
    draw_para(c, f"# {inv_num}",
              W - 20 * mm - 120, H - 14 * mm, 120, inv_num_style, max_h=16 * mm)

    # Accent line
    c.setFillColor(ACCENT)
    c.rect(0, H - bar_h - 3, W, 3, fill=1, stroke=0)

    # ── Date badges ─────────────────────────────────────
    y_badges = H - bar_h - 28 * mm
    badge_w, badge_h = 52 * mm, 16 * mm

    badges = [
        ("Issue Date",  _hval(inv, cfg, "issue_date")),
        ("Due Date",    _hval(inv, cfg, "due_date")),
        ("Payment",     _hval(inv, cfg, "payment_type")),
    ]
    for i, (label, value) in enumerate(badges):
        bx = 20 * mm + i * (badge_w + 8 * mm)
        draw_rounded_rect(c, bx, y_badges, badge_w, badge_h, 3, fill_color=LIGHT_BG)
        c.setFillColor(MID_GRAY)
        c.setFont(FONT, 7)
        c.drawString(bx + 4 * mm, y_badges + badge_h - 5.5 * mm, label.upper())
        c.setFillColor(DARK_TXT)
        c.setFont(FONT_B, 10)
        c.drawString(bx + 4 * mm, y_badges + 3 * mm, value)

    # Currency badge
    bx_curr = W - 20 * mm - badge_w
    draw_rounded_rect(c, bx_curr, y_badges, badge_w, badge_h, 3, fill_color=LIGHT_BG)
    c.setFillColor(MID_GRAY)
    c.setFont(FONT, 7)
    c.drawString(bx_curr + 4 * mm, y_badges + badge_h - 5.5 * mm, "CURRENCY")
    c.setFillColor(DARK_TXT)
    c.setFont(FONT_B, 10)
    c.drawString(bx_curr + 4 * mm, y_badges + 3 * mm, _hval(inv, cfg, "currency"))

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
        c.drawString(20 * mm, y_wz, f"Delivery Note (WZ): {wz}")

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
                      f"{currency} {float(_hval(inv, cfg, 'net_total') or 0):.2f}")

    c.setFillColor(MID_GRAY); c.setFont(FONT, 9)
    c.drawString(tx + 5 * mm, y_tot - 6 * mm, "VAT:")
    c.setFillColor(DARK_TXT)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 6 * mm,
                      f"{currency} {float(_hval(inv, cfg, 'vat_total') or 0):.2f}")

    c.setStrokeColor(ACCENT); c.setLineWidth(1)
    c.line(tx + 5 * mm, y_tot - 12 * mm, tx + tw - 5 * mm, y_tot - 12 * mm)

    c.setFillColor(NAVY); c.setFont(FONT_B, 12)
    c.drawString(tx + 5 * mm, y_tot - 22 * mm, "TOTAL:")
    c.setFillColor(ACCENT); c.setFont(FONT_B, 14)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 22 * mm,
                      f"{currency} {float(_hval(inv, cfg, 'gross_total') or 0):.2f}")

    # ── Paginated batch / expiry table ───────────────────
    y_cursor = y_tot - 46 * mm
    batch_label_h = 8 * mm

    batch_header, batch_rows, batch_cols = _build_batch_data(inv, cfg)
    batch_rh = _measure_row_heights(batch_header, batch_rows, batch_cols, table_width)
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


def draw_barcode_pages(c, inv: InvoiceData, cfg: MappingConfig,
                       total_pages: int, start_page_num: int = 2):
    """Draw EAN-128 / GS1-128 barcode pages for each item."""

    # Check if any items have EAN-128 codes
    has_barcodes = any(_ival(item, cfg, "barcode_ean128") for item in inv.items)
    if not has_barcodes:
        return

    c.showPage()
    page_num = start_page_num
    margin_x = 20 * mm
    card_w = W - 40 * mm
    card_h = 40 * mm
    gap = 3 * mm
    inv_num = _hval(inv, cfg, "invoice_number")

    def draw_barcode_header(title_suffix=""):
        bar_h2 = 20 * mm
        c.setFillColor(NAVY)
        c.rect(0, H - bar_h2, W, bar_h2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(FONT_B, 14)
        label = f"Invoice #{inv_num} — EAN-128 / GS1-128 Barcodes{title_suffix}"
        label = _truncate(label, FONT_B, 14, W - 40 * mm)
        c.drawString(20 * mm, H - 14 * mm, label)
        c.setFillColor(ACCENT)
        c.rect(0, H - bar_h2 - 2.5, W, 2.5, fill=1, stroke=0)
        return H - bar_h2 - 18 * mm

    y_cursor = draw_barcode_header()

    bc_name_style = ParagraphStyle("BcName", fontName=FONT_B, fontSize=10, leading=12, textColor=DARK_TXT)

    for idx, item in enumerate(inv.items, 1):
        ean128 = _ival(item, cfg, "barcode_ean128")
        if not ean128:
            continue

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
        bc = code128.Code128(ean128, barWidth=0.26 * mm, barHeight=bc_h, humanReadable=False)
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

        # New page if no room
        if y_cursor - card_h < 30 * mm and idx < len(inv.items):
            draw_footer(c, inv, cfg, page_num, total_pages)
            c.showPage()
            page_num += 1
            y_cursor = draw_barcode_header(" (cont.)")

    draw_footer(c, inv, cfg, page_num, total_pages)


def xml_to_pdf(xml_path: str, output_path: str | None = None,
               include_barcodes: bool = True, font_dir: str | None = None,
               mapping_config: MappingConfig | None = None) -> str:
    """Convert an invoice XML file to PDF.

    Args:
        xml_path:        Path to the invoice XML file
        output_path:     Output PDF path (default: same dir, .pdf extension)
        include_barcodes: Whether to generate barcode pages
        font_dir:        Optional directory containing DejaVuSans*.ttf fonts
        mapping_config:  Optional field mapping configuration

    Returns:
        Path to the generated PDF file
    """
    if not os.path.isfile(xml_path):
        raise FileNotFoundError(f"Nie znaleziono pliku: {xml_path}")

    if output_path is None:
        output_path = os.path.splitext(xml_path)[0] + ".pdf"

    if mapping_config is None:
        mapping_config = MappingConfig()

    # Override config options with explicit parameters
    if font_dir is not None:
        mapping_config.font_dir = font_dir
    mapping_config.include_barcodes = include_barcodes

    register_fonts(mapping_config.font_dir)
    inv = InvoiceData(xml_path,
                      header_xpath=mapping_config.header_xpath,
                      item_xpath=mapping_config.item_xpath)

    # Two-pass: measure content pages, then draw
    content_pages = _count_content_pages(inv, mapping_config)
    barcode_pages = 0
    if mapping_config.include_barcodes:
        barcode_count = sum(1 for item in inv.items if _ival(item, mapping_config, "barcode_ean128"))
        if barcode_count > 0:
            barcode_pages = math.ceil(barcode_count / 5)
    total_pages = content_pages + barcode_pages

    c = canvas.Canvas(output_path, pagesize=A4)
    last_page = draw_content_pages(c, inv, mapping_config, total_pages)

    if mapping_config.include_barcodes:
        draw_barcode_pages(c, inv, mapping_config, total_pages, last_page + 1)

    c.save()
    return output_path
