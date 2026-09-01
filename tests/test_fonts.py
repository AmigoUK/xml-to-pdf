"""Font registration must work with the two faces the renderer actually uses."""

import os

import pytest

from pdf_renderer import register_fonts, xml_to_pdf, FONT, FONT_B


def test_registers_successfully_without_italic_faces(core_fonts_dir):
    """Regular + Bold is enough — the renderer never draws italic text."""
    assert register_fonts(core_fonts_dir) is True


def test_registered_faces_are_usable_after_core_only_registration(core_fonts_dir):
    from reportlab.pdfbase import pdfmetrics

    register_fonts(core_fonts_dir)
    assert pdfmetrics.stringWidth("test", FONT, 10) > 0
    assert pdfmetrics.stringWidth("test", FONT_B, 10) > 0


def test_renders_a_pdf_with_core_fonts_only(make_invoice, core_fonts_dir, tmp_path):
    """The end-to-end path must not blow up when italic faces are absent."""
    xml = make_invoice(items=3)
    out = str(tmp_path / "core.pdf")
    xml_to_pdf(xml, out, font_dir=core_fonts_dir)
    assert os.path.getsize(out) > 0


def test_missing_regular_face_raises_a_clear_error(tmp_path, make_invoice):
    """A directory without DejaVuSans.ttf must fail loudly, not crash deep in ReportLab."""
    empty = tmp_path / "no_fonts"
    empty.mkdir()
    xml = make_invoice(items=2)

    with pytest.raises(FileNotFoundError, match="DejaVuSans.ttf"):
        xml_to_pdf(xml, str(tmp_path / "x.pdf"), font_dir=str(empty))
