# Batch Conversion with Pattern-Based PDF Names — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a folder or a set of invoice XMLs in one go, naming each PDF from a user pattern (`{period}_{invoice_number}_{supplier_name}`), with a preview of the first file plus all planned names, then a cancellable "X of Y" run, in both the GUI and the CLI.

**Architecture:** Two new flat modules hold everything the GUI and the CLI share. `naming.py` is pure string logic: pattern validation, `period`, sanitising, collision-free allocation. `batch.py` collects inputs, plans names and runs the queue with progress and stop callbacks. `MappingConfig` gains `filename_pattern`. The CLI and a new GUI "Batch" tab are thin callers.

**Tech Stack:** Python 3.12, reportlab, CustomTkinter, pytest; poppler/Xvfb for artefact tests.

**Spec:** `docs/superpowers/specs/2026-10-22-batch-naming-design.md`

## Global Constraints

- Flat modules at the repo root; import as `from naming import ...`. No package directory.
- Everything a user sees is English: CLI output, GUI labels, placeholders (`no-<slot_id>`), warnings. `tests/test_cli.py` fails on Polish output.
- Never mutate a caller's `MappingConfig` (CLAUDE.md invariant 8). Use `dataclasses.replace`.
- Do not edit `configs/*.json`, `example_invoice.xml`, `screenshots/*.png` or released CHANGELOG sections.
- Forbidden characters: `/ \ : * ? " < > |` and U+0000–U+001F, U+007F. They are **dropped**, not replaced.
- Windows reserved stems: `CON PRN AUX NUL COM1–COM9 LPT1–LPT9` (case-insensitive) get `_` appended.
- `MAX_STEM_LEN = 200` characters before any `_N` suffix and `.pdf`.
- Collision suffixes are `_2`, `_3`, …, compared case-insensitively, against the batch and the files already in the output folder. Never overwrite.
- `period` = `YYYY-MM` from `issue_date`; accepts `YYYY-MM-DD` (optionally followed by `T…` or ` …`), `DD.MM.YYYY`, `DD/MM/YYYY`. Unparseable counts as missing.
- Missing or empty-after-sanitising field → placeholder `no-<field>` plus warning text `missing <field>`.
- A pattern applies only in batch-to-folder mode (GUI Batch tab, or CLI `--output-dir`). Without `--output-dir` the CLI behaves exactly as today.
- Release: v0.7.0, with a CHANGELOG `[0.7.0]` section and a release body that states there is no Intel (x86_64) macOS binary and links the README "Intel Macs: run from source" section.

## Review Focus

1. **Non-ASCII values** (`Łódź Sp. z o.o.`, `Müller GmbH`) must survive sanitising unchanged. Only the forbidden set is dropped. → Task 1 `test_sanitize_keeps_non_ascii`.
2. **Literal text in the pattern containing forbidden characters** (`{period}/{invoice_number}`) must give a valid name and must not create a subfolder. → Task 1 `test_pattern_literal_slash_is_dropped`.
3. **A value made only of forbidden characters** (`///`) must become the placeholder, not an empty name or `.pdf`. → Task 1 `test_value_empty_after_sanitising_is_missing`.
4. **An existing file differing only in case** (`2026-03_INV-TEST.PDF` already on disk) must not be overwritten. → Task 2 `test_allocator_respects_existing_files_case_insensitively`.
5. **A folder containing no XML files**, or the same file given twice, must give a clear message, or one entry, not a crash or a duplicate PDF. → Task 3 `test_collect_deduplicates_and_sorts`, Task 4 `test_cli_empty_folder_is_an_error`.

---

### Task 1: `naming.py` — pattern, period, sanitising

**Files:**
- Create: `naming.py`
- Test: `tests/test_naming.py`

**Interfaces:**
- Consumes: `mapping.SLOT_CATEGORIES`, `mapping.HEADER_SLOTS`.
- Produces:
  - `PERIOD_FIELD = "period"`
  - `NAME_FIELDS: list[str]`: header slot ids in `SLOT_CATEGORIES` order, then `"period"`.
  - `MAX_STEM_LEN = 200`
  - `class PatternError(ValueError)`
  - `validate_pattern(pattern: str) -> list[str]`: the field names used, in order. Raises `PatternError` for an unknown field, or for any `{` or `}` that is not part of a `{name}` token. The message names the offending field or character.
  - `parse_period(date_text: str) -> str`: `"YYYY-MM"`, or `""` if unparseable.
  - `sanitize(text: str) -> str`
  - `build_stem(pattern: str, values: dict[str, str]) -> tuple[str, list[str]]`: `values` is keyed by slot id. `period` is derived from `values.get("issue_date", "")`. Returns `(stem, warnings)`, with warnings like `"missing supplier_name"`. The stem is sanitised as a whole, reserved names are handled, and the result is truncated to `MAX_STEM_LEN` (trailing whitespace and dots stripped again after truncation).

