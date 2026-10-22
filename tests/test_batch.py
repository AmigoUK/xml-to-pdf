"""Batch planning and running: names, collisions, progress, stop, isolation."""

import dataclasses
import os

import pytest

from batch import collect_xml_files, plan_batch, run_batch
from conftest import build_invoice_xml, pdf_words
from mapping import MappingConfig


@pytest.fixture
def three_invoices(tmp_path):
    root = tmp_path / "in"
    files = []
    for sub, number in (("a", "INV-1"), ("b", "INV-2"), ("c", "INV-1")):
        (root / sub).mkdir(parents=True)
        files.append(build_invoice_xml(
            str(root / sub / "invoice.xml"),
            header_overrides={"InvoiceNumber": number, "IssueDate": "2026-03-10"}))
    return root, sorted(files)


def test_collect_deduplicates_and_sorts(three_invoices):
    root, files = three_invoices
    assert collect_xml_files([str(root), files[0]]) == sorted(files)


def test_collect_matches_extension_case_insensitively(tmp_path):
    (tmp_path / "A.XML").write_text("<x/>")
    (tmp_path / "b.txt").write_text("x")
    assert collect_xml_files([str(tmp_path)]) == [str(tmp_path / "A.XML")]


def test_plan_names_and_collisions(three_invoices, british_config, tmp_path):
    plan = plan_batch(three_invoices[1], british_config, str(tmp_path / "out"),
                      pattern="{period}_{invoice_number}")
    assert [f.filename for f in plan.files] == \
        ["2026-03_INV-1.pdf", "2026-03_INV-2.pdf", "2026-03_INV-1_2.pdf"]


def test_plan_empty_pattern_uses_xml_stem(three_invoices, british_config, tmp_path):
    plan = plan_batch(three_invoices[1], british_config, str(tmp_path / "out"), pattern="")
    assert [f.filename for f in plan.files] == ["invoice.pdf", "invoice_2.pdf", "invoice_3.pdf"]


def test_pattern_none_uses_config_pattern(three_invoices, british_config, tmp_path):
    cfg = dataclasses.replace(british_config, filename_pattern="{invoice_number}")
    plan = plan_batch(three_invoices[1], cfg, str(tmp_path / "out"))
    assert plan.files[0].filename == "INV-1.pdf"


def test_pattern_that_sanitises_to_nothing_falls_back_to_xml_stem(
        three_invoices, british_config, tmp_path):
    plan = plan_batch(three_invoices[1][:1], british_config, str(tmp_path / "o"),
                      pattern="///")
    assert plan.files[0].filename == "invoice.pdf"


def test_plan_rejects_bad_pattern(three_invoices, british_config, tmp_path):
    from naming import PatternError
    with pytest.raises(PatternError):
        plan_batch(three_invoices[1], british_config, str(tmp_path), pattern="{nope}")


def test_plan_does_not_mutate_config(three_invoices, british_config, tmp_path):
    before = dataclasses.asdict(british_config)
    plan_batch(three_invoices[1], british_config, str(tmp_path / "o"), pattern="{period}")
    assert dataclasses.asdict(british_config) == before


def test_run_writes_pdfs_and_reports_progress(three_invoices, british_config, fonts_dir, tmp_path):
    out = tmp_path / "out"
    plan = plan_batch(three_invoices[1], british_config, str(out), pattern="{invoice_number}")
    seen = []
    res = run_batch(plan, british_config, font_dir=fonts_dir,
                    on_progress=lambda i, n, f: seen.append((i, n)))
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert sorted(os.listdir(out)) == ["INV-1.pdf", "INV-1_2.pdf", "INV-2.pdf"]
    assert "INV-2" in " ".join(w.text for w in pdf_words(str(out / "INV-2.pdf")))
    assert len(res.succeeded) == 3 and not res.failed


def test_broken_file_fails_alone(three_invoices, british_config, fonts_dir, tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<not-closed>", encoding="utf-8")
    files = three_invoices[1] + [str(bad)]
    res = run_batch(plan_batch(files, british_config, str(tmp_path / "o"),
                               pattern="{invoice_number}"),
                    british_config, font_dir=fonts_dir)
    assert len(res.succeeded) == 3 and [s for s, _ in res.failed] == [str(bad)]


def test_stop_finishes_current_and_skips_rest(three_invoices, british_config, fonts_dir, tmp_path):
    calls = []
    res = run_batch(plan_batch(three_invoices[1], british_config, str(tmp_path / "o")),
                    british_config, font_dir=fonts_dir,
                    on_progress=lambda i, n, f: calls.append(i),
                    should_stop=lambda: len(calls) >= 1)
    assert res.stopped and len(res.succeeded) == 1 and calls == [1]


def test_never_overwrites_file_created_after_planning(
        three_invoices, british_config, fonts_dir, tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    plan = plan_batch(three_invoices[1][:1], british_config, str(out), pattern="{invoice_number}")
    (out / "INV-1.pdf").write_bytes(b"keep me")
    run_batch(plan, british_config, font_dir=fonts_dir)
    assert (out / "INV-1.pdf").read_bytes() == b"keep me" and (out / "INV-1_2.pdf").exists()
