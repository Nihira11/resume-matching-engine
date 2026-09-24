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
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

DEDUCTIONS = {
    "tables": 25,
    "multi_column": 20,
    "images": 10,
    "headers_footers": 15,
}


# How much of the document each issue affects, rather than merely whether
# it occurs. A skills table on one page of three is a smaller problem than
# tables on every page, and the old fixed deductions could not say so:
# the score could only ever take 13 values (100, 90, 85, 80, 75 ...), so
# two very different documents scored identically.
#
# Severity is the affected fraction, floored: any occurrence still costs
# at least half the deduction, because one mangled section can be the one
# holding your experience.
MIN_SEVERITY = 0.5
# images are counted, not paged: this many or more is "throughout"
IMAGES_FOR_FULL_SEVERITY = 3


@dataclass
class ParsabilityResult:
    has_tables: bool = False
    has_multi_column: bool = False
    has_images: bool = False
    has_headers_footers: bool = False
    score: float = 100.0
    flags: list = field(default_factory=list)
    # severity in [0, 1] per issue; absent means the issue did not occur
    severities: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "has_tables": self.has_tables,
            "has_multi_column": self.has_multi_column,
            "has_images": self.has_images,
            "has_headers_footers": self.has_headers_footers,
            "parsability_score": self.score,
            "parsability_flags": self.flags,
        }


def _severity(affected: float, total: float) -> float:
    """Affected fraction, floored at MIN_SEVERITY. 0 when nothing hit."""
    if affected <= 0 or total <= 0:
        return 0.0
    return max(MIN_SEVERITY, min(1.0, affected / total))


def _score_from_flags(result: ParsabilityResult) -> None:
    score = 100.0
    for issue, deduction in DEDUCTIONS.items():
        severity = result.severities.get(issue, 0.0)
        if severity:
            score -= deduction * severity
    # a whole number: the inputs are page counts and detector thresholds,
    # and decimal places would imply precision the measurement lacks
    result.score = float(max(0.0, round(score)))


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
        pages_with_tables = pages_multi_column = 0
        image_count = 0

        for page in pdf.pages:
            if _has_table(page):
                pages_with_tables += 1
                result.has_tables = True
                add_flag(
                    "tables",
                    "Detected table structure – many ATS parsers read tables "
                    "left-to-right/top-to-bottom and scramble content order.",
                )

            if page.images:
                image_count += len(page.images)
                result.has_images = True
                add_flag(
                    "images",
                    "Detected embedded image – text inside images (e.g. a "
                    "skills icon graphic) is invisible to ATS text extraction.",
                )

            words = page.extract_words()
            if _looks_multi_column(words, page.width):
                pages_multi_column += 1
                result.has_multi_column = True
                add_flag(
                    "multi_column",
                    "Detected multi-column layout – ATS parsers typically read "
                    "left-to-right across the full page width, merging column "
                    "content out of order.",
                )

        page_count = max(1, len(pdf.pages))
        result.severities["tables"] = _severity(pages_with_tables, page_count)
        result.severities["multi_column"] = _severity(pages_multi_column, page_count)
        result.severities["images"] = _severity(
            min(image_count, IMAGES_FOR_FULL_SEVERITY), IMAGES_FOR_FULL_SEVERITY
        )

        if _has_repeated_margin_text(pdf.pages):
            # a running header sits on every page by definition
            result.severities["headers_footers"] = 1.0
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
# A real table's column boundaries fall between words. Whitespace that
# merely lines up across wrapped prose does not: on a resume whose
# project bullets were flagged, the inferred columns cut straight through
# words -- "Resu|me Matching", "In Progr|ess", "Pyth|on" -- and 29% of the
# words in the block were sliced by an edge, against 0% for a genuine
# table. Anything above this is alignment coincidence, not structure.
MAX_SLICED_WORD_FRACTION = 0.05


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
            and _columns_respect_words(page, table)
        ):
            return True
    return False


def _columns_respect_words(page, table) -> bool:
    """True when the grid's column edges fall between words, not through them."""
    x0, top, x1, bottom = table.bbox
    words = [
        w for w in page.extract_words()
        if w["top"] >= top - 2 and w["bottom"] <= bottom + 2
    ]
    if not words:
        return False

    edges = sorted(
        {column.bbox[0] for column in table.columns}
        | {column.bbox[2] for column in table.columns}
    )[1:-1]  # interior boundaries only; the outer two are the table's own edges
    if not edges:
        return False

    sliced = sum(
        1
        for edge in edges
        for word in words
        if word["x0"] < edge - 0.5 and word["x1"] > edge + 0.5
    )
    return sliced / len(words) <= MAX_SLICED_WORD_FRACTION


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
    """A running header or footer is one *line* that recurs across pages.

    The band is compared line by line, not as a single joined string: the
    top 8% of a page catches the running header *and* whatever heading
    happens to sit near the top, so joining them made two pages with the
    same header look different ("...Vitae JORDAN BLAKE" vs "...Vitae
    CERTIFICATIONS") and the check never fired.

    Digits are stripped before comparing, because the most common footer
    of all is "Page 1 of 3", which is never literally identical twice.
    """
    if len(pages) < 2:
        return False

    def margin_lines(page) -> set[str]:
        words = page.extract_words()
        if not words:
            return set()
        top_band = page.height * 0.08
        bottom_band = page.height * 0.92

        rows: dict[float, list[str]] = {}
        for word in words:
            if word["top"] <= top_band or word["top"] >= bottom_band:
                # group by baseline; PDFs rarely place a line's words at
                # exactly the same y
                key = round(word["top"] / 3)
                rows.setdefault(key, []).append(word["text"])

        lines = set()
        for parts in rows.values():
            text = re.sub(r"\d+", "", " ".join(parts))
            text = re.sub(r"\s+", " ", text).strip().lower()
            # a bare "page" or a stray bullet is not evidence of anything
            if len(text) >= 8:
                lines.add(text)
        return lines

    seen: dict[str, int] = {}
    for page in pages:
        for line in margin_lines(page):
            seen[line] = seen.get(line, 0) + 1
            if seen[line] >= 2:
                return True
    return False


# DOCX

def check_docx(path: str) -> ParsabilityResult:
    result = ParsabilityResult()
    doc = Document(path)

    if doc.tables:
        result.severities["tables"] = _severity(
            min(len(doc.tables), IMAGES_FOR_FULL_SEVERITY), IMAGES_FOR_FULL_SEVERITY
        )
        result.has_tables = True
        result.flags.append(
            "Detected Word table structure – ATS parsers reading .docx often "
            "flatten or reorder table content."
        )

    if doc.inline_shapes:
        result.severities["images"] = _severity(
            min(len(doc.inline_shapes), IMAGES_FOR_FULL_SEVERITY), IMAGES_FOR_FULL_SEVERITY
        )
        result.has_images = True
        result.flags.append(
            "Detected embedded image – text inside images is invisible to "
            "ATS text extraction."
        )

    for section in doc.sections:
        header_text = section.header.paragraphs[0].text.strip() if section.header.paragraphs else ""
        footer_text = section.footer.paragraphs[0].text.strip() if section.footer.paragraphs else ""
        if header_text or footer_text:
            result.severities["headers_footers"] = 1.0
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