- [ ] **Step 1: Write the failing tests** in `tests/test_naming.py`:

```python
import pytest
from naming import (NAME_FIELDS, PatternError, build_stem, parse_period,
                    sanitize, validate_pattern, MAX_STEM_LEN)

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
    assert len(stem) == MAX_STEM_LEN
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_naming.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'naming'`.

- [ ] **Step 3: Implement `naming.py`** with the interfaces above. Tokenise with `re.finditer(r"\{([a-z0-9_]+)\}", pattern)`. After removing the tokens, any leftover `{` or `}` is a `PatternError`. Do not use `str.format`. Each value is sanitised on its own first (so an all-forbidden value becomes missing), and then the joined stem is sanitised again (so literal pattern text is cleaned too). Module docstring and `# ── Name ──` section headers match the existing modules.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_naming.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add naming.py tests/test_naming.py
git commit -m "feat(naming): pattern-based PDF names with safe-character rules"
```

---

### Task 2: `naming.py` — collision-free allocation

**Files:**
- Modify: `naming.py`
- Test: `tests/test_naming.py`

**Interfaces:**
- Produces: `class NameAllocator`
  - `__init__(self, output_dir: str)`: snapshots `os.listdir(output_dir)` if the folder exists, lower-cased.
  - `allocate(self, stem: str) -> str`: returns a file name (`"stem.pdf"`, `"stem_2.pdf"`, …) that is free case-insensitively, both in the snapshot and among names already allocated, and that does not exist on disk right now (`os.path.exists`). Reserves it before returning.

- [ ] **Step 1: Write the failing tests**

```python
from naming import NameAllocator

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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_naming.py -q -k allocator`
Expected: `ImportError: cannot import name 'NameAllocator'`.

- [ ] **Step 3: Implement `NameAllocator`** in `naming.py`.

- [ ] **Step 4: Run and confirm they pass**

Run: `python -m pytest tests/test_naming.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**: `feat(naming): never overwrite — suffix _2, _3 on collisions`

---

### Task 3: `filename_pattern` on profiles + `batch.py`

**Files:**
- Modify: `mapping.py` (`MappingConfig`, `load_config`)
- Create: `batch.py`
- Test: `tests/test_batch.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 (`build_stem`, `validate_pattern`, `sanitize`, `NameAllocator`, `PatternError`); `xml_parser.InvoiceData`; `pdf_renderer.xml_to_pdf`; `mapping.HEADER_SLOTS`.
- Produces:
  - `MappingConfig.filename_pattern: str = ""`. `load_config` reads `data.get("filename_pattern", "")`. `save_config` needs no change (it uses `asdict`).
  - `collect_xml_files(paths: list[str]) -> list[str]`: directories are walked recursively for files ending in `.xml` (case-insensitive), files are kept as given, everything is de-duplicated by `os.path.realpath`, and the result is sorted by path.
  - `header_values(xml_path: str, config: MappingConfig) -> dict[str, str]`: `{slot: inv.h(config.get(slot))}` for every `HEADER_SLOTS` slot with a mapping, read with the config's `header_xpath`/`item_xpath`, exactly as the renderer does.
  - `@dataclass PlannedFile`: `source: str`, `filename: str`, `stem: str`, `warnings: list[str]`, `error: str = ""`.
  - `@dataclass BatchPlan`: `output_dir: str`, `files: list[PlannedFile]`, `allocator: NameAllocator`.
  - `plan_batch(xml_paths: list[str], config: MappingConfig, output_dir: str, pattern: str | None = None) -> BatchPlan`: `pattern=None` means `config.filename_pattern`. The pattern is validated first and a `PatternError` propagates. An empty pattern gives `stem = sanitize(XML stem)`. A file whose header cannot be read gets `error=str(exc)`, a name from its XML stem, and stays in the plan, so it fails visibly at run time.
  - `@dataclass BatchResult`: `succeeded: list[tuple[str, str]]` (source, output path), `failed: list[tuple[str, str]]` (source, reason), `stopped: bool = False`.
  - `run_batch(plan: BatchPlan, config: MappingConfig, *, include_barcodes: bool | None = None, font_dir: str | None = None, on_progress: Callable[[int, int, PlannedFile], None] | None = None, should_stop: Callable[[], bool] | None = None) -> BatchResult`. It creates `output_dir`. Before file *i* (1-based) it checks `should_stop()`, then calls `on_progress(i, total, item)`. If the target exists by then, it re-allocates via `plan.allocator.allocate(item.stem)`. Each file's exception is caught into `failed`. Planned items with `error` fail with that reason, without rendering.

- [ ] **Step 1: Write the failing tests.** In `tests/test_config.py`:

```python
def test_filename_pattern_round_trips(tmp_path):
    from mapping import MappingConfig, save_config, load_config
    p = str(tmp_path / "c.json")
    save_config(p, MappingConfig(filename_pattern="{period}_{invoice_number}"))
    assert load_config(p).filename_pattern == "{period}_{invoice_number}"

