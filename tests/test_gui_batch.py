"""The Batch tab, driven through a real window.

The batch logic itself is tested in test_batch.py; what these guard is the
seam — that the names the tab shows are the names it writes, and that the
pattern the user builds reaches the config the renderer and the profile get.
"""

import os

import pytest

from test_gui_config import _run_in_gui

pytestmark = pytest.mark.gui

# Runs the real Tk main loop until *cond* holds. Pumping with app.update() is
# not enough: a worker thread's self.after() raises "main thread is not in main
# loop" unless mainloop() is actually running — which it always is for a user.
PUMP = """
import time
def pump(cond, timeout):
    deadline = time.time() + timeout
    state = {"ok": False}
    def check():
        if cond():
            state["ok"] = True
            app.quit()
        elif time.time() > deadline:
            app.quit()
        else:
            app.after(50, check)
    app.after(50, check)
    app.mainloop()
    if not state["ok"]:
        raise SystemExit("timed out; status=" + app.status_label.cget("text"))
"""


@pytest.fixture
def two_invoices(tmp_path):
    from conftest import build_invoice_xml
    root = tmp_path / "in"
    for sub, num in (("a", "INV-1"), ("b", "INV-2")):
        (root / sub).mkdir(parents=True)
        build_invoice_xml(str(root / sub / "invoice.xml"),
                          header_overrides={"InvoiceNumber": num,
                                            "IssueDate": "2026-03-10"})
    return str(root)


def _preview_snippet(folder: str, out: str, fonts_dir: str) -> str:
    return PUMP + f"""
filedialog.askdirectory = lambda **kw: {folder!r}
app.font_dir_var.set({fonts_dir!r})
app._choose_batch_folder()
print("COUNT:", app.batch_count_label.cget("text"))
app.batch_output_var.set({out!r})
app.pattern_var.set("{{period}}_{{invoice_number}}")
app._batch_preview()
pump(lambda: app.preview_pdf_path is not None
     and app.status_label.cget("text") == "Preview ready", 30)
print("TAB:", app.tabview.get())
print("LIST:", app.batch_list.get("1.0", "end"))
"""


def test_batch_folder_preview_lists_planned_names(two_invoices, tmp_path, fonts_dir):
    out = _run_in_gui(_preview_snippet(two_invoices, str(tmp_path / "out"), fonts_dir),
                      two_invoices)
    print(out)
    assert "COUNT: 2 XML files" in out, out
    assert "2026-03_INV-1.pdf" in out, out
    assert "2026-03_INV-2.pdf" in out, out
    assert "TAB: Preview" in out, out


def test_batch_generate_all_writes_named_pdfs(two_invoices, tmp_path, fonts_dir):
    target = tmp_path / "out"
    out = _run_in_gui(_preview_snippet(two_invoices, str(target), fonts_dir) + """
app._batch_run()
pump(lambda: app.status_label.cget("text").startswith("Batch done"), 60)
print("STATUS:", app.status_label.cget("text"))
print("PROGRESS:", app.batch_progress_label.cget("text"))
""", two_invoices)
    assert sorted(os.listdir(target)) == ["2026-03_INV-1.pdf", "2026-03_INV-2.pdf"], out
    assert "STATUS: Batch done: 2 succeeded, 0 failed" in out, out
    assert "PROGRESS: 2 of 2: invoice.xml" in out, out


def test_generate_all_is_disabled_until_a_plan_exists(two_invoices):
    out = _run_in_gui("""
print("STATE:", app.btn_batch_run.cget("state"))
""", two_invoices)
    assert "STATE: disabled" in out, out


def test_invalid_pattern_is_reported_under_the_entry(two_invoices):
    out = _run_in_gui(f"""
filedialog.askdirectory = lambda **kw: {two_invoices!r}
app._choose_batch_folder()
app.pattern_var.set("{{nope}}")
app._batch_preview()
app.update()
print("ERR:", app.pattern_error_label.cget("text"))
print("STATE:", app.btn_batch_run.cget("state"))
""", two_invoices)
    assert "ERR: unknown field {nope}" in out, out
    assert "STATE: disabled" in out, out


def test_field_button_inserts_token(two_invoices):
    out = _run_in_gui("""
app.pattern_var.set("")
app._insert_pattern_field("supplier_name")
print("PATTERN:", app.pattern_var.get())
""", two_invoices)
    assert "PATTERN: {supplier_name}" in out, out


def test_pattern_saved_with_profile(two_invoices):
    out = _run_in_gui("""
app.pattern_var.set("{invoice_number}")
print("CFG:", app._build_config().filename_pattern)
""", two_invoices)
    assert "CFG: {invoice_number}" in out, out


