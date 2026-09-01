"""Barcode pages must carry conformant GS1-128 symbols, not literal text."""

import shutil
import subprocess

import pytest

from pdf_renderer import gs1_encode, xml_to_pdf

FNC1 = "\xf1"


def _decode(pdf_path: str, tmp_path) -> list[str]:
    """Render every page at 300 dpi and decode all barcodes found, in order."""
    for tool in ("pdftoppm", "zbarimg"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not installed")

    prefix = str(tmp_path / "scan")
    subprocess.run(["pdftoppm", "-r", "300", "-png", pdf_path, prefix],
                   check=True, capture_output=True)
    images = sorted(tmp_path.glob("scan*.png"))
    assert images, "the PDF did not render"

    out = subprocess.run(["zbarimg", "--raw", "-q", *map(str, images)],
                         capture_output=True)
    return [line for line in out.stdout.decode("utf-8", "replace").splitlines() if line]


# ── gs1_encode ───────────────────────────────────────────────

def test_parentheses_are_stripped_and_fnc1_is_prefixed():
    assert gs1_encode("(01)05060412780011(17)280930(10)GAU-240917-A") == (
        FNC1 + "01" + "05060412780011" + "17" + "280930" + "10" + "GAU-240917-A"
    )


def test_no_separator_is_added_after_a_predefined_length_ai():
    """AI 01 carries exactly 14 digits, so no FNC1 may follow its data."""
    encoded = gs1_encode("(01)05060412780011(10)LOT1")
    assert encoded == FNC1 + "0105060412780011" + "10LOT1"
    assert encoded.count(FNC1) == 1


def test_a_variable_length_ai_is_terminated_when_another_element_follows():
    encoded = gs1_encode("(10)LOT1(17)280930")
    assert encoded == FNC1 + "10LOT1" + FNC1 + "17280930"


def test_a_trailing_variable_length_ai_needs_no_separator():
    encoded = gs1_encode("(01)05060412780011(21)SERIAL9")
    assert encoded == FNC1 + "0105060412780011" + "21SERIAL9"
    assert not encoded.endswith(FNC1)


def test_four_digit_ais_are_recognised_as_predefined_length():
    """3103 (net weight, 3 decimals) carries 6 digits and needs no separator."""
    encoded = gs1_encode("(3103)000123(10)LOT1")
    assert encoded == FNC1 + "3103000123" + "10LOT1"


def test_whitespace_around_elements_is_ignored():
    assert gs1_encode(" (01) 05060412780011 ") == FNC1 + "0105060412780011"


def test_a_value_without_parentheses_is_left_alone():
    """Without AI delimiters the boundaries are unknowable, so do not guess."""
    assert gs1_encode("ABC123") == "ABC123"


def test_an_empty_value_stays_empty():
    assert gs1_encode("") == ""


# ── end to end ───────────────────────────────────────────────

def test_rendered_barcode_decodes_without_parentheses(make_invoice, fonts_dir, tmp_path):
    """A scanner must receive AI data, not the human-readable form."""
    xml = make_invoice(items=2)
    out = str(tmp_path / "codes.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    decoded = _decode(out, tmp_path)
    assert decoded, "no barcode could be decoded from the barcode page"
    for value in decoded:
        assert "(" not in value and ")" not in value, f"parentheses were encoded: {value}"
        assert value.startswith("01"), f"expected an AI-prefixed payload, got {value}"


def test_rendered_barcode_carries_the_expected_ai_data(make_invoice, fonts_dir, tmp_path):
    xml = make_invoice(items=1)
    out = str(tmp_path / "one.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    decoded = _decode(out, tmp_path)
    assert decoded == ["01" + "0506041278" + "0001" + "17" + "290131" + "10" + "LOT-0001"]


def test_human_readable_line_keeps_the_parenthesised_form(make_invoice, fonts_dir,
                                                          tmp_path):
    """GS1 prescribes the (AI)data form for the text printed under the symbol."""
    from conftest import pdf_words

    xml = make_invoice(items=1)
    out = str(tmp_path / "hri.pdf")
    xml_to_pdf(xml, out, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "(01)" in text and "(17)" in text and "(10)" in text
