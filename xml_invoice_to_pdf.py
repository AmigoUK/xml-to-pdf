#!/usr/bin/env python3
"""
xml_invoice_to_pdf.py
=====================
Konwertuje faktury XML (format Domson/polski) do profesjonalnego PDF
z tabela pozycji, danymi partii i kodami kreskowymi EAN-128 / GS1-128.

Wymagania:
    pip install reportlab

Uzycie:
    python xml_invoice_to_pdf.py faktura.xml                    # -> faktura.pdf
    python xml_invoice_to_pdf.py faktura.xml -o wynik.pdf       # -> wynik.pdf
    python xml_invoice_to_pdf.py *.xml                          # batch: wiele plikow
    python xml_invoice_to_pdf.py faktura.xml --no-barcodes      # bez strony z EAN-128
    python xml_invoice_to_pdf.py faktura.xml --font-dir /fonts  # wlasna sciezka do czcionek
    python xml_invoice_to_pdf.py --gui                          # tryb graficzny
"""

import argparse
import os
import sys

# Auto-relaunch with venv Python if running under system Python and venv exists
_VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python3")
if (
    os.path.isfile(_VENV_PYTHON)
    and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON)
):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

from __about__ import __version__
from pdf_renderer import xml_to_pdf
from mapping import MappingConfig, load_config


def main():
    parser = argparse.ArgumentParser(
        description="Konwersja faktur XML -> PDF z kodami EAN-128",
        epilog="Przyklady:\n"
               "  python xml_invoice_to_pdf.py faktura.xml\n"
               "  python xml_invoice_to_pdf.py faktura.xml -o wynik.pdf\n"
               "  python xml_invoice_to_pdf.py *.xml\n"
               "  python xml_invoice_to_pdf.py faktura.xml --no-barcodes\n"
               "  python xml_invoice_to_pdf.py --gui\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("xml_files", nargs="*", help="Pliki XML faktur do konwersji")
    parser.add_argument("-o", "--output", help="Sciezka wyjsciowa PDF (tylko dla 1 pliku)")
    parser.add_argument("--no-barcodes", action="store_true",
                        help="Pomin strone z kodami kreskowymi EAN-128")
    parser.add_argument("--font-dir", help="Katalog z czcionkami DejaVuSans*.ttf")
    parser.add_argument("--gui", action="store_true", help="Uruchom tryb graficzny (GUI)")
    parser.add_argument("--config", help="Sciezka do pliku konfiguracji JSON z mapowaniem pol")
    parser.add_argument("--version", action="version",
                        version=f"xml-to-pdf {__version__}")

    args = parser.parse_args()

    # GUI mode
    if args.gui or (not args.xml_files):
        try:
            from gui import launch_gui
            launch_gui()
        except ImportError as e:
            print(f"Blad: Nie mozna uruchomic GUI — {e}", file=sys.stderr)
            print("Zainstaluj customtkinter: pip install customtkinter", file=sys.stderr)
            sys.exit(1)
        return

    if args.output and len(args.xml_files) > 1:
        parser.error("Opcja -o/--output dostepna tylko dla pojedynczego pliku.")

    # Load mapping config if specified
    mapping_config = None
    if args.config:
        try:
            mapping_config = load_config(args.config)
        except Exception as e:
            print(f"Blad ladowania konfiguracji: {e}", file=sys.stderr)
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
            print(f"FAIL {xml_path} — Blad: {e}", file=sys.stderr)
            failed += 1

    if len(args.xml_files) > 1:
        print(f"\nGotowe: {success} sukces, {failed} bledow")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
