"""
ATS parsability scoring

Flags formatting patterns that cause real ATS engines (Workday, Greenhouse,
Taleo, etc.) to drop or scramble resume content – independent of what the
resume actually says. Deliberately kept separate from the NLP/skill
extraction pipeline: a resume can have perfect keyword coverage and still
fail to parse because it's a two-column, table-based, or image-heavy
template

Score starts at 100, deducts per issue found. The deduction weights are
opinionated placeholders, not a cited industry standard – documented here
so they're easy to recalibrate once Phase 4 validates against real
postings/outcomes
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

DEDUCTIONS = {
    "tables": 25,
    "multi_column": 20,
    "images": 10,
    "headers_footers": 15,
}


@dataclass
class ParsabilityResult:
    has_tables: bool = False
    has_multi_column: bool = False
    has_images: bool = False
    has_headers_footers: bool = False
    score: float = 100.0
    flags: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "has_tables": self.has_tables,
            "has_multi_column": self.has_multi_column,
            "has_images": self.has_images,
            "has_headers_footers": self.has_headers_footers,
            "parsability_score": self.score,
            "parsability_flags": self.flags,
        }


def _score_from_flags(result: ParsabilityResult) -> None:
    score = 100.0
    if result.has_tables:
        score -= DEDUCTIONS["tables"]
    if result.has_multi_column:
        score -= DEDUCTIONS["multi_column"]
    if result.has_images:
        score -= DEDUCTIONS["images"]
    if result.has_headers_footers:
        score -= DEDUCTIONS["headers_footers"]
    result.score = max(0.0, score)


# PDF

def check_pdf(path: str) -> ParsabilityResult:
    result = ParsabilityResult()
    # track which issue types have already been flagged so a 5-page resume
    # doesn't produce 5 copies of the same message – one page tripping a
    # check is enough to know the document has that problem
    seen_flag_types = set()

    def add_flag(flag_type: str, message: str) -> None:
        if flag_type not in seen_flag_types:
            seen_flag_types.add(flag_type)
            result.flags.append(message)

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if _has_table(page):
                result.has_tables = True
                add_flag(
                    "tables",
                    "Detected table structure – many ATS parsers read tables "
                    "left-to-right/top-to-bottom and scramble content order.",
                )

            if page.images:
                result.has_images = True
                add_flag(
                    "images",
                    "Detected embedded image – text inside images (e.g. a "
                    "skills icon graphic) is invisible to ATS text extraction.",
                )

            words = page.extract_words()
            if _looks_multi_column(words, page.width):
                result.has_multi_column = True
                add_flag(
                    "multi_column",
                    "Detected multi-column layout – ATS parsers typically read "
                    "left-to-right across the full page width, merging column "
                    "content out of order.",
                )

        if _has_repeated_margin_text(pdf.pages):
            result.has_headers_footers = True
            add_flag(
                "headers_footers",
                "Detected repeated header/footer text across pages – some "
                "ATS parsers ignore running headers/footers entirely, others "
                "duplicate them into every parsed section.",
            )

    _score_from_flags(result)
    return result


# A table has to be a *localised* grid to count. pdfplumber's text
# strategy infers structure from whitespace alignment, and on an ordinary
# resume the whole page qualifies -- every line becomes a row and every
# gap a column boundary. Measured on 25 random real resumes, the original
# "any 2x2 grid" rule fired on 25 of 25, so every resume scored exactly
# 75/100 and the check carried no information at all. Requiring the grid
# to occupy at most a third of the page height (plus >=3 rows and >=2
# columns) flags 8 of the same 25, and still flags the synthetic
# table fixture while leaving the plain one clean.
MAX_TABLE_HEIGHT_FRACTION = 0.35
MIN_TABLE_ROWS = 3


def _has_table(page) -> bool:
    """Ruled table, or a borderless grid confined to part of the page.

    Real resume templates mostly use borderless layout tables, which the
    default line-based strategy misses entirely (0 of 25 real resumes),
    so both strategies are used: lines catch genuine bordered tables,
    text-alignment catches borderless ones, bounded by size.
    """
    for table in page.find_tables():
        if len(table.rows) >= 2 and len(table.columns) >= 2:
            return True

    for table in page.find_tables(
        table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
    ):
        _, top, _, bottom = table.bbox
        height_fraction = (bottom - top) / page.height if page.height else 1.0
        if (
            height_fraction <= MAX_TABLE_HEIGHT_FRACTION
            and len(table.rows) >= MIN_TABLE_ROWS
            and len(table.columns) >= 2
        ):
            return True
    return False


def _find_gutter(words: list, page_width: float):
    """Find the widest empty vertical band within the middle portion of the
    page (25%-75% of width) – that's the column gutter, wherever the
    template actually places it (a narrow sidebar column split is common,
    not just an even 50/50 split). Returns (gutter_start, gutter_end) or
    None if no meaningful gap exists"""
    search_lo, search_hi = page_width * 0.25, page_width * 0.75

    spans = sorted((w["x0"], w["x1"]) for w in words)
    merged = []
    for x0, x1 in spans:
        if merged and x0 <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], x1))
        else:
            merged.append((x0, x1))

    best_gap = (0, None, None)
    for i in range(len(merged) - 1):
        gap_start, gap_end = merged[i][1], merged[i + 1][0]
        if gap_end < search_lo or gap_start > search_hi:
            continue
        gap_start = max(gap_start, search_lo)
        gap_end = min(gap_end, search_hi)
        gap_width = gap_end - gap_start
        if gap_width > best_gap[0]:
            best_gap = (gap_width, gap_start, gap_end)

    min_gap_width = page_width * 0.02
    if best_gap[1] is None or best_gap[0] < min_gap_width:
        return None
    return best_gap[1], best_gap[2]


def _looks_multi_column(words: list, page_width: float) -> bool:
    """Group words into lines, then classify each line as either confined
    to one column or crossing the gutter. Normal single-column text has
    almost every line crossing the gutter; genuine multi-column layouts
    have almost no line crossing it"""
    if len(words) < 20:
        return False

    lines: dict = {}
    for w in words:
        bucket = round(w["top"] / 2) * 2
        lines.setdefault(bucket, []).append(w)

    gutter = _find_gutter(words, page_width)
    if gutter is None:
        return False
    gutter_start, gutter_end = gutter

    left_confined = right_confined = crossing = 0
    for line_words in lines.values():
        x0 = min(w["x0"] for w in line_words)
        x1 = max(w["x1"] for w in line_words)
        if x1 <= gutter_start:
            left_confined += 1
        elif x0 >= gutter_end:
            right_confined += 1
        elif x0 < gutter_start and x1 > gutter_end:
            crossing += 1

    total_lines = len(lines)
    if total_lines < 6:
        return False

    crossing_ratio = crossing / total_lines
    confined_ratio = (left_confined + right_confined) / total_lines

    return (
        crossing_ratio < 0.2
        and confined_ratio > 0.6
        and left_confined >= 3
        and right_confined >= 3
    )


def _has_repeated_margin_text(pages) -> bool:
    if len(pages) < 2:
        return False

    top_lines, bottom_lines = [], []
    for page in pages:
        words = page.extract_words()
        if not words:
            continue
        top_band = page.height * 0.08
        bottom_band = page.height * 0.92
        top = " ".join(w["text"] for w in words if w["top"] <= top_band)
        bottom = " ".join(w["text"] for w in words if w["top"] >= bottom_band)
        top_lines.append(top.strip())
        bottom_lines.append(bottom.strip())

    def repeated(lines):
        non_empty = [l for l in lines if l]
        if len(non_empty) < 2:
            return False
        return len(set(non_empty)) < len(non_empty)

    return repeated(top_lines) or repeated(bottom_lines)


# DOCX

def check_docx(path: str) -> ParsabilityResult:
    result = ParsabilityResult()
    doc = Document(path)

    if doc.tables:
        result.has_tables = True
        result.flags.append(
            "Detected Word table structure – ATS parsers reading .docx often "
            "flatten or reorder table content."
        )

    if doc.inline_shapes:
        result.has_images = True
        result.flags.append(
            "Detected embedded image – text inside images is invisible to "
            "ATS text extraction."
        )

    for section in doc.sections:
        header_text = section.header.paragraphs[0].text.strip() if section.header.paragraphs else ""
        footer_text = section.footer.paragraphs[0].text.strip() if section.footer.paragraphs else ""
        if header_text or footer_text:
            result.has_headers_footers = True
            result.flags.append(
                "Detected a Word header/footer – some ATS parsers skip these "
                "entirely, so contact info placed there may not be captured."
            )
            break

    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for section in doc.sections:
        try:
            cols = section._sectPr.xpath("./w:cols")
            if cols and cols[0].get(f"{ns}num") not in (None, "1"):
                result.has_multi_column = True
                result.flags.append(
                    "Detected multi-column section layout – ATS parsers "
                    "typically read left-to-right across the full page width."
                )
        except Exception:
            pass

    _score_from_flags(result)
    return result


def check_parsability(path: str) -> ParsabilityResult:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return check_pdf(path)
    elif ext == ".docx":
        return check_docx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
