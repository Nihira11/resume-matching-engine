"""
Regression tests for ATS parsability detection

Fixtures were generated with reportlab specifically to nail down two bugs
found during development:
  - plain.pdf: an early version of the multi-column heuristic false-
    positived on any normally-wrapped single-column paragraph
  - tabled.pdf: a borderless layout table (no visible grid lines) – the
    default pdfplumber line-based table strategy misses these entirely,
    which matters because that's the more common case in real resume
    templates
  - twocol2.pdf: a genuine two-column sidebar layout with independently
    flowing columns (not row-paired data, which reads more like a table)

Run: pytest tests/test_ats_parsability.py
"""
import os

from src.ingestion.ats_parsability import check_parsability

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_plain_single_column_scores_clean():
    result = check_parsability(os.path.join(FIXTURES, "plain.pdf"))
    assert result.score == 100.0
    assert not result.has_tables
    assert not result.has_multi_column


def test_borderless_table_detected():
    result = check_parsability(os.path.join(FIXTURES, "tabled.pdf"))
    assert result.has_tables
    assert result.score < 100.0


def test_two_column_layout_detected():
    result = check_parsability(os.path.join(FIXTURES, "twocol2.pdf"))
    assert result.has_multi_column
    assert result.score < 100.0

def test_ordinary_text_page_is_not_a_table(tmp_path):
    """Regression: the text strategy treats a whole page of aligned text as
    one giant grid, so every real resume was flagged and every score was
    exactly 75/100 -- measured 25 out of 25 on random Kaggle resumes. A
    table has to be a localised grid."""
    import fitz  # PyMuPDF, already a dependency

    path = tmp_path / "prose.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for i in range(30):
        page.insert_text((72, y), f"Delivered project {i} using Python and SQL for the analytics team")
        y += 20
    doc.save(str(path))
    doc.close()

    result = check_parsability(str(path))
    assert not result.has_tables
    assert result.score == 100
