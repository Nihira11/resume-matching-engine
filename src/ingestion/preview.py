"""
First-page thumbnail of an uploaded resume.

Rendered once at ingestion and stored on the row, rather than kept as a
file: the preview then follows the resume's lifecycle exactly, including
being deleted with it when a session is cleared or expires. A directory
of orphaned PNGs is precisely the kind of thing that outlives the data it
belongs to.

PDF only. DOCX has no page geometry until something lays it out, and
pulling in a renderer for that is a lot of dependency for a thumbnail;
those resumes simply have no preview.
"""
from __future__ import annotations

from pathlib import Path

# 110 dpi: legible at the ~380px the UI displays it at, including on a
# retina screen, without making the row heavy. A full-page render at 72
# dpi looks soft; 150 dpi triples the bytes for no visible gain.
PREVIEW_DPI = 110
MAX_PREVIEW_BYTES = 2_000_000


def render_first_page(file_path: str) -> bytes | None:
    """PNG bytes for page one, or None if the file cannot be rendered."""
    if Path(file_path).suffix.lower() != ".pdf":
        return None

    try:
        import fitz  # PyMuPDF

        with fitz.open(file_path) as document:
            if document.page_count == 0:
                return None
            page = document.load_page(0)
            pixmap = page.get_pixmap(dpi=PREVIEW_DPI)
            data = pixmap.tobytes("png")
    except Exception:  # noqa: BLE001 -- a missing preview must never fail an upload
        return None

    if not data or len(data) > MAX_PREVIEW_BYTES:
        return None
    return data
