#!/usr/bin/env python3
"""
xml_invoice_to_pdf.py
=====================
Konwertuje faktury XML (format Domson/polski) do profesjonalnego PDF
z tabelą pozycji, danymi partii i kodami kreskowymi EAN-128 / GS1-128.

Wymagania:
    pip install reportlab

Użycie:
    python xml_invoice_to_pdf.py faktura.xml                    # → faktura.pdf
    python xml_invoice_to_pdf.py faktura.xml -o wynik.pdf       # → wynik.pdf
    python xml_invoice_to_pdf.py *.xml                          # batch: wiele plików
    python xml_invoice_to_pdf.py faktura.xml --no-barcodes      # bez strony z EAN-128
    python xml_invoice_to_pdf.py faktura.xml --font-dir /fonts  # własna ścieżka do czcionek

Struktura XML (obsługiwane pola):
    <Document>
      <Faktura>
        <Naglowek>
          DostawcaNIP, DostawcaNazwa, DostawcaAdresKodPocztowy,
          DostawcaAdresMiejscowosc, DostawcaAdresUlica,
          NabywcaNIP, NabywcaNazwa, NabywcaAdresKodPocztowy,
          NabywcaAdresMiejscowosc, NabywcaAdresUlica,
          FakturaNumer, FakturaDataWystawienia, FakturaDataPlatnosci,
          FakturaTypPlatnosci, FakturaWaluta,
          FakturaWartoscNetto, FakturaWartoscVat, FakturaWartoscBrutto,
          FakturaNumeryWZ
        </Naglowek>
        <Pozycje>
          <Pozycja>
            TowarKod, TowarKodEan, TowarKodEan128, TowarNazwa, TowarJm,
            Ilosc, CenaNetto, WartoscNetto, StawkaVat, WartoscVat,
            WartoscBrutto, TowarDostawaNumerSerii, TowarDostawaDataWaznosci
          </Pozycja>
        </Pozycje>
      </Faktura>
    </Document>
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET

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


# ╔══════════════════════════════════════════════════════════╗
# ║  KONFIGURACJA KOLORÓW I CZCIONEK                        ║
# ╚══════════════════════════════════════════════════════════╝

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

# Standardowe ścieżki do DejaVu Sans (Linux / macOS / Windows)
FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    r"C:\Windows\Fonts",
    os.path.dirname(os.path.abspath(__file__)),  # obok skryptu
]

W, H = A4


def register_fonts(font_dir: str | None = None):
    """Rejestruje czcionki DejaVu Sans z obsługą polskich znaków (UTF-8)."""
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
            print(f"UWAGA: Nie znaleziono {filename} — polskie znaki mogą się nie wyświetlać.")
            print(f"       Szukano w: {search}")
            print(f"       Użyj --font-dir <ścieżka> aby wskazać katalog z DejaVuSans*.ttf")
            return False

    for name, path in resolved.items():
        pdfmetrics.registerFont(TTFont(name, path))

    from reportlab.lib.fonts import addMapping
    addMapping("DJV", 0, 0, "DJV")
    addMapping("DJV", 1, 0, "DJV-Bold")
    addMapping("DJV", 0, 1, "DJV-Oblique")
    addMapping("DJV", 1, 1, "DJV-BoldOblique")
    return True


# ╔══════════════════════════════════════════════════════════╗
# ║  PARSOWANIE XML                                          ║
# ╚══════════════════════════════════════════════════════════╝

class InvoiceData:
    """Sparsowane dane faktury z XML."""

    def __init__(self, xml_path: str):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        self.header = root.find(".//Naglowek")
        self.items = root.findall(".//Pozycja")

        if self.header is None:
            raise ValueError(f"Brak elementu <Naglowek> w {xml_path}")
        if not self.items:
            raise ValueError(f"Brak elementów <Pozycja> w {xml_path}")

    def h(self, tag: str) -> str:
        """Pobiera wartość z nagłówka faktury."""
        el = self.header.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def item_val(item, tag: str) -> str:
        """Pobiera wartość z pozycji faktury."""
        el = item.find(tag)
        return el.text.strip() if el is not None and el.text else ""


# ╔══════════════════════════════════════════════════════════╗
# ║  POMOCNICZE FUNKCJE RYSOWANIA                           ║
# ╚══════════════════════════════════════════════════════════╝

def draw_rounded_rect(c, x, y, w, h, r, fill_color=None, stroke_color=None):
    """Rysuje prostokąt z zaokrąglonymi rogami."""
    p = c.beginPath()
    p.roundRect(x, y, w, h, r)
    if fill_color:
        c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(0.5)
    c.drawPath(p, fill=fill_color is not None, stroke=stroke_color is not None)


def draw_footer(c, inv: InvoiceData, page_num: int, total_pages: int):
    """Rysuje stopkę na dole strony."""
    y = 18 * mm
    c.setStrokeColor(LINE_GRY)
    c.setLineWidth(0.5)
    c.line(20 * mm, y + 6 * mm, W - 20 * mm, y + 6 * mm)
    c.setFillColor(MID_GRAY)
    c.setFont(FONT, 7)
    supplier = inv.h("DostawcaNazwa")
    addr = f"{inv.h('DostawcaAdresUlica')}, {inv.h('DostawcaAdresMiejscowosc')}, {inv.h('DostawcaAdresKodPocztowy')}"
    vat = inv.h("DostawcaNIP")
    c.drawString(20 * mm, y, f"{supplier}  |  {addr}  |  VAT: {vat}")
    c.drawRightString(W - 20 * mm, y, f"Invoice {inv.h('FakturaNumer')}  |  Page {page_num} of {total_pages}")


# ╔══════════════════════════════════════════════════════════╗
# ║  STRONA 1 — DANE FAKTURY + TABELA POZYCJI               ║
# ╚══════════════════════════════════════════════════════════╝

def draw_page1(c, inv: InvoiceData, total_pages: int):
    """Rysuje główną stronę faktury."""

    # ── Nagłówek (pasek granatowy) ──────────────────────
    bar_h = 28 * mm
    c.setFillColor(NAVY)
    c.rect(0, H - bar_h, W, bar_h, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont(FONT_B, 22)
    c.drawString(20 * mm, H - 18 * mm, inv.h("DostawcaNazwa").upper())

    c.setFont(FONT, 11)
    c.drawRightString(W - 20 * mm, H - 12 * mm, "INVOICE")
    c.setFont(FONT_B, 18)
    c.drawRightString(W - 20 * mm, H - 22 * mm, f"# {inv.h('FakturaNumer')}")

    # Linia akcentowa
    c.setFillColor(ACCENT)
    c.rect(0, H - bar_h - 3, W, 3, fill=1, stroke=0)

    # ── Odznaki dat ─────────────────────────────────────
    y_badges = H - bar_h - 28 * mm
    badge_w, badge_h = 52 * mm, 16 * mm

    badges = [
        ("Issue Date",  inv.h("FakturaDataWystawienia")),
        ("Due Date",    inv.h("FakturaDataPlatnosci")),
        ("Payment",     inv.h("FakturaTypPlatnosci")),
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

    # Waluta — z prawej
    bx_curr = W - 20 * mm - badge_w
    draw_rounded_rect(c, bx_curr, y_badges, badge_w, badge_h, 3, fill_color=LIGHT_BG)
    c.setFillColor(MID_GRAY)
    c.setFont(FONT, 7)
    c.drawString(bx_curr + 4 * mm, y_badges + badge_h - 5.5 * mm, "CURRENCY")
    c.setFillColor(DARK_TXT)
    c.setFont(FONT_B, 10)
    c.drawString(bx_curr + 4 * mm, y_badges + 3 * mm, inv.h("FakturaWaluta"))

    # ── Dostawca / Nabywca ──────────────────────────────
    y_boxes = y_badges - 42 * mm
    box_w = (W - 50 * mm) / 2
    box_h = 34 * mm

    # Dostawca (Supplier)
    draw_rounded_rect(c, 20 * mm, y_boxes, box_w, box_h, 4, fill_color=LIGHT_BG)
    c.setFillColor(ACCENT)
    c.setFont(FONT_B, 8)
    c.drawString(24 * mm, y_boxes + box_h - 6 * mm, "SUPPLIER")
    c.setFillColor(DARK_TXT)
    c.setFont(FONT_B, 10)
    c.drawString(24 * mm, y_boxes + box_h - 14 * mm, inv.h("DostawcaNazwa"))
    c.setFont(FONT, 9)
    c.setFillColor(MID_GRAY)
    c.drawString(24 * mm, y_boxes + box_h - 21 * mm, inv.h("DostawcaAdresUlica"))
    c.drawString(24 * mm, y_boxes + box_h - 27 * mm,
                 f"{inv.h('DostawcaAdresMiejscowosc')}, {inv.h('DostawcaAdresKodPocztowy')}")
    c.drawString(24 * mm, y_boxes + box_h - 33 * mm, f"VAT: {inv.h('DostawcaNIP')}")

    # Nabywca (Buyer)
    bx_b = 20 * mm + box_w + 10 * mm
    draw_rounded_rect(c, bx_b, y_boxes, box_w, box_h, 4, fill_color=LIGHT_BG)
    c.setFillColor(ACCENT)
    c.setFont(FONT_B, 8)
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 6 * mm, "BUYER")
    c.setFillColor(DARK_TXT)

    buyer_name = inv.h("NabywcaNazwa")
    c.setFont(FONT_B, 8.5 if len(buyer_name) > 38 else 10)
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 14 * mm, buyer_name)

    buyer_addr = inv.h("NabywcaAdresUlica")
    c.setFillColor(MID_GRAY)
    c.setFont(FONT, 7.5 if len(buyer_addr) > 42 else 8)
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 21 * mm, buyer_addr)
    c.setFont(FONT, 9)
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 27 * mm,
                 f"{inv.h('NabywcaAdresMiejscowosc')}, {inv.h('NabywcaAdresKodPocztowy')}")
    c.drawString(bx_b + 4 * mm, y_boxes + box_h - 33 * mm, f"VAT: {inv.h('NabywcaNIP')}")

    # ── Numer WZ ────────────────────────────────────────
    y_wz = y_boxes - 8 * mm
    wz = inv.h("FakturaNumeryWZ")
    if wz:
        c.setFillColor(MID_GRAY)
        c.setFont(FONT, 8)
        c.drawString(20 * mm, y_wz, f"Delivery Note (WZ): {wz}")

    # ── Tabela pozycji ──────────────────────────────────
    y_table_top = y_wz - 8 * mm
    col_widths = [8*mm, 18*mm, 60*mm, 12*mm, 12*mm, 22*mm, 14*mm, 25*mm]

    styles = getSampleStyleSheet()
    cs   = ParagraphStyle("C",  parent=styles["Normal"], fontSize=8, leading=10, textColor=DARK_TXT, fontName="DJV")
    cs_r = ParagraphStyle("CR", parent=cs, alignment=TA_RIGHT)
    cs_c = ParagraphStyle("CC", parent=cs, alignment=TA_CENTER)
    hs   = ParagraphStyle("H",  parent=styles["Normal"], fontSize=7, leading=9, textColor=WHITE, fontName="DJV-Bold")
    hs_r = ParagraphStyle("HR", parent=hs, alignment=TA_RIGHT)
    hs_c = ParagraphStyle("HC", parent=hs, alignment=TA_CENTER)

    data = [[
        Paragraph("#", hs_c), Paragraph("Code", hs), Paragraph("Description", hs),
        Paragraph("Qty", hs_c), Paragraph("Unit", hs_c), Paragraph("Unit Price", hs_r),
        Paragraph("VAT", hs_c), Paragraph("Net Total", hs_r),
    ]]

    iv = InvoiceData.item_val
    for idx, item in enumerate(inv.items, 1):
        data.append([
            Paragraph(str(idx), cs_c),
            Paragraph(iv(item, "TowarKod"), cs),
            Paragraph(iv(item, "TowarNazwa"), cs),
            Paragraph(iv(item, "Ilosc"), cs_c),
            Paragraph(iv(item, "TowarJm"), cs_c),
            Paragraph(f"{float(iv(item, 'CenaNetto') or 0):.2f}", cs_r),
            Paragraph(iv(item, "StawkaVat"), cs_c),
            Paragraph(f"{float(iv(item, 'WartoscNetto') or 0):.2f}", cs_r),
        ])

    tbl = Table(data, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND",     (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0), WHITE),
        ("FONTNAME",       (0, 0), (-1, 0), "DJV-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0), 7),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 3),
        ("LINEBELOW",      (0, 0), (-1, 0), 1, ACCENT),
        ("LINEBELOW",      (0, 1), (-1, -1), 0.3, LINE_GRY),
        ("ROUNDEDCORNERS", [4, 4, 0, 0]),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    tbl.setStyle(TableStyle(style_cmds))

    _, tbl_h = tbl.wrap(W - 40 * mm, 200 * mm)
    tbl.drawOn(c, 20 * mm, y_table_top - tbl_h)

    # ── Podsumowanie ────────────────────────────────────
    y_tot = y_table_top - tbl_h - 12 * mm
    tw = 70 * mm
    tx = W - 20 * mm - tw
    currency = inv.h("FakturaWaluta")

    draw_rounded_rect(c, tx, y_tot - 28 * mm, tw, 38 * mm, 4, fill_color=LIGHT_BG)

    c.setFillColor(MID_GRAY); c.setFont(FONT, 9)
    c.drawString(tx + 5 * mm, y_tot + 2 * mm, "Net Total:")
    c.setFillColor(DARK_TXT); c.setFont(FONT, 9)
    c.drawRightString(tx + tw - 5 * mm, y_tot + 2 * mm,
                      f"{currency} {float(inv.h('FakturaWartoscNetto') or 0):.2f}")

    c.setFillColor(MID_GRAY); c.setFont(FONT, 9)
    c.drawString(tx + 5 * mm, y_tot - 6 * mm, "VAT:")
    c.setFillColor(DARK_TXT)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 6 * mm,
                      f"{currency} {float(inv.h('FakturaWartoscVat') or 0):.2f}")

    c.setStrokeColor(ACCENT); c.setLineWidth(1)
    c.line(tx + 5 * mm, y_tot - 12 * mm, tx + tw - 5 * mm, y_tot - 12 * mm)

    c.setFillColor(NAVY); c.setFont(FONT_B, 12)
    c.drawString(tx + 5 * mm, y_tot - 22 * mm, "TOTAL:")
    c.setFillColor(ACCENT); c.setFont(FONT_B, 14)
    c.drawRightString(tx + tw - 5 * mm, y_tot - 22 * mm,
                      f"{currency} {float(inv.h('FakturaWartoscBrutto') or 0):.2f}")

    # ── Tabela partii / ważności ────────────────────────
    y_batch = y_tot - 46 * mm
    c.setFillColor(MID_GRAY); c.setFont(FONT, 7)
    c.drawString(20 * mm, y_batch + 4 * mm, "BATCH & EXPIRY DETAILS")

    ss   = ParagraphStyle("S",  parent=styles["Normal"], fontSize=7, leading=9, textColor=DARK_TXT, fontName="DJV")
    ss_c = ParagraphStyle("SC", parent=ss, alignment=TA_CENTER)
    sh   = ParagraphStyle("SH", parent=ss, fontName="DJV-Bold", textColor=WHITE, fontSize=6.5)
    sh_c = ParagraphStyle("SHC", parent=sh, alignment=TA_CENTER)

    bcols = [8*mm, 70*mm, 45*mm, 30*mm]
    bdata = [[Paragraph("#", sh_c), Paragraph("Product", sh),
              Paragraph("Batch / Lot No.", sh), Paragraph("Expiry Date", sh)]]

    for idx, item in enumerate(inv.items, 1):
        bdata.append([
            Paragraph(str(idx), ss_c),
            Paragraph(iv(item, "TowarNazwa"), ss),
            Paragraph(iv(item, "TowarDostawaNumerSerii"), ss),
            Paragraph(iv(item, "TowarDostawaDataWaznosci"), ss),
        ])

    bt = Table(bdata, colWidths=bcols)
    bstyle = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE_GRY),
        ("ROUNDEDCORNERS", [3, 3, 0, 0]),
    ]
    for i in range(1, len(bdata)):
        if i % 2 == 0:
            bstyle.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    bt.setStyle(TableStyle(bstyle))
    _, bh = bt.wrap(W - 40 * mm, 100 * mm)
    bt.drawOn(c, 20 * mm, y_batch - bh)

    draw_footer(c, inv, 1, total_pages)


# ╔══════════════════════════════════════════════════════════╗
# ║  STRONA 2+ — KODY KRESKOWE EAN-128 / GS1-128            ║
# ╚══════════════════════════════════════════════════════════╝

def draw_barcode_pages(c, inv: InvoiceData, total_pages: int):
    """Rysuje strony z kodami kreskowymi EAN-128 dla każdej pozycji."""
    iv = InvoiceData.item_val

    # Sprawdź, czy w ogóle są kody EAN-128
    has_barcodes = any(iv(item, "TowarKodEan128") for item in inv.items)
    if not has_barcodes:
        return

    c.showPage()
    page_num = 2
    margin_x = 20 * mm
    card_w = W - 40 * mm
    card_h = 40 * mm
    gap = 3 * mm

    def draw_barcode_header(title_suffix=""):
        bar_h2 = 20 * mm
        c.setFillColor(NAVY)
        c.rect(0, H - bar_h2, W, bar_h2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(FONT_B, 14)
        label = f"Invoice #{inv.h('FakturaNumer')} — EAN-128 / GS1-128 Barcodes{title_suffix}"
        c.drawString(20 * mm, H - 14 * mm, label)
        c.setFillColor(ACCENT)
        c.rect(0, H - bar_h2 - 2.5, W, 2.5, fill=1, stroke=0)
        return H - bar_h2 - 18 * mm

    y_cursor = draw_barcode_header()

    for idx, item in enumerate(inv.items, 1):
        ean128 = iv(item, "TowarKodEan128")
        if not ean128:
            continue

        ean    = iv(item, "TowarKodEan")
        name   = iv(item, "TowarNazwa")
        code   = iv(item, "TowarKod")
        batch  = iv(item, "TowarDostawaNumerSerii")
        expiry = iv(item, "TowarDostawaDataWaznosci")

        # Karta
        draw_rounded_rect(c, margin_x, y_cursor - card_h, card_w, card_h, 4,
                          fill_color=LIGHT_BG, stroke_color=LINE_GRY)

        # Info po lewej
        ix = margin_x + 5 * mm
        iy = y_cursor - 8 * mm

        c.setFillColor(ACCENT); c.setFont(FONT_B, 7)
        c.drawString(ix, iy, f"ITEM {idx}")

        c.setFillColor(DARK_TXT); c.setFont(FONT_B, 10)
        c.drawString(ix, iy - 8 * mm, name)

        c.setFillColor(DARK_TXT); c.setFont(FONT, 7.5)
        c.drawString(ix, iy - 15 * mm, f"Code: {code}")
        c.drawString(ix + 32 * mm, iy - 15 * mm, f"EAN: {ean}")
        c.drawString(ix, iy - 20.5 * mm, f"Batch: {batch}    |    Expiry: {expiry}")

        # Kod kreskowy — wyrównany do prawej krawędzi karty
        bc_h = 18 * mm
        card_right = margin_x + card_w - 5 * mm
        bc = code128.Code128(ean128, barWidth=0.26 * mm, barHeight=bc_h, humanReadable=False)
        bc_x = card_right - bc.width
        bc_y = y_cursor - card_h + 6 * mm
        bc.drawOn(c, bc_x, bc_y)

        # Numer GS1-128 pod kodem kreskowym
        c.setFillColor(DARK_TXT); c.setFont(FONT, 5.5)
        c.drawRightString(card_right, bc_y - 4 * mm, f"GS1-128: {ean128}")

        y_cursor -= (card_h + gap)

        # Nowa strona jeśli brak miejsca
        if y_cursor - card_h < 30 * mm and idx < len(inv.items):
            draw_footer(c, inv, page_num, total_pages)
            c.showPage()
            page_num += 1
            y_cursor = draw_barcode_header(" (cont.)")

    draw_footer(c, inv, page_num, total_pages)


# ╔══════════════════════════════════════════════════════════╗
# ║  GŁÓWNA FUNKCJA KONWERSJI                               ║
# ╚══════════════════════════════════════════════════════════╝

def xml_to_pdf(xml_path: str, output_path: str | None = None,
               include_barcodes: bool = True, font_dir: str | None = None) -> str:
    """
    Konwertuje fakturę XML do PDF.

    Args:
        xml_path:         Ścieżka do pliku XML faktury
        output_path:      Ścieżka wyjściowa PDF (domyślnie: ten sam katalog, rozszerzenie .pdf)
        include_barcodes: Czy generować stronę z kodami EAN-128
        font_dir:         Opcjonalny katalog z czcionkami DejaVuSans*.ttf

    Returns:
        Ścieżka do wygenerowanego pliku PDF
    """
    if not os.path.isfile(xml_path):
        raise FileNotFoundError(f"Nie znaleziono pliku: {xml_path}")

    if output_path is None:
        output_path = os.path.splitext(xml_path)[0] + ".pdf"

    register_fonts(font_dir)
    inv = InvoiceData(xml_path)

    # Oblicz liczbę stron
    total_pages = 1
    if include_barcodes:
        iv = InvoiceData.item_val
        barcode_count = sum(1 for item in inv.items if iv(item, "TowarKodEan128"))
        if barcode_count > 0:
            # ~5 kodów na stronę (card_h=40mm + gap=3mm ≈ 43mm, dostępne ≈ 215mm)
            import math
            total_pages += math.ceil(barcode_count / 5)

    c = canvas.Canvas(output_path, pagesize=A4)
    draw_page1(c, inv, total_pages)

    if include_barcodes:
        draw_barcode_pages(c, inv, total_pages)

    c.save()
    return output_path


# ╔══════════════════════════════════════════════════════════╗
# ║  CLI                                                     ║
# ╚══════════════════════════════════════════════════════════╝

def main():
    parser = argparse.ArgumentParser(
        description="Konwersja faktur XML → PDF z kodami EAN-128",
        epilog="Przykłady:\n"
               "  python xml_invoice_to_pdf.py faktura.xml\n"
               "  python xml_invoice_to_pdf.py faktura.xml -o wynik.pdf\n"
               "  python xml_invoice_to_pdf.py *.xml\n"
               "  python xml_invoice_to_pdf.py faktura.xml --no-barcodes\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("xml_files", nargs="+", help="Pliki XML faktur do konwersji")
    parser.add_argument("-o", "--output", help="Ścieżka wyjściowa PDF (tylko dla 1 pliku)")
    parser.add_argument("--no-barcodes", action="store_true",
                        help="Pomiń stronę z kodami kreskowymi EAN-128")
    parser.add_argument("--font-dir", help="Katalog z czcionkami DejaVuSans*.ttf")

    args = parser.parse_args()

    if args.output and len(args.xml_files) > 1:
        parser.error("Opcja -o/--output dostępna tylko dla pojedynczego pliku.")

    success, failed = 0, 0
    for xml_path in args.xml_files:
        try:
            out = xml_to_pdf(
                xml_path,
                output_path=args.output,
                include_barcodes=not args.no_barcodes,
                font_dir=args.font_dir,
            )
            print(f"✓ {xml_path} → {out}")
            success += 1
        except Exception as e:
            print(f"✗ {xml_path} — Błąd: {e}", file=sys.stderr)
            failed += 1

    if len(args.xml_files) > 1:
        print(f"\nGotowe: {success} sukces, {failed} błędów")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
