# Batch conversion with pattern-based PDF names — design

Date: 2026-10-22 · Status: draft for approval · Target: v0.7.0 (minor: new feature)

## Why

Invoice XMLs often arrive with names that say nothing, typically `invoice.xml`,
one per folder. Today the CLI already converts several files (`*.xml`), but each
PDF is named after its XML (`invoice.pdf`), so a batch from several folders gives
a pile of identically named PDFs. The GUI opens one file at a time.

The maintainer wants each PDF's name to say what it is: the period, the invoice
number, the supplier, or whatever combination the job needs. Typical batches are
a dozen files and can run to a few dozen.

Success: point the app at a folder (or pick files), check the first PDF and the
list of planned names, click once, and get correctly named PDFs while watching
"X of Y" progress. The same is possible from the terminal.

## Goals

1. Name output PDFs from a user-defined **pattern** built from invoice fields
   plus free text.
2. Make **filesystem-unsafe characters** in field values harmless.
3. Batch in **both GUI and CLI**, sharing one implementation of naming and
   queueing.
4. **Preview before the run**: the first invoice's PDF plus the full list of
   planned names.
5. Show **progress "X of Y"** during the run, without freezing the window.
6. Store the pattern **in the mapping profile**.

## Non-goals

- Batches of thousands of files, parallel rendering, resumable queues. The
  expected scale is tens of files; a single sequential background worker is
  enough.
- Batches that mix XML schemas. **One batch = one supplier's format**, decided
  by the maintainer: "jeden batch na serię — od jednego dostawcy — jasny
  przekaz dla użytkownika". One mapping is applied to every file; there is no
  per-file auto-matching. A file whose structure does not fit fails
  individually and is reported (see Queue and progress); it does not stop the
  batch.
- Item-level fields (product, lot, quantity) in names. An invoice has many
  items; there is no single value.
- Translating PDF labels (an existing, separate limit; see CLAUDE.md).

## Anti-goals (would make this a failure even if it "works")

- **Silently overwriting** an existing PDF.
- A name that is valid on Linux but **cannot be copied to Windows** (a colon, a
  trailing dot, `CON.pdf`).
- One broken XML **aborting** the remaining files.
- The GUI **freezing** while a batch runs.
- Changing what any **existing built-in profile** produces (`configs/*.json` are
  protected; see below).

## Behaviour (agreed with the maintainer)

### Pattern

- Syntax: field names in braces, any literal text between them, e.g.
  `{period}_{invoice_number}_{supplier_name}` →
  `2026-10_FV-123-2026_Acme Ltd.pdf`. The `.pdf` extension is appended by the
  app and is not part of the pattern. *(Brace syntax is the builder's
  proposal, accepted in conversation.)*
- Available fields: every **header** slot (those in `HEADER_SLOTS` in
  `mapping.py`: supplier, buyer, invoice details, totals) referred to by its slot
  id, plus the derived field below.
- **Derived field `period`** = year and month of `issue_date`, formatted
  `YYYY-MM` (e.g. `2026-10`). Agreed with the maintainer: "month from the issue
  date".
- An unknown field name in the pattern is a **validation error** shown before the
  run (GUI: next to the pattern field; CLI: error exit before any file is
  touched), not a placeholder.
- An empty pattern means today's behaviour: the PDF is named after its XML stem.

### Missing values

If a field used in the pattern is empty or missing for a given invoice, the
placeholder `no-<slot_id>` (e.g. `no-supplier_name`) is inserted and that row of
the planned-names list carries a warning. The file is still generated. Agreed
with the maintainer. The placeholder is English because every artefact this app
produces is English (CLAUDE.md).

### Unsafe characters

Applied to each **substituted field value** (and to the final name as a whole):

- remove `/ \ : * ? " < > |` and control characters (U+0000–U+001F, U+007F);
- collapse runs of whitespace to one space; strip leading/trailing whitespace
  and trailing dots;