def test_choose_files_counts_only_xml(two_invoices, tmp_path):
    first = os.path.join(two_invoices, "a", "invoice.xml")
    second = os.path.join(two_invoices, "b", "invoice.xml")
    out = _run_in_gui(f"""
filedialog.askopenfilenames = lambda **kw: ({first!r}, {second!r})
app._choose_batch_files()
print("COUNT:", app.batch_count_label.cget("text"))
print("OUTDIR:", app.batch_output_var.get())
print("XML:", app.xml_path)
""", first)
    assert "COUNT: 2 XML files" in out, out
    assert f"OUTDIR: {os.path.dirname(first)}" in out, out
    assert f"XML: {first}" in out, out


def test_stop_ends_the_batch_early(two_invoices, tmp_path, fonts_dir):
    out = _run_in_gui(_preview_snippet(two_invoices, str(tmp_path / "out"), fonts_dir) + """
app._batch_run()
app._batch_stop()
pump(lambda: app.status_label.cget("text").startswith("Batch done"), 60)
print("STATUS:", app.status_label.cget("text"))
print("LIST:", app.batch_list.get("1.0", "end"))
""", two_invoices)
    assert "(stopped)" in out, out
    assert "not generated (stopped)" in out, out


def test_generate_pdf_suggests_the_pattern_name(two_invoices):
    first = os.path.join(two_invoices, "a", "invoice.xml")
    out = _run_in_gui("""
seen = {}
def fake_save(**kw):
    seen.update(kw)
    return ""
filedialog.asksaveasfilename = fake_save
app._open_xml()
app.pattern_var.set("{period}_{invoice_number}")
app._generate_pdf()
print("INITIAL:", seen.get("initialfile"))
app.pattern_var.set("{bad")
app._generate_pdf()
print("FALLBACK:", seen.get("initialfile"))
""", first)
    assert "INITIAL: 2026-03_INV-1.pdf" in out, out
    assert "FALLBACK: invoice.pdf" in out, out


def test_warnings_survive_the_run(tmp_path, fonts_dir):
    from conftest import build_invoice_xml
    folder = tmp_path / "in"
    folder.mkdir()
    build_invoice_xml(str(folder / "x.xml"), header_overrides={"BuyerName": ""})
    target = tmp_path / "out"
    out = _run_in_gui(PUMP + f"""
filedialog.askdirectory = lambda **kw: {str(folder)!r}
app.font_dir_var.set({fonts_dir!r})
app._choose_batch_folder()
app.batch_output_var.set({str(target)!r})
app.pattern_var.set("{{buyer_name}}")
app._batch_run()
pump(lambda: app.status_label.cget("text").startswith("Batch done"), 60)
print("LIST:", app.batch_list.get("1.0", "end"))
""", str(folder / "x.xml"))
    assert "no-buyer_name.pdf" in out, out
    assert "⚠ missing buyer_name" in out, out


def test_inputs_are_locked_while_a_batch_runs(two_invoices, tmp_path, fonts_dir):
    """Choosing new inputs mid-run used to relabel the old run's results."""
    from conftest import build_invoice_xml
    other = tmp_path / "other"
    other.mkdir()
    for n in range(3):
        build_invoice_xml(str(other / f"o{n}.xml"))
    out = _run_in_gui(_preview_snippet(two_invoices, str(tmp_path / "out"), fonts_dir) + f"""
app._batch_run()
print("LOCKED:", [w.cget("state") for w in app._batch_input_widgets].count("normal"))
filedialog.askdirectory = lambda **kw: {str(other)!r}
filedialog.askopenfilenames = lambda **kw: ({str(other / "o0.xml")!r},)
app._choose_batch_folder()
app._choose_batch_files()
app._set_batch_inputs([{str(other)!r}], default_output={str(other)!r})
app._insert_pattern_field("supplier_name")
app._batch_preview()
print("MID_COUNT:", app.batch_count_label.cget("text"))
print("MID_INPUTS:", len(app.batch_inputs))
print("MID_PATTERN:", app.pattern_var.get())
print("MID_STATUS:", app.status_label.cget("text"))
pump(lambda: app.status_label.cget("text").startswith("Batch done"), 60)
print("STATUS:", app.status_label.cget("text"))
print("COUNT:", app.batch_count_label.cget("text"))
print("UNLOCKED:", all(w.cget("state") == "normal" for w in app._batch_input_widgets))
print("LIST:", app.batch_list.get("1.0", "end"))
""", two_invoices)
    assert "LOCKED: 0" in out, out
    assert "MID_COUNT: 2 XML files" in out, out
    assert "MID_INPUTS: 2" in out, out
    assert "MID_PATTERN: {period}_{invoice_number}" in out, out
    assert "MID_STATUS: Batch running..." in out, out
    assert "STATUS: Batch done: 2 succeeded, 0 failed" in out, out
    assert "COUNT: 2 XML files" in out, out
    assert "UNLOCKED: True" in out, out
    assert "o0.xml" not in out.split("LIST:")[1], out


