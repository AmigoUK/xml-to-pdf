# Changelog

All notable changes to **xml-to-pdf** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

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

[Unreleased]: https://github.com/AmigoUK/xml-to-pdf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AmigoUK/xml-to-pdf/releases/tag/v0.1.0