def test_shipped_profiles_have_no_pattern():
    from mapping import load_config
    from conftest import CONFIGS_DIR
    import os
    for f in os.listdir(CONFIGS_DIR):
        assert load_config(os.path.join(CONFIGS_DIR, f)).filename_pattern == ""
```

In `tests/test_batch.py`, build three invoices named `invoice.xml` in `a/`, `b/` and `c/` with `build_invoice_xml` and `header_overrides` (`InvoiceNumber` `INV-1`, `INV-2`, `INV-1`; `IssueDate` `2026-03-10`), using `british_config` and `fonts_dir`:

```python
def test_collect_deduplicates_and_sorts(three_invoices, tmp_path):
    root, files = three_invoices
    got = collect_xml_files([str(root), files[0]])
    assert got == sorted(files)

def test_plan_names_and_collisions(three_invoices, british_config, tmp_path):
    root, files = three_invoices
    plan = plan_batch(files, british_config, str(tmp_path / "out"),
                      pattern="{period}_{invoice_number}")
    assert [f.filename for f in plan.files] == \
        ["2026-03_INV-1.pdf", "2026-03_INV-2.pdf", "2026-03_INV-1_2.pdf"]

def test_plan_empty_pattern_uses_xml_stem(three_invoices, british_config, tmp_path):
    plan = plan_batch(three_invoices[1], british_config, str(tmp_path / "out"), pattern="")
    assert [f.filename for f in plan.files] == ["invoice.pdf", "invoice_2.pdf", "invoice_3.pdf"]

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
    bad = tmp_path / "bad.xml"; bad.write_text("<not-closed>", encoding="utf-8")
    files = three_invoices[1] + [str(bad)]
    res = run_batch(plan_batch(files, british_config, str(tmp_path / "o"), pattern="{invoice_number}"),
                    british_config, font_dir=fonts_dir)
    assert len(res.succeeded) == 3 and [s for s, _ in res.failed] == [str(bad)]

def test_stop_finishes_current_and_skips_rest(three_invoices, british_config, fonts_dir, tmp_path):
    calls = []
    res = run_batch(plan_batch(three_invoices[1], british_config, str(tmp_path / "o")),
                    british_config, font_dir=fonts_dir,
                    on_progress=lambda i, n, f: calls.append(i),
                    should_stop=lambda: len(calls) >= 1)
    assert res.stopped and len(res.succeeded) == 1 and calls == [1]

def test_never_overwrites_file_created_after_planning(three_invoices, british_config, fonts_dir, tmp_path):
    out = tmp_path / "o"; out.mkdir()
    plan = plan_batch(three_invoices[1][:1], british_config, str(out), pattern="{invoice_number}")
    (out / "INV-1.pdf").write_bytes(b"keep me")
    run_batch(plan, british_config, font_dir=fonts_dir)
    assert (out / "INV-1.pdf").read_bytes() == b"keep me" and (out / "INV-1_2.pdf").exists()
```

`three_invoices` is a fixture in `tests/test_batch.py` that returns `(root, sorted_paths)`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_batch.py tests/test_config.py -q`
Expected: `ModuleNotFoundError: No module named 'batch'` and an `AttributeError` on `filename_pattern`.

- [ ] **Step 3: Add `filename_pattern` to `MappingConfig`/`load_config`, and implement `batch.py`.**

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (GUI tests may skip).

- [ ] **Step 5: Commit**: `feat(batch): plan and run named batches; filename_pattern on profiles`

---

### Task 4: CLI — `--output-dir`, `--name-pattern`, `--dry-run`, folders