def test_batch_keeps_the_selected_profiles_mapping(two_invoices, tmp_path):
    # Choosing a folder loads its first XML, which auto-matches every slot.
    # That used to overwrite the selected profile's mapping while the Config
    # dropdown still named the profile, so the batch was named and rendered
    # with a mapping the user never chose, and Save Config could persist it.
    import dataclasses
    from conftest import build_invoice_xml
    from mapping import load_config, save_config
    profile = tmp_path / "custom.json"
    base = load_config(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "configs", "british_english.json"))
    cfg = dataclasses.replace(base, name="custom",
                              mappings={**base.mappings, "invoice_number": "SupplierName"},
                              filename_pattern="{invoice_number}")
    save_config(str(profile), cfg)

    other = tmp_path / "other.xml"
    build_invoice_xml(str(other))

    out = _run_in_gui(f"""
app._find_config = lambda name: {str(profile)!r}
app.config_var.set("custom")
app._on_config_selected("custom")
filedialog.askdirectory = lambda **kw: {two_invoices!r}
app._choose_batch_folder()
print("AFTER_CHOOSE:", app.slot_vars["invoice_number"].get())
app.batch_output_var.set({str(tmp_path / "out")!r})
app._make_batch_plan()
print("LIST1:", app.batch_list.get("1.0", "end").replace(chr(10), " | "))
# Opening another XML from the top bar makes the next plan reload the batch's
# first file: the re-plan path must keep the profile too.
app._load_xml({str(other)!r})
app._make_batch_plan()
print("AFTER_REPLAN:", app.slot_vars["invoice_number"].get())
print("LIST2:", app.batch_list.get("1.0", "end").replace(chr(10), " | "))
""", two_invoices)
    assert "AFTER_CHOOSE: SupplierName" in out, out
    assert "AFTER_REPLAN: SupplierName" in out, out
    for tag in ("LIST1:", "LIST2:"):
        line = next(l for l in out.splitlines() if l.startswith(tag))
        assert "Test Supplier Ltd.pdf" in line and "Test Supplier Ltd_2.pdf" in line, out
        assert "INV-1" not in line.split("←")[0], out


def test_closing_mid_batch_waits_for_the_current_file(two_invoices, tmp_path, fonts_dir):
    # The worker is a daemon thread: destroying the window at once killed it,
    # possibly mid-save, leaving a truncated PDF under its final name.
    out_dir = tmp_path / "out"
    out = _run_in_gui(_preview_snippet(two_invoices, str(out_dir), fonts_dir) + f"""
closed = []
real_destroy = app.destroy
def fake_destroy():
    files = sorted(os.listdir({str(out_dir)!r})) if os.path.isdir({str(out_dir)!r}) else []
    tails = [open(os.path.join({str(out_dir)!r}, f), "rb").read()[-1024:] for f in files]
    closed.append((files, all(b"%%EOF" in t for t in tails), len(finished)))
app.destroy = fake_destroy
# Hold the worker inside the first file so the close lands mid-file every
# time; a real render is fast enough to finish between two polls.
import batch, threading, time
started, finished = threading.Event(), []
real_render = batch.xml_to_pdf
def slow_render(*a, **kw):
    started.set()
    time.sleep(0.5)
    result = real_render(*a, **kw)
    finished.append(a[1])
    return result
batch.xml_to_pdf = slow_render
app._batch_run()
pump(started.is_set, 30)
app._on_closing()
print("IMMEDIATE_CLOSE:", bool(closed))
print("STATUS:", app.status_label.cget("text"))
app._on_closing()            # a second click must not close early either
print("SECOND_CLOSE:", bool(closed))
pump(lambda: bool(closed), 60)
app.destroy = real_destroy
print("FILES:", closed[0][0])
print("COMPLETE:", closed[0][1])
print("RENDERED_BEFORE_CLOSE:", closed[0][2])
""", two_invoices)
    assert "IMMEDIATE_CLOSE: False" in out, out
    assert "SECOND_CLOSE: False" in out, out
    assert "STATUS: Stopping after the current file" in out, out
    assert "COMPLETE: True" in out, out
    # The file being written when the window was closed is finished, not cut
    # off, and the stop keeps the second from starting.
    assert "RENDERED_BEFORE_CLOSE: 1" in out, out
    assert "FILES: ['2026-03_INV-1.pdf']" in out, out
