"""Config files must be complete, honoured, and consistent about their defaults."""

import copy
import glob
import json
import os

import pytest

from conftest import CONFIGS_DIR, pdf_page_count
from mapping import DEFAULT_MAPPINGS, MappingConfig, all_slots, load_config, save_config
from pdf_renderer import xml_to_pdf

CONFIG_FILES = sorted(glob.glob(os.path.join(CONFIGS_DIR, "*.json")))
CONFIG_NAMES = [os.path.basename(p)[:-5] for p in CONFIG_FILES]


@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_shipped_config_maps_every_slot(name):
    """A slot left out of a config renders as a blank column on the PDF."""
    with open(os.path.join(CONFIGS_DIR, f"{name}.json"), encoding="utf-8") as f:
        mappings = json.load(f)["mappings"]

    missing = [s for s in all_slots() if not mappings.get(s)]
    assert not missing, f"{name}.json does not map {missing}"


@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_shipped_config_loads_and_declares_xpaths(name):
    cfg = load_config(os.path.join(CONFIGS_DIR, f"{name}.json"))
    assert cfg.header_xpath, f"{name} has no header_xpath"
    assert cfg.item_xpath, f"{name} has no item_xpath"
    assert set(cfg.mappings) <= set(all_slots()), f"{name} maps unknown slots"


def test_british_config_fills_the_unit_column(make_invoice, fonts_dir, tmp_path,
                                              british_config):
    """The default config used to omit item_unit, leaving the Unit column empty."""
    from conftest import pdf_words

    xml = make_invoice(items=3)
    out = str(tmp_path / "unit.pdf")
    xml_to_pdf(xml, out, mapping_config=british_config, font_dir=fonts_dir)

    text = " ".join(w.text for w in pdf_words(out))
    assert "box" in text, "the Unit column is blank"


def test_config_can_switch_barcodes_off(make_invoice, fonts_dir, tmp_path,
                                        british_config):
    """include_barcodes=false in a config must be honoured, not overwritten."""
    xml = make_invoice(items=5)

    with_codes = str(tmp_path / "with.pdf")
    xml_to_pdf(xml, with_codes, mapping_config=copy.deepcopy(british_config),
               font_dir=fonts_dir)

    british_config.include_barcodes = False
    without = str(tmp_path / "without.pdf")
    xml_to_pdf(xml, without, mapping_config=british_config, font_dir=fonts_dir)

    assert pdf_page_count(without) < pdf_page_count(with_codes)


def test_explicit_no_barcodes_argument_still_wins(make_invoice, fonts_dir, tmp_path,
                                                  british_config):
    xml = make_invoice(items=5)
    out = str(tmp_path / "cli.pdf")
    xml_to_pdf(xml, out, include_barcodes=False,
               mapping_config=british_config, font_dir=fonts_dir)

    from conftest import pdf_words
    text = " ".join(w.text for w in pdf_words(out))
    assert "GS1-128:" not in text


def test_xml_to_pdf_does_not_mutate_the_config_it_is_given(make_invoice, fonts_dir,
                                                           tmp_path, british_config):
    """Batch conversions share one config object; rendering must not alter it."""
    before = copy.deepcopy(british_config)
    xml = make_invoice(items=2)
    xml_to_pdf(xml, str(tmp_path / "a.pdf"), mapping_config=british_config,
               font_dir=fonts_dir)

    assert british_config.mappings == before.mappings
    assert british_config.include_barcodes == before.include_barcodes
    assert british_config.font_dir == before.font_dir


def test_default_xpaths_agree_across_the_codebase(tmp_path):
    """MappingConfig() and load_config() must not disagree about the defaults."""
    written = str(tmp_path / "roundtrip.json")
    save_config(written, MappingConfig())
    reloaded = load_config(written)

    fresh = MappingConfig()
    assert reloaded.header_xpath == fresh.header_xpath
    assert reloaded.item_xpath == fresh.item_xpath
    assert reloaded.mappings == fresh.mappings


def test_load_config_of_a_file_without_xpaths_uses_the_dataclass_defaults(tmp_path):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"name": "bare", "mappings": DEFAULT_MAPPINGS}),
                    encoding="utf-8")

    cfg = load_config(str(path))
    assert cfg.header_xpath == MappingConfig().header_xpath
    assert cfg.item_xpath == MappingConfig().item_xpath


# ── resolving a profile by name ───────────────────────────────

def test_config_can_be_selected_by_bare_name():
    """`--config polish` must work, not just a full path — an .exe user has no
    configs/ directory next to the executable."""
    from mapping import resolve_config_path

    path = resolve_config_path("polish")
    assert path is not None and path.endswith("polish.json")


def test_config_name_with_the_json_suffix_also_resolves():
    from mapping import resolve_config_path

    assert resolve_config_path("polish.json").endswith("polish.json")


def test_an_explicit_path_is_returned_unchanged(tmp_path):
    from mapping import resolve_config_path

    custom = tmp_path / "mine.json"
    custom.write_text("{}", encoding="utf-8")
    assert resolve_config_path(str(custom)) == str(custom)


def test_an_unknown_name_resolves_to_nothing():
    from mapping import resolve_config_path

    assert resolve_config_path("klingon") is None
