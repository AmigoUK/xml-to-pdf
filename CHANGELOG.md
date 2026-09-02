# Changelog

All notable changes to **xml-to-pdf** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.6.0] — 2026-09-02

### Changed
- **BREAKING (CLI output):** every user-facing string is English now. The CLI
  messages and `--help` were Polish, left over from the original single-format
  tool, while the README, GUI, PDF, releases and commits were all English.
  Scripts grepping for `Blad`, `Gotowe` or `N sukces, N bledow` need updating —
  the equivalents are `Error`, `Done` and `N succeeded, N failed`. A test now
  fails if a Polish string reaches stdout or stderr.
- The `screenshoots/` directory is spelled `screenshots/`, with the README
  links updated. Releases up to v0.5.1 keep the old spelling in their own tree.
- The invoice number in the header bar is drawn on one line, shrinking to fit
  instead of wrapping. A long number used to break mid-token
  ("INV-2026-0" / "03842"), which is easy to mistranscribe from a printed
  invoice.

### Added
- `CLAUDE.md`: project overview, the exact dependency versions the code is
  verified against, the conventions, the eight invariants each of which
  represents a bug that shipped, and the protected files.
- README screenshots regenerated from the current code — the old ones still
  showed the hidden payment badge and the blank Unit column, both fixed in
  v0.1.0.

### Notes
- Flat module layout is recorded as the current shape, not a principle:
  publishing to PyPI needs a real package, and CLAUDE.md spells out what that
  migration involves so it happens deliberately rather than halfway.

## [0.5.1] — 2026-09-01

### Fixed
- **Every field mapped, yet the PDF came out with empty boxes.** Discovery
  walked the tree, found the real header and listed its tags — so the GUI
  reported 35/35 — but then emitted a simplified `.//Header` XPath. That
  resolves to whichever element of that name comes first in the document, so an
  earlier `<Header>` anywhere in the file (metadata blocks, archived copies)
  won, `header.find(tag)` returned nothing, and the supplier, buyer, invoice
  number, dates and totals all rendered blank. Discovery now emits the full
  path from the root (`./Invoice/Header`), with a positional predicate wherever
  a tag repeats among its siblings, so the XPath resolves to exactly the element
  that was read.
- **A repeating block before `<Items>` was mistaken for the line items.** The
  first repeating group in breadth-first order won, so a `<Taxes>` or
  `<Contacts>` block took priority and the items table rendered empty. The
  richest group now wins, scored by how many fields a member carries.
- The Polish `Naglowek`/`Pozycja` fast path bypassed both fixes and returned the
  same ambiguous XPaths; it now goes through the same path builder, and picks
  the `Naglowek` carrying the most fields.

### Added
- Tests for the GUI path itself (`tests/test_gui_config.py`), driving a real
  window headlessly: opening an XML, the config `_build_config()` produces, and
  a full render through it. This is the seam the bug lived in and no test
  covered it. They skip where there is no display or no CustomTkinter, and CI
  now installs xvfb so they run there.
- Seven document shapes exercised end to end, including the reported one.

### Notes
- Saved configs keep working. A stored `.//Header` still resolves correctly in
  an unambiguous document; re-opening the XML in the GUI is what upgrades a
  profile to the precise path.
- Verified on reportlab 4.4.10 and 5.0.1, since `requirements.txt` allows both.

## [0.5.0] — 2026-09-01

### Added
- **Credit footer in the GUI**: a small muted line across the bottom of the
  window — `dev@attv.uk · Project & Development: Tomasz 'Amigo' Lewandowski ·
  www.attv.uk · GitHub · v0.5.0` — with the email, website and repository as
  clickable links. Verified rendered in both light and dark appearance modes.
- The same credit line is printed by `--version`.
- `__about__.py` gains `footer_segments()` / `footer_text()`, with a test
  asserting the GitHub link still matches the checkout's actual git remote.

