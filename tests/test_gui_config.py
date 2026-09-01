"""The GUI path: loading an XML must produce a config that actually renders.

The reported "everything mapped, PDF empty" bug lived here — between what the
GUI displays and what _build_config() hands to the renderer — which no test
covered. These run headlessly and skip where there is no display or no
CustomTkinter.
"""

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.gui

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_in_gui(body: str, *args: str) -> str:
    """Execute a snippet against a live App instance under a virtual display."""
    for module in ("tkinter", "customtkinter"):
        pytest.importorskip(module)
    if shutil.which("xvfb-run") is None and not os.environ.get("DISPLAY"):
        pytest.skip("no display and xvfb-run not installed")

    script = textwrap.dedent(f"""
        import sys, os
        sys.path.insert(0, {PROJECT_ROOT!r})
        os.chdir({PROJECT_ROOT!r})
        from tkinter import filedialog
        from gui import App, NONE_TAG
        XML = sys.argv[1]
        filedialog.askopenfilename = lambda **kw: XML
        app = App()
        app.update()
        try:
{textwrap.indent(textwrap.dedent(body), " " * 12)}
        finally:
            app.destroy()
    """)

    command = [sys.executable, "-c", script, *args]
    if not os.environ.get("DISPLAY"):
        command = ["xvfb-run", "-a", *command]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"GUI run failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


@pytest.fixture
def decoy_header_xml(tmp_path):
    """An invoice with a second, earlier <Header> — the reported shape."""
    from test_discovery_paths import SHAPES

    path = tmp_path / "decoy.xml"
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>'
                    + SHAPES["duplicate_header"], encoding="utf-8")
    return str(path)


def test_opening_an_xml_maps_every_slot(make_invoice):
    out = _run_in_gui("""
        app._open_xml()
        app.update()
        print("STATUS:", app.status_label.cget("text"))
        print("NONE:", sum(1 for v in app.slot_vars.values() if v.get() == NONE_TAG))
    """, make_invoice(items=3))

    assert "35/35" in out, out
    assert "NONE: 0" in out, out


def test_built_config_carries_the_discovered_xpaths_and_mappings(make_invoice):
    out = _run_in_gui("""
        app._open_xml()
        cfg = app._build_config()
        print("SLOTS:", len(cfg.mappings))
        print("HEADER:", cfg.header_xpath)
        print("ITEM:", cfg.item_xpath)
    """, make_invoice(items=3))

    assert "SLOTS: 35" in out, out
    assert "HEADER: ./Invoice/Header" in out, out
    assert "ITEM: ./Invoice/Items/Item" in out, out


def test_the_config_the_gui_builds_renders_a_populated_pdf(make_invoice, tmp_path,
                                                           fonts_dir):
    """End to end through the GUI's own config, not a hand-built one."""
    pdf = tmp_path / "gui.pdf"
    out = _run_in_gui(f"""
        app._open_xml()
        cfg = app._build_config()
        from pdf_renderer import xml_to_pdf
        xml_to_pdf(XML, {str(pdf)!r}, mapping_config=cfg, font_dir={fonts_dir!r})
        print("RENDERED")
    """, make_invoice(items=3))
    assert "RENDERED" in out

    from conftest import pdf_words
    text = " ".join(w.text for w in pdf_words(str(pdf)))
    for expected in ("Test", "Supplier", "INV-TEST", "PC-0001"):
        assert expected in text, f"{expected!r} missing — the boxes are empty again"


def test_a_decoy_header_still_renders_through_the_gui(decoy_header_xml, tmp_path,
                                                      fonts_dir):
    """Regression for the reported bug, driven the way the user hit it."""
    pdf = tmp_path / "decoy.pdf"
    out = _run_in_gui(f"""
        app._open_xml()
        app.update()
        print("STATUS:", app.status_label.cget("text"))
        cfg = app._build_config()
        from pdf_renderer import xml_to_pdf
        xml_to_pdf(XML, {str(pdf)!r}, mapping_config=cfg, font_dir={fonts_dir!r})
        print("RENDERED")
    """, decoy_header_xml)

    assert "35/35" in out, out
    assert "RENDERED" in out

    from conftest import pdf_words
    text = " ".join(w.text for w in pdf_words(str(pdf)))
    assert "Supplier" in text, "header fields are empty despite a full mapping"
    assert "INV-9" in text
    assert "metadata" not in text, "read the decoy <Meta><Header> instead"


def test_the_credit_footer_is_present_in_the_window(make_invoice):
    out = _run_in_gui("""
        labels = []
        def walk(w):
            for c in w.winfo_children():
                try:
                    text = c.cget("text")
                except Exception:
                    text = ""
                if text:
                    labels.append(text)
                walk(c)
        walk(app)
        print("HAS_EMAIL:", any("dev@attv.uk" == t for t in labels))
        print("HAS_CREDIT:", any("Lewandowski" in t for t in labels))
        print("HAS_GITHUB:", any(t == "GitHub" for t in labels))
    """, make_invoice(items=2))

    assert "HAS_EMAIL: True" in out, out
    assert "HAS_CREDIT: True" in out, out
    assert "HAS_GITHUB: True" in out, out
