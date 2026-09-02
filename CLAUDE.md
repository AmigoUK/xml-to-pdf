# Project Overview

Converts XML invoices into print-ready A4 PDFs: a paginated items table, a
batch/expiry table, totals, and one GS1-128 barcode card per line item. Any XML
schema is supported by mapping 35 fixed "slots" onto that document's own tag
names, either through a saved JSON profile or the CustomTkinter GUI's
auto-matcher. Ships as a CLI, a GUI, and standalone executables for Windows,
macOS and Linux.

# Tech Stack

Runtime:

| Component | Constraint | Verified on |
|---|---|---|
| Python | 3.12+ | 3.12.3 (CI: 3.12) |
| reportlab | `>=4.0` | 4.4.10 **and** 5.0.1 |
| customtkinter | `>=5.2` | 6.0.0 |
| pymupdf | `>=1.24` | 1.28.2 |
| pillow | `>=10.0` | 12.3.0 |

Development and build:

| Component | Constraint | Verified on |
|---|---|---|
| pytest | `>=8.0` | 8.3.4 |
| PyInstaller | build only, not a runtime dep | 6.22.2 |
| DejaVu Sans | 2.37, fetched at build time by `scripts/fetch_fonts.py` | — |

External binaries the test suite shells out to (all optional — the affected
tests skip when missing):

- `poppler-utils` — `pdftotext -bbox`, `pdftoppm`, `pdfinfo`
- `zbar-tools` — `zbarimg`, to decode the generated barcodes
- `xvfb` — to drive the GUI headlessly

CI: GitHub Actions. Release binaries build on `windows-latest`,
`ubuntu-latest`, `macos-latest` (arm64) and `macos-13` (Intel, best effort).

**reportlab spans a major version on purpose.** `>=4.0` means users get 5.x;
run the suite against both before trusting a rendering change.

# Naming & Coding Conventions

**Layout.** Flat modules at the repo root — no package directory. They import
each other as top-level modules (`from mapping import ...`), which is what
keeps the PyInstaller spec simple.

This is the current shape, not a principle to defend. Publishing to PyPI
(the one way to sidestep the unsigned-binary warnings entirely) requires a real
package: a `xml_to_pdf/` directory, a `pyproject.toml` with a console entry
point, and every import updated — plus matching changes in `xml-to-pdf.spec`,
`paths.py` and the test imports. Treat that as a planned migration to be done
in one deliberate change, not as something to drift into halfway.

| Module | Owns |
|---|---|
| `xml_invoice_to_pdf.py` | CLI entry point, argument parsing |
| `pdf_renderer.py` | All drawing, pagination, amount parsing, GS1-128 encoding |
| `xml_parser.py` | Parsing, namespace flattening, schema discovery |
| `mapping.py` | Slots, `MappingConfig`, auto-matching, JSON profiles |
| `gui.py` | CustomTkinter window |
| `preview.py` | PDF → image for the preview tab |
| `paths.py` | Font/config lookup, source vs frozen bundle |
| `__about__.py` | Version and credit-footer content |

**Naming.** `snake_case` for functions and variables; a leading underscore
means module-private and callers outside the module should not reach for it.
Layout constants are module-level `UPPER_CASE` in mm (`FOOTER_MARGIN_Y`,
`BARCODE_CARD_H`). Section headers inside modules use `# ── Name ─────`.

**Language: everything the user or a reader sees is English.** Comments,
docstrings, CLI messages and `--help`, GUI labels, PDF labels, README, commit
messages. The CLI was Polish until v0.6.0 — a leftover from the original
single-format tool — and a test now fails if a Polish string reaches stdout or
stderr. Conversation with the maintainer is Polish; the artefact is not.

The seven language profiles map **input tag names**; they do not translate
output. PDF labels (`Code`, `Description`, `Page X of Y`) are English for every
profile. That is a deliberate limit, not an oversight: translating them needs a
`labels` field on `MappingConfig` and is the obvious next feature if a
non-English customer ever needs to receive one of these PDFs.

**Comments earn their place by explaining why**, especially why the obvious
approach was wrong. Every non-trivial comment in this codebase records a bug
that shipped. Keep that.

**Invariants learned the hard way — breaking one of these has already shipped
a bug:**

1. *Measure with the style you draw with.* Row heights come from
   `_build_table()`; both the measuring pass and the drawing pass go through
   it. Measuring an unstyled table wraps text differently and rows land over
   the footer.
2. *A discovered XPath must resolve to the element that was read.* Emit the
   full path from the root with positional predicates, never a bare
   `.//Tag` — a same-named element earlier in the document silently wins and
   every field renders blank.
3. *Never hardcode a derived dimension twice.* Page counts come from the layout
   constants (`barcode_cards_per_page()`), not from a literal.
4. *Text must fit its box.* Use `fit_paragraph()`/`draw_para()`; clamping a
   reported height without shortening the text still draws the overflow.
5. *Amounts go through `parse_amount()`.* Bare `float()` dies on `1,50`.
6. *Barcodes go through `gs1_encode()`.* Encoding the parenthesised form
   literally produces a Code 128 no GS1 system accepts.
7. *All 35 slots, in all seven profiles.* A test enforces it; an unmapped slot
   renders as a blank column.
8. *Never mutate a caller's `MappingConfig`.* Batch runs share one object.

**Tests.** `pytest`, in `tests/`, one file per concern. Assert on the real
artifact, not on internals: word bounding boxes via `pdftotext -bbox`, barcodes
via `zbarimg`, the GUI via a real window under Xvfb. Tests that need a display
carry the `gui` marker and skip without one. Write the failing test first — the
GUI seam went untested for five releases and that is exactly where the
empty-boxes bug lived.

**Releases.** SemVer in `__about__.py`; `CHANGELOG.md` in Keep a Changelog
format; conventional commit subjects (`fix(scope): what`) with a body saying
why and what evidence proves it. Pushing a `vX.Y.Z` tag runs the suite, then
builds, smoke-tests and uploads the platform binaries.

Every release body must say that **there is no Intel (x86_64) macOS binary**
and point at the README's "Intel Macs: run from source" section. The
best-effort `macos-13` job has never been scheduled, so silence on the point
reads as an oversight to anyone on an Intel Mac. Drop this line only once a
release actually ships that binary.

# Protected Files

Do not modify these without explicit instruction:

- **`configs/*.json`** — mapping profiles users convert real invoices with.
  Adding a slot is fine; re-pointing an existing slot to a different tag
  changes output for documents in production.
- **`example_invoice.xml`** — the fixture the README screenshots and several
  tests are built around.
- **`screenshots/*.png`** — README images, regenerated from the current code.
  Renaming the directory breaks the links in the published README (it was
  `screenshoots/` before v0.6.0; releases up to v0.5.1 keep the old spelling in
  their own tree, which is fine).
- **`CHANGELOG.md` — released sections are append-only.** Never rewrite an
  entry for a published version; add a new one.
- **Published tags and releases** — never retag or force-push `v*`. A tag must
  stay an ancestor of `main`, so merge PRs with a merge commit or a
  fast-forward, never a squash, when a tag points into the branch.
- **`.github/workflows/release.yml`** — the `resolve` job validates the
  `workflow_dispatch` tag input before it reaches any `ref:` or shell command.
  That validation stays.
- **`__about__.py` `REPO_URL`** — pinned by a test to the real git remote.
