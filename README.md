# XML to PDF Invoice Converter

A Python tool for exporting XML invoice files to professionally formatted PDF documents.

## Features

- Converts XML invoice data into clean, multi-page PDF reports
- Items and batch tables automatically paginate across pages with repeated headers
- EAN-128 / GS1-128 barcode pages for each invoice item
- Configurable field mapping — supports different XML schemas via JSON config files
- GUI mode (CustomTkinter) for visual field mapping and one-click PDF generation
- CLI mode for single-file or batch conversion

## Installation

```bash
pip install -r requirements.txt
```

DejaVu Sans fonts are required for Polish character support. Place `DejaVuSans*.ttf` files in the project directory or use `--font-dir` to specify their location.

## Usage

### CLI

```bash
# Convert a single invoice
python xml_invoice_to_pdf.py invoice.xml

# Specify output path
python xml_invoice_to_pdf.py invoice.xml -o output.pdf

# Batch convert multiple files
python xml_invoice_to_pdf.py *.xml

# Skip barcode pages
python xml_invoice_to_pdf.py invoice.xml --no-barcodes

# Use a custom field mapping config
python xml_invoice_to_pdf.py invoice.xml --config configs/default.json
```

### GUI

```bash
python xml_invoice_to_pdf.py --gui
```

## Project Structure

```
xml_invoice_to_pdf.py  — CLI entry point
pdf_renderer.py        — PDF drawing and pagination logic
xml_parser.py          — XML invoice parsing and field discovery
mapping.py             — Field mapping configuration and auto-matching
gui.py                 — CustomTkinter GUI
preview.py             — PDF preview helper
configs/               — Saved mapping profiles
requirements.txt       — Python dependencies
```
