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
    assert "3 sukces" in proc.stdout, proc.stdout

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
    assert "1 sukces, 1 bledow" in proc.stdout, proc.stdout
    assert os.path.isfile(os.path.splitext(good)[0] + ".pdf")
