"""
pdf_utils.py - PDF pages -> images (PyMuPDF, imported as "fitz").

The upload step only COUNTS pages (cheap). Each page is rendered later, when a worker needs it.
"""

import fitz  # PyMuPDF

import config


def page_count(pdf_path):
    """Number of pages. Raises ValueError for a PDF we cannot use."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise ValueError(f"not a readable PDF ({type(e).__name__})") from None
    try:
        if doc.needs_pass:
            raise ValueError("the PDF is password protected")
        n = doc.page_count
        if n == 0:
            raise ValueError("the PDF has no pages")
        if n > config.MAX_PDF_PAGES:
            raise ValueError(f"the PDF has {n} pages; the limit is {config.MAX_PDF_PAGES}")
        return n
    finally:
        doc.close()


def render_page(pdf_path, index, out_path, dpi=150):
    """Render page `index` (0-based) as a PNG file at out_path."""
    doc = fitz.open(str(pdf_path))
    try:
        doc[index].get_pixmap(dpi=dpi, alpha=False).save(str(out_path))
    finally:
        doc.close()