**Files:**
- Modify: `xml_invoice_to_pdf.py` (argument parsing, usage examples in the module docstring and epilog, main loop)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `collect_xml_files`, `plan_batch`, `run_batch`, `PatternError` (Task 3, Task 1).
- Behaviour:
  - Positional arguments may be directories; they are expanded with `collect_xml_files` in both modes.
  - **Without `--output-dir`:** today's loop is unchanged (PDF next to its XML, `-o` for a single file). `--name-pattern` or `--dry-run` without `--output-dir` → `parser.error("--name-pattern and --dry-run need --output-dir.")`.
  - **With `--output-dir`:** `-o` → `parser.error("-o/--output cannot be combined with --output-dir.")`. The pattern is `--name-pattern` if given, else the profile's. A `PatternError` → `parser.error(f"Invalid --name-pattern: {e}")`. No XML found → stderr `Error: no XML files found.` and exit 1.
  - Dry run prints one line per file, `{source} -> {filename}`, then indented `  warning: {w}` / `  error: {e}` lines, then `{N} files planned, {W} with warnings`, and exits 0 without creating `--output-dir`.
  - Run lines: `[{i}/{n}] OK {source} -> {path}` to stdout, `[{i}/{n}] FAIL {source} — {reason}` to stderr. Then the existing `Done: N succeeded, N failed` line, with exit 1 if any failed.
  - `--name-pattern` must not be written into the loaded config object (use `replace`).

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py`, using `run_cli`, `build_invoice_xml` into `tmp_path/"in"/"a"/"invoice.xml"` and `.../"b"/"invoice.xml"` (`INV-1`, `INV-2`), and `--font-dir fonts_dir`:
  - `test_cli_batch_to_folder_with_pattern`: `run_cli(str(in_dir), "--output-dir", out, "--name-pattern", "{period}_{invoice_number}", "--config", "british_english", "--font-dir", fonts_dir)` → `sorted(os.listdir(out)) == ["2026-03_INV-1.pdf", "2026-03_INV-2.pdf"]`, and `"[2/2] OK"` in stdout.
  - `test_cli_dry_run_writes_nothing`: the same with `--dry-run` → `not os.path.exists(out)`, and stdout contains `"-> 2026-03_INV-1.pdf"` and `"2 files planned"`.
  - `test_cli_dry_run_shows_missing_field_warning`: pattern `{buyer_name}` with `header_overrides={"BuyerName": ""}` → stdout contains `"warning: missing buyer_name"`.
  - `test_cli_pattern_from_profile`: a copy of `british_english.json` with `"filename_pattern": "{invoice_number}"` gives `INV-1.pdf`/`INV-2.pdf`.
  - `test_cli_without_output_dir_ignores_profile_pattern`: the same profile, no `--output-dir`, single file → `invoice.pdf` next to the XML.
  - `test_cli_pattern_needs_output_dir`, `test_cli_o_conflicts_with_output_dir`, `test_cli_unknown_field_is_a_usage_error` (`{nope}` → returncode 2, `"nope"` in stderr).
  - `test_cli_empty_folder_is_an_error`: an empty dir with `--output-dir` → returncode 1, `"no XML files found"` in stderr.

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_cli.py -q`
Expected: the new tests fail (unrecognised arguments); the old ones pass.

- [ ] **Step 3: Implement** the behaviour above in `xml_invoice_to_pdf.py`. Add a batch example to `--help`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass, including the no-Polish-output tests.

- [ ] **Step 5: Commit**: `feat(cli): batch to a folder with --name-pattern, --output-dir, --dry-run`

---

### Task 5: GUI — Batch tab

**Files:**
- Modify: `gui.py`
- Test: `tests/test_gui_batch.py` (`pytestmark = pytest.mark.gui`; reuse `_run_in_gui` by importing it from `test_gui_config`)

