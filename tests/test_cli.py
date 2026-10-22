"""The CLI must not silently override what a config says."""

import json
import os
import subprocess
import sys

import pytest

from conftest import CONFIGS_DIR, PROJECT_ROOT, pdf_page_count, pdf_words

CLI = os.path.join(PROJECT_ROOT, "xml_invoice_to_pdf.py")


def run_cli(*args, expect_success=True):
    proc = subprocess.run([sys.executable, CLI, *args],
                          capture_output=True, text=True, cwd=PROJECT_ROOT)
    if expect_success:
        assert proc.returncode == 0, f"CLI failed:\n{proc.stdout}\n{proc.stderr}"
    return proc


@pytest.fixture
def config_no_barcodes(tmp_path):
    with open(os.path.join(CONFIGS_DIR, "british_english.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["include_barcodes"] = False
    path = tmp_path / "no_barcodes.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def test_cli_honours_include_barcodes_false_from_the_config(
        make_invoice, tmp_path, config_no_barcodes, fonts_dir):
    xml = make_invoice(items=5)
    out = str(tmp_path / "cfg.pdf")

    run_cli(xml, "-o", out, "--config", config_no_barcodes, "--font-dir", fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "GS1-128:" not in text, "the config asked for no barcode pages"


def test_cli_produces_barcodes_when_the_config_asks_for_them(
        make_invoice, tmp_path, fonts_dir):
    xml = make_invoice(items=5)
    out = str(tmp_path / "yes.pdf")

    run_cli(xml, "-o", out, "--config",
            os.path.join(CONFIGS_DIR, "british_english.json"), "--font-dir", fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "GS1-128:" in text


def test_cli_no_barcodes_flag_overrides_the_config(make_invoice, tmp_path, fonts_dir):
    xml = make_invoice(items=5)
    out = str(tmp_path / "flag.pdf")

    run_cli(xml, "-o", out, "--no-barcodes", "--config",
            os.path.join(CONFIGS_DIR, "british_english.json"), "--font-dir", fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "GS1-128:" not in text


def test_batch_conversion_keeps_each_file_independent(make_invoice, tmp_path, fonts_dir):
    """One shared config object must not accumulate overrides across files."""
    first = make_invoice(items=4)
    second = make_invoice(items=6, items_with_barcode=0)
    third = make_invoice(items=4)

    proc = run_cli(first, second, third, "--font-dir", fonts_dir, "--config",
                   os.path.join(CONFIGS_DIR, "british_english.json"))
    assert "3 succeeded" in proc.stdout, proc.stdout

    for xml in (first, third):
        pdf = os.path.splitext(xml)[0] + ".pdf"
        text = " ".join(w.text for w in pdf_words(pdf))
        assert "GS1-128:" in text, f"{pdf} lost its barcode pages"


def test_cli_reports_a_readable_error_for_a_broken_file(tmp_path, fonts_dir):
    bad = tmp_path / "broken.xml"
    bad.write_text("<Document><Invoice></Invoice>", encoding="utf-8")

    proc = run_cli(str(bad), "--font-dir", fonts_dir, expect_success=False)
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr


def test_cli_keeps_going_after_one_bad_file(make_invoice, tmp_path, fonts_dir):
    good = make_invoice(items=3)
    bad = tmp_path / "broken.xml"
    bad.write_text("<nope/>", encoding="utf-8")

    proc = run_cli(str(bad), good, "--font-dir", fonts_dir, expect_success=False)
    assert "1 succeeded, 1 failed" in proc.stdout, proc.stdout
    assert os.path.isfile(os.path.splitext(good)[0] + ".pdf")


def test_user_facing_output_is_english(make_invoice, tmp_path, fonts_dir):
    """The repo, README, GUI and PDF are English; the CLI must not be the odd one out."""
    xml = make_invoice(items=2)
    proc = run_cli(xml, "-o", str(tmp_path / "en.pdf"), "--font-dir", fonts_dir)

    combined = proc.stdout + proc.stderr
    for polish in ("Blad", "Sciezka", "Gotowe", "sukces", "bledow", "Pliki XML"):
        assert polish not in combined, f"Polish string {polish!r} still reaches the user"


def test_help_text_is_english(fonts_dir):
    proc = run_cli("--help")
    for polish in ("Konwersja", "Przyklady", "Sciezka", "Katalog", "Uruchom", "Pomin"):
        assert polish not in proc.stdout, f"Polish string {polish!r} in --help"
    assert "Convert" in proc.stdout or "convert" in proc.stdout


def test_error_for_a_missing_file_is_english(tmp_path, fonts_dir):
    proc = run_cli(str(tmp_path / "nope.xml"), "--font-dir", fonts_dir,
                   expect_success=False)
    assert "Nie znaleziono" not in proc.stderr
    assert "not found" in proc.stderr.lower()


# ── Batch to a folder ─────────────────────────────────────────────

@pytest.fixture
def two_invoices(tmp_path):
    from conftest import build_invoice_xml
    root = tmp_path / "in"
    for sub, num in (("a", "INV-1"), ("b", "INV-2")):
        (root / sub).mkdir(parents=True)
        build_invoice_xml(str(root / sub / "invoice.xml"),
                          header_overrides={"InvoiceNumber": num, "IssueDate": "2026-03-10"})
    return root


def _profile_with_pattern(tmp_path, pattern):
    with open(os.path.join(CONFIGS_DIR, "british_english.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["filename_pattern"] = pattern
    path = tmp_path / "pat.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def test_cli_batch_to_folder_with_pattern(two_invoices, tmp_path, fonts_dir):
    out = str(tmp_path / "out")
    proc = run_cli(str(two_invoices), "--output-dir", out, "--name-pattern",
                   "{period}_{invoice_number}", "--config", "british_english",
                   "--font-dir", fonts_dir)
    assert sorted(os.listdir(out)) == ["2026-03_INV-1.pdf", "2026-03_INV-2.pdf"]
    assert "[2/2] OK" in proc.stdout


def test_cli_dry_run_writes_nothing(two_invoices, tmp_path, fonts_dir):
    out = str(tmp_path / "out")
    proc = run_cli(str(two_invoices), "--output-dir", out, "--name-pattern",
                   "{period}_{invoice_number}", "--config", "british_english",
                   "--dry-run", "--font-dir", fonts_dir)
    assert not os.path.exists(out)
    assert "-> 2026-03_INV-1.pdf" in proc.stdout
    assert "2 files planned" in proc.stdout


def test_cli_dry_run_shows_missing_field_warning(tmp_path, fonts_dir):
    from conftest import build_invoice_xml
    xml = build_invoice_xml(str(tmp_path / "x.xml"), header_overrides={"BuyerName": ""})
    proc = run_cli(xml, "--output-dir", str(tmp_path / "out"), "--name-pattern",
                   "{buyer_name}", "--config", "british_english", "--dry-run")
    assert "warning: missing buyer_name" in proc.stdout


def test_cli_pattern_from_profile(two_invoices, tmp_path, fonts_dir):
    out = str(tmp_path / "out")
    run_cli(str(two_invoices), "--output-dir", out, "--config",
            _profile_with_pattern(tmp_path, "{invoice_number}"), "--font-dir", fonts_dir)
    assert sorted(os.listdir(out)) == ["INV-1.pdf", "INV-2.pdf"]


def test_cli_without_output_dir_ignores_profile_pattern(tmp_path, fonts_dir):
    from conftest import build_invoice_xml
    xml = build_invoice_xml(str(tmp_path / "invoice.xml"))
    run_cli(xml, "--config", _profile_with_pattern(tmp_path, "{invoice_number}"),
            "--font-dir", fonts_dir)
    assert os.path.exists(tmp_path / "invoice.pdf")


def test_cli_pattern_needs_output_dir(tmp_path):
    from conftest import build_invoice_xml
    xml = build_invoice_xml(str(tmp_path / "x.xml"))
    for flag in (["--name-pattern", "{invoice_number}"], ["--dry-run"]):
        proc = run_cli(xml, *flag, expect_success=False)
        assert proc.returncode == 2
        assert "need --output-dir" in proc.stderr


def test_cli_o_conflicts_with_output_dir(tmp_path):
    from conftest import build_invoice_xml
    xml = build_invoice_xml(str(tmp_path / "x.xml"))
    proc = run_cli(xml, "-o", str(tmp_path / "a.pdf"), "--output-dir",
                   str(tmp_path / "o"), expect_success=False)
    assert proc.returncode == 2
    assert "cannot be combined" in proc.stderr


def test_cli_unknown_field_is_a_usage_error(tmp_path):
    from conftest import build_invoice_xml
    xml = build_invoice_xml(str(tmp_path / "x.xml"))
    proc = run_cli(xml, "--output-dir", str(tmp_path / "o"), "--name-pattern",
                   "{nope}", expect_success=False)
    assert proc.returncode == 2
    assert "nope" in proc.stderr


def test_cli_empty_folder_is_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = run_cli(str(empty), "--output-dir", str(tmp_path / "o"), expect_success=False)
    assert proc.returncode == 1
    assert "no XML files found" in proc.stderr


# ── Legacy path stays as it was when folders are accepted ─────────

def test_cli_legacy_keeps_argument_order_and_duplicates(tmp_path, fonts_dir):
    from conftest import build_invoice_xml
    a = build_invoice_xml(str(tmp_path / "a.xml"))
    b = build_invoice_xml(str(tmp_path / "b.xml"))
    proc = run_cli(b, a, b, "--font-dir", fonts_dir)
    ok = [l for l in proc.stdout.splitlines() if l.startswith("OK ")]
    assert [l.split()[1] for l in ok] == [b, a, b]
    assert "Done: 3 succeeded" in proc.stdout


def test_cli_legacy_folder_converts_next_to_each_xml(two_invoices, fonts_dir):
    run_cli(str(two_invoices), "--font-dir", fonts_dir)
    assert os.path.exists(two_invoices / "a" / "invoice.pdf")
    assert os.path.exists(two_invoices / "b" / "invoice.pdf")


def test_cli_folder_with_o_and_several_xmls_is_a_usage_error(two_invoices, tmp_path):
    proc = run_cli(str(two_invoices), "-o", str(tmp_path / "out.pdf"),
                   expect_success=False)
    assert proc.returncode == 2
    assert "single input file" in proc.stderr
    assert not os.path.exists(tmp_path / "out.pdf")


def test_cli_legacy_empty_folder_is_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = run_cli(str(empty), expect_success=False)
    assert proc.returncode == 1
    assert "no XML files found" in proc.stderr


def test_cli_folder_mode_reports_a_broken_xml_live(two_invoices, tmp_path, fonts_dir):
    (two_invoices / "bad.xml").write_text("<not-closed>", encoding="utf-8")
    out = tmp_path / "out"
    proc = run_cli(str(two_invoices), "--output-dir", str(out), "--font-dir", fonts_dir,
                   expect_success=False)
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr and "/3]" in proc.stderr
    assert "Done: 2 succeeded, 1 failed" in proc.stdout
