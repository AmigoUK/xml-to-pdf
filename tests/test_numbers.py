"""Amounts must survive real-world number formats instead of killing the conversion."""

import pytest

from pdf_renderer import parse_amount, format_amount, xml_to_pdf
from conftest import pdf_words


@pytest.mark.parametrize("raw,expected", [
    ("1.50", 1.50),
    ("1,50", 1.50),            # Polish / German decimal comma
    ("1 234,56", 1234.56),     # space as thousands separator
    ("1 234,56", 1234.56),  # non-breaking space, as Excel exports it
    ("1,234.56", 1234.56),     # English thousands separator
    ("1.234,56", 1234.56),     # German thousands separator
    ("2 985,00 PLN", 2985.00),  # trailing currency code
    ("-12,30", -12.30),
    ("", 0.0),
    ("   ", 0.0),
    (None, 0.0),
    ("n/a", 0.0),              # unparseable must not raise
])
def test_parse_amount_handles_common_formats(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


def test_format_amount_uses_two_decimals():
    assert format_amount("1,50") == "1.50"
    assert format_amount("") == "0.00"


def test_decimal_comma_does_not_abort_the_conversion(make_invoice, fonts_dir, tmp_path):
    """A single comma-formatted price used to raise ValueError and produce no PDF."""
    xml = make_invoice(items=3, item_overrides={"UnitPrice": "1,50", "NetAmount": "4,50"})
    out = str(tmp_path / "comma.pdf")

    xml_to_pdf(xml, out, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "1.50" in text and "4.50" in text


def test_unparseable_amount_renders_as_zero_rather_than_failing(
        make_invoice, fonts_dir, tmp_path):
    xml = make_invoice(items=2, item_overrides={"UnitPrice": "brak danych"})
    out = str(tmp_path / "junk.pdf")

    xml_to_pdf(xml, out, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "0.00" in text


def test_comma_formatted_totals_reach_the_summary(make_invoice, fonts_dir, tmp_path):
    xml = make_invoice(items=2, header_overrides={
        "NetTotal": "2 487,50", "VatTotal": "497,50", "GrossTotal": "2 985,00",
    })
    out = str(tmp_path / "totals.pdf")

    xml_to_pdf(xml, out, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "2487.50" in text
    assert "2985.00" in text
