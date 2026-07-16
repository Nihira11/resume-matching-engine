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