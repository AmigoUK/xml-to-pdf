"""
preview.py
==========
PDF-to-image rendering for the GUI preview tab.
Uses PyMuPDF (fitz) when available, falls back to external viewer.
"""

from __future__ import annotations

import os
import tempfile
import webbrowser

try:
    import fitz  # PyMuPDF

    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF."""
    if not HAS_PYMUPDF:
        return 0
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def render_pdf_page(pdf_path: str, page_num: int = 0, dpi: int = 150) -> "Image.Image | None":
    """Render a single PDF page to a PIL Image.

    Returns None if PyMuPDF or Pillow is not available.
    """
    if not HAS_PYMUPDF or not HAS_PIL:
        return None

    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        doc.close()
        return None

    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


def open_in_viewer(pdf_path: str) -> None:
    """Open a PDF in the system's default viewer."""
    webbrowser.open(f"file://{os.path.abspath(pdf_path)}")


def cleanup_temp_files(paths: list[str]) -> None:
    """Remove temporary files."""
    for p in paths:
        try:
            if os.path.isfile(p):
                os.unlink(p)
        except OSError:
            pass