### Changed
- The Intel macOS build moved into its own best-effort job. GitHub is retiring
  the x86_64 macOS images, and a queued `macos-13` runner used to block the
  `checksums` job — which is why v0.4.0 shipped without `SHA256SUMS.txt`. The
  three main platforms and their checksums no longer wait for it; the Intel job
  publishes its own `.sha256` beside its tarball.

### Notes
- The credit footer is deliberately **not** added to the generated PDF. That
  document is the user's invoice, sent on to their own customers; a developer
  credit does not belong on it.

## [0.4.0] — 2026-09-01

### Added
- **macOS Intel (x86_64) build.** `macos-latest` is Apple silicon, so Intel Mac
  users previously had nothing they could run.

### Changed
- **BREAKING (asset names):** the Unix binaries ship as `.tar.gz` rather than
  bare files. A GitHub release asset carries no POSIX permissions, so a bare
  download arrived as `-rw-r--r--` and needed `chmod +x` before it would run;
  a tarball preserves the executable bit. Windows keeps the bare `.exe`, which
  has no permission bit to lose. Download URLs for the Unix assets change
  accordingly.

### Fixed
- README: `gh attestation verify` needs GitHub CLI 2.49 or newer; documented
  the plain-API equivalent for older versions. Also explains why the Unix
  executables have no filename extension.

## [0.3.0] — 2026-09-01

### Added
- **Build provenance** on every release binary, signed through Sigstore by the
  GitHub Actions build. A download can be traced to the repository, tag and
  workflow run that produced it:
  `gh attestation verify xml-to-pdf-windows-x64.exe --repo AmigoUK/xml-to-pdf`.
- `SHA256SUMS.txt` attached to each release.
- README: how to verify a download, and what to do about the "unknown
  publisher" warning.

### Notes
- The binaries remain unsigned, so Windows SmartScreen and macOS Gatekeeper
  still warn on first run. This cannot be fixed for free — SmartScreen goes by
  publisher reputation, which a self-signed certificate does not earn, and
  Gatekeeper needs a notarised Apple Developer ID. Provenance plus checksums
  give verifiable authenticity instead; the per-file "Run anyway" / right-click
  "Open" confirmation is documented rather than telling anyone to disable the
  protection.

## [0.2.0] — 2026-09-01

### Added
- **Standalone executables** for Windows, Linux and macOS, attached to every
  release. DejaVu Sans and all seven language profiles are bundled, so there is
  nothing to install: no Python, no dependencies, no fonts.
- `xml-to-pdf.spec` (PyInstaller) and `scripts/fetch_fonts.py`, which fetches
  the DejaVu faces at build time rather than vendoring them into git.
- `.github/workflows/release.yml`: pushing a `vX.Y.Z` tag runs the test suite,
  then builds and smoke-tests each platform's binary and uploads it to the
  release. PyInstaller does not cross-compile, so each one is built on its own
  runner.
- `paths.py`, which resolves fonts and configs identically from a source
  checkout and from a frozen bundle. Files next to the executable take
  precedence over the bundled copies, so users can substitute their own fonts
  or mapping profiles without rebuilding.
- `--config` now accepts a profile name as well as a path (`--config polish`),
  which is what makes the shipped profiles usable from an executable that has
  no `configs/` directory beside it. An unknown name lists what is available.

### Fixed
- The `.venv` auto-relaunch is skipped in a frozen build. There
  `sys.executable` is the application itself, so a `.venv` directory happening
  to sit next to the executable would have made it re-exec an unrelated
  interpreter with the application's arguments.
- `reportlab.graphics.barcode` loads its symbology modules dynamically, which a
  static import scan cannot see; the first build died with `No module named
  reportlab.graphics.barcode.code93`. The spec collects them explicitly.
- Font lookup no longer depends on `__file__`, which does not point anywhere
  useful in a one-file bundle.

## [0.1.0] — 2026-09-01

First versioned release. Everything before this point is untagged history; this
entry covers the audit fixes applied on top of it.

### Added
- `pytest` suite (106 tests) asserting real PDF geometry: word bounding boxes
  are read back with `pdftotext -bbox` and the barcodes are decoded with
  `zbarimg`, so layout and encoding regressions fail the build rather than
  being spotted by eye.
