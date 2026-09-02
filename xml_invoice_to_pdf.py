#!/usr/bin/env python3
"""
xml_invoice_to_pdf.py
=====================
Converts XML invoices into formatted PDFs with an items table, batch details
and EAN-128 / GS1-128 barcodes.

Requirements:
    pip install -r requirements.txt

Usage:
    python xml_invoice_to_pdf.py invoice.xml                    # -> invoice.pdf
    python xml_invoice_to_pdf.py invoice.xml -o result.pdf      # -> result.pdf
    python xml_invoice_to_pdf.py *.xml                          # batch conversion
    python xml_invoice_to_pdf.py invoice.xml --no-barcodes      # skip barcode pages
    python xml_invoice_to_pdf.py invoice.xml --config polish    # a mapping profile
    python xml_invoice_to_pdf.py invoice.xml --font-dir /fonts  # custom font directory
    python xml_invoice_to_pdf.py --gui                          # graphical mode
"""

import argparse
import os
import sys

# Convenience for source checkouts: re-run under ./.venv when there is one.
# Skipped in a frozen build, where sys.executable is this application.
from paths import maybe_reexec_in_venv

maybe_reexec_in_venv()

from __about__ import __version__, footer_text
from pdf_renderer import xml_to_pdf
from mapping import (
    MappingConfig, available_configs, load_config, resolve_config_path,
)


def main():
    parser = argparse.ArgumentParser(
        description="Convert XML invoices to PDF with EAN-128 / GS1-128 barcodes",
        epilog="Examples:\n"
               "  python xml_invoice_to_pdf.py invoice.xml\n"
               "  python xml_invoice_to_pdf.py invoice.xml -o result.pdf\n"
               "  python xml_invoice_to_pdf.py *.xml\n"
               "  python xml_invoice_to_pdf.py invoice.xml --config polish\n"
               "  python xml_invoice_to_pdf.py invoice.xml --no-barcodes\n"
               "  python xml_invoice_to_pdf.py --gui\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("xml_files", nargs="*", help="Invoice XML files to convert")
    parser.add_argument("-o", "--output", help="Output PDF path (single input file only)")
    parser.add_argument("--no-barcodes", action="store_true",
                        help="Skip the EAN-128 / GS1-128 barcode pages")
    parser.add_argument("--font-dir", help="Directory containing DejaVuSans*.ttf")
    parser.add_argument("--gui", action="store_true", help="Launch the graphical interface")
    parser.add_argument("--config",
                        help="Path to a JSON mapping config, or a profile name "
                             "(e.g. 'polish'); profiles live in configs/")
    parser.add_argument("--version", action="version",
                        version=f"xml-to-pdf {__version__}\n{footer_text()}")

    args = parser.parse_args()

    # GUI mode
    if args.gui or (not args.xml_files):
        try:
            from gui import launch_gui
            launch_gui()
        except ImportError as e:
            print(f"Error: cannot start the GUI — {e}", file=sys.stderr)
            print("Install customtkinter: pip install customtkinter", file=sys.stderr)
            sys.exit(1)
        return

    if args.output and len(args.xml_files) > 1:
        parser.error("-o/--output only applies to a single input file.")

    # Load mapping config if specified
    mapping_config = None
    if args.config:
        config_path = resolve_config_path(args.config)
        if config_path is None:
            print(f"Error: no config found for '{args.config}'.", file=sys.stderr)
            print(f"       Available profiles: "
                  f"{', '.join(available_configs()) or 'none'}", file=sys.stderr)
            sys.exit(1)
        try:
            mapping_config = load_config(config_path)
        except Exception as e:
            print(f"Error loading the config: {e}", file=sys.stderr)
            sys.exit(1)

    success, failed = 0, 0
    for xml_path in args.xml_files:
        try:
            out = xml_to_pdf(
                xml_path,
                output_path=args.output,
                # None leaves the config's own setting alone; --no-barcodes is
                # the only reason to override it from the command line.
                include_barcodes=False if args.no_barcodes else None,
                font_dir=args.font_dir,
                mapping_config=mapping_config,
            )
            print(f"OK {xml_path} -> {out}")
            success += 1
        except Exception as e:
            print(f"FAIL {xml_path} — {e}", file=sys.stderr)
            failed += 1

    if len(args.xml_files) > 1:
        print(f"\nDone: {success} succeeded, {failed} failed")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
