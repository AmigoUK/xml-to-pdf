# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec.

    pyinstaller xml-to-pdf.spec

Produces a single self-contained executable. Windows builds must run on
Windows: PyInstaller does not cross-compile, which is why the .exe comes from
the windows-latest job in .github/workflows/release.yml rather than from a
developer's Linux box.

Fonts: DejaVu Sans is bundled at the archive root, because Windows has no
system copy and the renderer requires it. The build fetches the .ttf files into
./fonts first (see the workflow, or scripts/fetch_fonts.py for a local build).
Anything the user drops next to the executable still wins — see
paths.font_search_paths().
"""

import os

datas = []
binaries = []
hiddenimports = []

# reportlab.graphics.barcode loads every symbology module dynamically when the
# package is first imported, so a static import scan finds none of them and the
# frozen build dies with "No module named reportlab.graphics.barcode.code93".
try:
    from PyInstaller.utils.hooks import collect_submodules
    hiddenimports += collect_submodules("reportlab.graphics.barcode")
except Exception:
    hiddenimports += [
        f"reportlab.graphics.barcode.{name}" for name in
        ("code128", "code93", "code39", "usps", "usps4s", "ecc200datamatrix",
         "eanbc", "qr", "qrencoder", "dmtx", "widgets", "lto")
    ]

# Mapping profiles, so the shipped languages are available out of the box.
if os.path.isdir("configs"):
    datas += [(os.path.join("configs", f), "configs")
              for f in os.listdir("configs") if f.endswith(".json")]

# DejaVu Sans at the archive root, where paths.resource_dir() looks.
if os.path.isdir("fonts"):
    datas += [(os.path.join("fonts", f), ".")
              for f in os.listdir("fonts")
              if f.endswith(".ttf") or f.startswith("LICENSE")]

# CustomTkinter ships JSON themes and assets that the module loads at runtime;
# PyInstaller cannot see those through imports alone.
try:
    from PyInstaller.utils.hooks import collect_data_files
    datas += collect_data_files("customtkinter")
except Exception:  # customtkinter absent (CLI-only build) — nothing to collect
    pass

a = Analysis(
    ["xml_invoice_to_pdf.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "numpy", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="xml-to-pdf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console kept on: the same executable is the CLI (xml-to-pdf invoice.xml)
    # and the GUI (no arguments, or --gui). A windowed build would silence the
    # CLI's output and its error messages.
    console=True,
    disable_windowed_traceback=False,
    codesign_identity=None,
    entitlements_file=None,
)
