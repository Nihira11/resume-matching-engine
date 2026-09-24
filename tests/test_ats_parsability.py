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


def test_running_header_is_detected_despite_differing_content(tmp_path):
    """Regression: the top band catches the running header *and* whatever
    heading sits near the top, so comparing the joined band made two pages
    with an identical header look different and the check never fired."""
    import fitz

    path = tmp_path / "running_header.pdf"
    doc = fitz.open()
    for page_number, heading in enumerate(["EXPERIENCE", "EDUCATION"], start=1):
        page = doc.new_page()
        page.insert_text((60, 40), "Jane Candidate - Curriculum Vitae", fontsize=8)
        page.insert_text((60, 70), heading, fontsize=12)
        page.insert_text((60, 100), "Some content that differs between pages.", fontsize=9)
        page.insert_text((60, 800), f"Page {page_number} of 2", fontsize=8)
    doc.save(str(path))
    doc.close()

    result = check_parsability(str(path))
    assert result.has_headers_footers


def _pdf_with_tables(path, total_pages, table_pages):
    """A document of `total_pages`, `table_pages` of which hold a ruled table."""
    import fitz

    doc = fitz.open()
    for index in range(total_pages):
        page = doc.new_page()
        page.insert_text((60, 70), f"Section {index + 1}", fontsize=12)
        # varied lines: six identical ones stack into perfectly aligned
        # "columns" and are themselves detected as a table, which would
        # make this fixture test the wrong thing
        prose = [
            "Led a reporting workstream across three teams and two regions.",
            "Wrote SQL against a warehouse of forty million transaction rows.",
            "Automated month end reconciliation, saving roughly a day each cycle.",
            "Presented findings to stakeholders who were not technical.",
            "Maintained documentation for every recurring report produced.",
            "Mentored two interns through their first analytics project.",
        ]
        for line, text in enumerate(prose):
            page.insert_text((60, 100 + line * 16), text, fontsize=9)
        if index < table_pages:
            top, left, right, row_h = 220, 60, 400, 18
            rows = [["Skill", "Level", "Years"], ["SQL", "Advanced", "4"],
                    ["Python", "Intermediate", "2"], ["Excel", "Advanced", "6"]]
            for r, row in enumerate(rows):
                y = top + r * row_h
                page.draw_line(fitz.Point(left, y), fitz.Point(right, y), width=0.6)
                for c, cell in enumerate(row):
                    page.insert_text((left + c * 110 + 4, y + 12), cell, fontsize=9)
            page.draw_line(fitz.Point(left, top + len(rows) * row_h), fitz.Point(right, top + len(rows) * row_h), width=0.6)
            for c in range(4):
                x = left + c * 110
                page.draw_line(fitz.Point(x, top), fitz.Point(x, top + len(rows) * row_h), width=0.6)
    doc.save(str(path))
    doc.close()


class TestSeverityScaling:
    """Deductions scale with how much of the document an issue affects.
    Fixed deductions allowed only 13 possible scores, so a table on one
    page of four scored the same as tables on every page."""

    def test_a_table_on_every_page_costs_more_than_one_table(self, tmp_path):
        one = tmp_path / "one.pdf"
        every = tmp_path / "every.pdf"
        _pdf_with_tables(one, total_pages=4, table_pages=1)
        _pdf_with_tables(every, total_pages=4, table_pages=4)

        light = check_parsability(str(one))
        heavy = check_parsability(str(every))
        assert light.has_tables and heavy.has_tables
        assert light.score > heavy.score
        assert heavy.severities["tables"] == 1.0

    def test_any_occurrence_still_costs_something(self, tmp_path):
        path = tmp_path / "one_of_eight.pdf"
        _pdf_with_tables(path, total_pages=8, table_pages=1)
        result = check_parsability(str(path))
        # a single table in a long document must not round away to nothing
        assert result.severities["tables"] >= 0.5
        assert result.score <= 90

    def test_scores_are_whole_numbers(self, tmp_path):
        path = tmp_path / "half.pdf"
        _pdf_with_tables(path, total_pages=2, table_pages=1)
        score = check_parsability(str(path)).score
        assert score == int(score)      # 25 * 0.5 = 12.5, so this would be 87.5