- if the stem (case-insensitive, ignoring anything after the first dot) is a
  Windows reserved name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`,
  `LPT1`–`LPT9`), append `_`;
- cap the final name at a safe length (proposal: 200 characters before `.pdf`)
  so that suffixes and long folder paths still fit.

The same rules apply on every OS, so a batch produced on Linux copies cleanly to
Windows. *(Builder's call, accepted.)* Characters are dropped, not replaced, as
the maintainer asked: `FV/2026/10` → `FV202610`.

### Name collisions

When two invoices in the batch produce the same name, or a file of that name
already exists in the output folder, append `_2`, `_3`, … before `.pdf`
(`2026-10_Acme.pdf`, `2026-10_Acme_2.pdf`). Agreed with the maintainer. Nothing
is ever overwritten. Comparison is case-insensitive, because Windows and macOS
filesystems are.

Resolution is computed once, during planning, so the preview list shows the
final names, including suffixes. If a file appears on disk between planning and
writing, the writer re-resolves rather than overwriting.

### Choosing inputs

Both, agreed with the maintainer:

- **a folder**, collecting `*.xml` recursively from its subfolders;
- **selected files**.

Order: sorted by path, so runs are reproducible and "the first file" for preview
is predictable.

### Which mapping a GUI batch uses

The GUI today builds its mapping from the XML that is open (discovery,
auto-match, positional XPaths winning over the profile's). The batch reuses that
flow: when a batch is chosen, its **first file** (by the sort order above) is
loaded exactly as "Open XML" loads a file today. The mapping tab shows that
file, the user can correct it, and the resulting config, from
`_build_config()`, is applied unchanged to every file in the batch. The preview
therefore shows the same file the mapping was built from.

The UI says this plainly next to the batch controls, in English, e.g. "One
batch = one supplier's XML format. The mapping is taken from the first file."
That way a user does not expect mixed suppliers to work. A file that does not
fit shows up as a failure with its reason (typically the header element not
being found), not as a PDF with blank fields.

### Output folder

One output folder for the whole batch, chosen by the user. *(Builder's
default: the GUI suggests the input folder (or the folder of the first selected
file); the CLI requires `--output-dir` when a pattern is used.)* No mirroring of
input subfolders. The flat folder is the point of renaming.

### Preview (GUI)

Before the run, the app:

1. renders the **first** invoice of the batch into the Preview tab (the existing
   preview machinery);
2. shows the **planned-names list**: one row per input, `final name ← source
   path`, with warning rows for missing fields and visible `_2`/`_3` suffixes.

Then the user presses **"Generate all"**. Agreed with the maintainer: "tak,
dokładnie tak".

Planning only parses the header fields; it does not render PDFs, so it is fast
for tens of files.

### Queue and progress

- One background worker processes files sequentially; the GUI stays responsive
  (same `threading` + `self.after` pattern `gui.py` already uses).
- Progress shows **"X of Y"** and the current file.
- **Stop** button: finishes the current file, skips the rest, and reports what
  was done. *(Builder's proposal.)*
- A file that fails (unparseable XML, missing header element) is recorded and
  the batch continues. At the end a summary: N succeeded, N failed, and for each
  failure the source path and the reason.

### CLI

Same logic, new options on the existing entry point:

- `--name-pattern "{period}_{invoice_number}"` — overrides the profile's
  pattern for this run;
- `--output-dir DIR` — where named PDFs go;
- `--recursive DIR` (or a directory given as a positional argument; builder's
  choice) — collect XMLs from a folder tree;
- `--dry-run` — print the planned-names list (with warnings) and exit without
  writing anything. This is the CLI's preview.

Progress lines carry the counter: `[3/40] OK path/invoice.xml -> out/2026-10_FV-3.pdf`.
The existing final line `Done: N succeeded, N failed` and the non-zero exit code
on any failure stay. All messages English (a test enforces no Polish output).

### Profile storage

- New field on `MappingConfig`: `filename_pattern: str = ""`. `save_config`
  writes it (it uses `asdict`); `load_config` reads it with default `""`, so all
  existing profiles keep working unchanged.
- In the GUI, the pattern is edited alongside the mapping and saved with "Save
  config". Agreed with the maintainer: "razem z profilem mapowania".
- **Built-in `configs/*.json` are not edited.** They are protected, and without
  a pattern they behave exactly as today.

## Constraints from the codebase (CLAUDE.md)

- Flat modules at the repo root. Naming/sanitising/collision logic belongs in a
  new module (proposal: `naming.py`), and batch planning and running in another
  (proposal: `batch.py`), both used by the CLI and the GUI. New modules must be
  added to `xml-to-pdf.spec` if it enumerates modules.
- Never mutate a caller's `MappingConfig` (invariant 8): `--name-pattern` must
  not be written back into a shared config object.
- Header values for naming must be read the same way the renderer reads them
  (`InvoiceData` with the profile's `header_xpath`, the slot → tag mapping), so
  the name shows what the PDF shows.
- `issue_date` comes in various formats. `period` must parse at least ISO
  `YYYY-MM-DD` (with or without time) and the common European `DD.MM.YYYY` /
  `DD/MM/YYYY`. If the date cannot be parsed, it counts as a missing value:
  `no-period` plus a warning.
- Tests first, asserting on real artefacts: files actually written to a temp
  folder with the expected names; CLI via subprocess; the GUI batch flow under
  Xvfb with the `gui` marker.
- Release as v0.7.0 with CHANGELOG and release-body rules (including the
  no-Intel-macOS-binary line).
- Credit footer already exists in the GUI; any new dialog/window that is a
  full shell gets it too.

## Decisions settled after the builder check (builder's calls)

- **Where the pattern applies.** Only in *batch-to-folder* mode: the GUI batch
  flow, or the CLI with `--output-dir`. A plain CLI run without `--output-dir`
  behaves exactly as today (PDF next to its XML), even if the profile carries a
  pattern, so existing scripts do not change. `-o` stays single-file and wins.
  `--name-pattern` without `--output-dir` is a usage error. The GUI's
  single-file "Generate PDF" uses the profile's pattern only to *suggest* the
  file name in the save dialog.
- **Collisions with an empty pattern.** In batch-to-folder mode the no-overwrite
  and `_2`/`_3` rules always apply; an empty pattern just means the stem is the
  XML's own name (`invoice.pdf`, `invoice_2.pdf`, …). The legacy
  next-to-the-XML mode keeps its current overwrite behaviour.
- **Raw vs rendered values.** Names use the raw header text as read through
  the profile's mapping (`InvoiceData.h()` via the slot → tag mapping), not
  the renderer's display formatting. `period` is the only derived value.

## Left to the builder

- Exact GUI layout: where the batch controls, pattern field, names list and
  progress bar live (new tab vs. bottom bar). Include a clickable list of
  available fields next to the pattern box, so nobody has to type slot ids from
  memory (maintainer's general preference: pick, don't hand-type).
- Exact CLI flag spelling, within the shape above.
- Module and function names.
- Length cap value, within the rule above.