**Interfaces:**
- Consumes: Task 1 (`NAME_FIELDS`, `validate_pattern`, `PatternError`, `build_stem`), Task 3 (everything in `batch.py`, `MappingConfig.filename_pattern`).
- Produces, in `App`:
  - `self.pattern_var: ctk.StringVar`. `_build_config()` passes `filename_pattern=self.pattern_var.get().strip()`, and `_on_config_selected` sets it from the loaded profile, so "Save Config" stores it.
  - Refactor `_open_xml` into `_load_xml(path: str) -> bool` (everything after the dialog). `_open_xml` keeps the dialog and calls it.
  - A new tab `"Batch"`, added after `"Preview"`, built by `_build_batch_tab()`, containing:
    - the buttons **Choose Folder…** (`filedialog.askdirectory`) and **Choose Files…** (`filedialog.askopenfilenames`). Both store `self.batch_inputs = collect_xml_files(...)` and call `_load_xml(self.batch_inputs[0])`. Show `"{n} XML files"`, or `"No XML files found"`.
    - an output-folder entry plus **Browse…**, defaulting to the chosen folder (or the folder of the first selected file).
    - a pattern entry bound to `self.pattern_var`, with one small button per `NAME_FIELDS` entry beneath it. Clicking one inserts `{field}` at the entry cursor (`_insert_pattern_field(name: str)`). The field must never need typing.
    - an info label with exactly this text: `One batch = one supplier's XML format. The mapping is taken from the first file.`
    - a read-only `CTkTextbox` holding the planned-names list, one line per file in the form `{filename}  ←  {source}`, followed by indented `⚠ {warning}` / `✖ {error}` lines.
    - the buttons **Preview First** (`_batch_preview()`: validate the pattern and show a `PatternError` in red under the entry, `plan_batch`, fill the list, call the existing `_generate_preview()` for `batch_inputs[0]`, then switch to the Preview tab), **Generate All** (`_batch_run()`, disabled until a plan exists, and re-planning right before running), and **Stop** (`_batch_stop()`, which sets a `threading.Event`).
    - a `CTkProgressBar` and a label `"{i} of {n}: {basename}"`, updated through `self.after(0, …)` from the worker thread.
  - When finished: the status label shows `"Batch done: {s} succeeded, {f} failed"` (plus `" (stopped)"`), and failures are listed in the textbox with their reasons.
  - Single-file **Generate PDF**: if the pattern is non-empty and valid, `initialfile` = `build_stem(pattern, header_values(self.xml_path, config))[0] + ".pdf"`.
  - The credit footer is window-level and already present; no new top-level window is added.

- [ ] **Step 1: Write the failing GUI tests.** Each one patches `filedialog.askdirectory`/`askopenfilenames` in the snippet:
  - `test_batch_folder_preview_lists_planned_names`: a folder with two `invoice.xml` in subfolders, `app.pattern_var.set("{period}_{invoice_number}")`, `app._batch_preview()`. Pump `app.update()` until the preview finishes (poll `app.preview_pdf_path`, timeout 30 s). Print the textbox content and assert `"2026-03_INV-1.pdf"` and `"2026-03_INV-2.pdf"` are in it.
  - `test_batch_generate_all_writes_named_pdfs`: the same, then `app._batch_run()`. Pump until the status starts with `"Batch done"` (timeout 60 s). Assert the output dir listing equals the two names and the status is `"Batch done: 2 succeeded, 0 failed"`.
  - `test_field_button_inserts_token`: `app.pattern_var.set("")`; `app._insert_pattern_field("supplier_name")` → `pattern_var.get() == "{supplier_name}"`.
  - `test_pattern_saved_with_profile`: set the pattern, then `app._build_config().filename_pattern == "{invoice_number}"`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `xvfb-run -a python -m pytest tests/test_gui_batch.py -q` (install `customtkinter` in the venv first if it is missing; the suite currently skips GUI tests here for that reason)
Expected: `AttributeError` on `_batch_preview` / `pattern_var`.

- [ ] **Step 3: Implement the Batch tab** as specified.

- [ ] **Step 4: Run the GUI tests and the full suite**

Run: `xvfb-run -a python -m pytest -q`
Expected: all pass, with **no GUI skips**.

- [ ] **Step 5: Look at it.** Launch `python xml_invoice_to_pdf.py --gui` under Xvfb, take a screenshot of the Batch tab after Preview First, and check that nothing is clipped at the default window size.

- [ ] **Step 6: Commit**: `feat(gui): Batch tab — pattern naming, preview first, X of Y progress, stop`

---

### Task 6: Docs and release v0.7.0

**Files:**
- Modify: `README.md` (new "Batch conversion and file naming" section: pattern syntax, field list, `period`, dropped characters, `_2` suffixes, CLI examples including `--dry-run`), `CHANGELOG.md` (new `[0.7.0] — <date>` under `### Added`; `[Unreleased]` back to `_Nothing yet._`; compare links), `__about__.py` (`__version__ = "0.7.0"`), `CLAUDE.md` (add `naming.py` and `batch.py` to the module table).

- [ ] **Step 1: Run the full suite under Xvfb.** All pass, with no GUI skips.
- [ ] **Step 2: Update the docs and bump the version** as listed above.
- [ ] **Step 3: Commit** `chore(release): v0.7.0 — batch conversion with pattern-based names`, with a body explaining why and the evidence.
- [ ] **Step 4: Tag and push**: `git tag -a v0.7.0 -m "v0.7.0 — batch conversion with pattern-based names"`, `git push origin main`, `git push origin v0.7.0`.
- [ ] **Step 5: Create the GitHub release** from the CHANGELOG section plus the Downloads paragraph stating that there is no Intel (x86_64) macOS binary, with the README link.
- [ ] **Step 6: Watch "Release binaries"**: `gh run watch <id> --exit-status`. Expected: success, and four assets on the release.
