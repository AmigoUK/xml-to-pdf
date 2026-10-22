import re

import pytest
from naming import (NAME_FIELDS, NameAllocator, PatternError, build_stem, parse_period,
                    sanitize, validate_pattern, MAX_STEM_BYTES)

V = {"issue_date": "2026-10-22", "invoice_number": "FV/2026/10",
     "supplier_name": "Acme Ltd"}

def test_name_fields_are_header_slots_plus_period():
    assert "invoice_number" in NAME_FIELDS and NAME_FIELDS[-1] == "period"
    assert "item_code" not in NAME_FIELDS

def test_validate_pattern_returns_fields_in_order():
    assert validate_pattern("{period}_{invoice_number}") == ["period", "invoice_number"]

@pytest.mark.parametrize("bad", ["{nope}", "{period", "period}", "{item_code}"])
def test_validate_pattern_rejects(bad):
    with pytest.raises(PatternError):
        validate_pattern(bad)

@pytest.mark.parametrize("text,expected", [
    ("2026-10-22", "2026-10"), ("2026-10-22T08:00:00", "2026-10"),
    ("2026-10-22 08:00", "2026-10"), ("22.10.2026", "2026-10"),
    ("22/10/2026", "2026-10"), ("", ""), ("next week", ""), ("2026-13-01", ""),
])
def test_parse_period(text, expected):
    assert parse_period(text) == expected

def test_build_stem_substitutes_and_drops_forbidden():
    assert build_stem("{period}_{invoice_number}_{supplier_name}", V) == \
        ("2026-10_FV202610_Acme Ltd", [])

def test_missing_field_gets_placeholder_and_warning():
    stem, warnings = build_stem("{period}_{buyer_name}", V)
    assert stem == "2026-10_no-buyer_name"
    assert warnings == ["missing buyer_name"]

def test_unparseable_date_is_missing_period():
    stem, warnings = build_stem("{period}", {"issue_date": "soon"})
    assert (stem, warnings) == ("no-period", ["missing period"])

def test_sanitize_keeps_non_ascii():
    assert sanitize("Łódź Sp. z o.o.") == "Łódź Sp. z o.o"   # trailing dot stripped
    assert sanitize("Müller GmbH") == "Müller GmbH"

def test_sanitize_drops_controls_and_collapses_space():
    # whitespace (tabs, newlines) collapses to one space first; then forbidden
    # characters and the remaining controls are dropped
    assert sanitize('  a\tb \x00c:  d*"e  ') == "a b c de"

def test_pattern_literal_slash_is_dropped():
    stem, _ = build_stem("{period}/{supplier_name}", V)
    assert stem == "2026-10Acme Ltd" and "/" not in stem

def test_value_empty_after_sanitising_is_missing():
    stem, warnings = build_stem("{invoice_number}", {"invoice_number": "///"})
    assert (stem, warnings) == ("no-invoice_number", ["missing invoice_number"])

@pytest.mark.parametrize("value", ["CON", "nul", "Com1", "LPT9"])
def test_reserved_windows_names_get_underscore(value):
    assert build_stem("{invoice_number}", {"invoice_number": value})[0] == value + "_"

def test_stem_is_capped():
    stem, _ = build_stem("{supplier_name}", {"supplier_name": "x" * 500})
    assert len(stem) == MAX_STEM_BYTES

def test_allocator_suffixes_duplicates_in_batch(tmp_path):
    a = NameAllocator(str(tmp_path))
    assert [a.allocate("x"), a.allocate("x"), a.allocate("X")] == \
        ["x.pdf", "x_2.pdf", "X_3.pdf"]

def test_allocator_respects_existing_files_case_insensitively(tmp_path):
    (tmp_path / "2026-03_INV-TEST.PDF").write_bytes(b"old")
    a = NameAllocator(str(tmp_path))
    assert a.allocate("2026-03_inv-test") == "2026-03_inv-test_2.pdf"

def test_allocator_sees_files_created_after_snapshot(tmp_path):
    a = NameAllocator(str(tmp_path))
    (tmp_path / "late.pdf").write_bytes(b"x")
    assert a.allocate("late") == "late_2.pdf"

def test_allocator_on_missing_folder(tmp_path):
    assert NameAllocator(str(tmp_path / "new")).allocate("a") == "a.pdf"

def test_stem_is_capped_in_utf8_bytes_and_writable(tmp_path):
    # ext4/APFS limit a name to 255 *bytes*; 150 two-byte letters are 300.
    stem, _ = build_stem("{supplier_name}", {"supplier_name": "ł" * 150})
    assert len(stem.encode("utf-8")) <= MAX_STEM_BYTES
    assert stem == "ł" * 100
    (tmp_path / (stem + "_99.pdf")).write_bytes(b"x")   # must not raise ENAMETOOLONG

def test_byte_cap_never_splits_a_character():
    # 199 ASCII bytes + a 2-byte letter would be 201: the letter is dropped whole.
    stem, _ = build_stem("{supplier_name}", {"supplier_name": "x" * 199 + "ł" * 5})
    assert stem == "x" * 199

@pytest.mark.parametrize("value,expected", [
    (".hidden", "hidden"), ("...x", "x"), (". .x", "x"), ("..", "no-invoice_number"),
])
def test_leading_dots_are_stripped(value, expected):
    # A name starting with "." is a hidden file on macOS and Linux.
    assert build_stem("{invoice_number}", {"invoice_number": value})[0] == expected

def test_leading_dot_in_pattern_literal_is_stripped():
    assert build_stem(".{invoice_number}", {"invoice_number": "A"})[0] == "A"

@pytest.mark.parametrize("bad,field", [("{Period}", "Period"), ("{invoice-number}", "invoice-number"),
                                       ("{}", "")])
def test_unknown_field_is_named_even_with_odd_characters(bad, field):
    with pytest.raises(PatternError, match=r"unknown field \{" + re.escape(field) + r"\}"):
        validate_pattern(bad)

def test_nested_brace_is_still_unmatched():
    with pytest.raises(PatternError, match="unmatched"):
        validate_pattern("{{period}")

def test_reserved_name_check_runs_after_leading_dots_go():
    assert build_stem("{invoice_number}", {"invoice_number": ".con"})[0] == "con_"