- Namespace support — documents declaring `xmlns` on the root (UBL-style) are
  parsed by flattening namespace prefixes at parse time.
- `parse_amount()` / `format_amount()`: tolerant monetary parsing (decimal
  comma, either thousands convention, non-breaking spaces, trailing currency
  codes).
- `gs1_encode()`: builds conformant GS1-128 payloads (FNC1 + AI data).
- `fit_paragraph()`: text that will not fit its box is shortened with an
  ellipsis instead of overflowing.
- `resolve_xpaths()`: one documented rule for which XPaths a config gets.
- `barcode_cards_per_page()`: barcode page count derived from the layout
  constants instead of a hardcoded 5.
- `--version` flag; version lives in `__about__.py`.
- `requirements-dev.txt`.

### Fixed
- **Items and batch rows overflowed the footer.** Row heights were measured on
  an unstyled table while drawing applied different paddings, so cell text
  wrapped differently in the two passes and the paginator split on wrong
  numbers. Invoices above ~16 items printed rows up to 14 mm below the footer
  margin, over the footer text. Both passes now share `_build_table()`.
- **BREAKING (output):** barcodes encoded the human-readable string literally,
  parentheses and all, producing a plain Code 128 that no GS1 system accepts.
  They are now real GS1-128 symbols. Previously generated PDFs decode
  differently from new ones.
- Missing italic DejaVu faces aborted every conversion, although nothing in the
  layout uses italics. Regular + Bold now suffice (as shipped by Debian's
  `fonts-dejavu-core`); a genuinely missing required face raises
  `FileNotFoundError` instead of crashing inside ReportLab.
- A decimal comma (`1,50`) raised `ValueError` and produced no PDF at all.
- Auto-matching was non-deterministic: ties were broken by set iteration order,
  so the same XML mapped `item_code` to `TowarKod`, `TowarKodEan` or
  `TowarKodEan128` depending on the run.
- Auto-matching keyword bugs: a stray space in `"compradorc alle"`,
  `cod`/`kod` typos that made both Polish postal codes unmatchable, a missing
  letter in `"odbiorcnip"`, and shortened copies of shared vocabularies that
  left German `ArtikelBezeichnung` and Dutch `ArtikelNaam` unmatched for the
  batch and barcode product-name slots. All seven shipped configs now
  round-trip 35/35.
- The currency badge was laid out on top of the payment badge, so the payment
  method was never visible.
- Over-long supplier/buyer names printed past the page top and over their own
  labels and address lines.
- A partially coded invoice (only some items carrying `Ean128Code`) emitted a
  trailing blank barcode page and footers reading "Page 5 of 4".
- `"include_barcodes": false` in a config was silently overridden by the CLI.
- `xml_to_pdf()` mutated the config it was given, leaking overrides between
  files in a batch run.
- `configs/british_english.json` — the default config — did not map
  `item_unit` or `barcode_product_name`, leaving the Unit column and the
  barcode cards' product name blank.
- Three different default XPaths lived in three places, one of them Polish; the
  GUI's copy silently overrode the XPaths of any config the user loaded.
- An invoice with zero lines raised instead of rendering empty tables.
- GUI: "Open in Viewer" existed only when PyMuPDF was absent, while the preview
  told users to press it when Pillow was absent; the preview leaked one temp
  file per click; the diagnostic named the wrong package.
- `requirements.txt` was missing `pillow`, which `preview.py` imports.
- The English PDF said "Delivery Note (WZ)", leaking a Polish abbreviation.

### Security
- `DOCTYPE` declarations are rejected before parsing. XXE and entity-expansion
  payloads are therefore unreachable regardless of the Python/expat version,
  rather than relying on the runtime's own amplification limits.

[Unreleased]: https://github.com/AmigoUK/xml-to-pdf/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.6.0
[0.5.1]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.5.1
[0.5.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.5.0
[0.4.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.4.0
[0.3.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.3.0
[0.2.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.2.0
[0.1.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.1.0
