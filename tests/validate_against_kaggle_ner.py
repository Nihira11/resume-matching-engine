"""
Validates entity extraction (src.nlp.extract_entities.extract_all)
against the Kaggle "Resume Entities for NER" ground truth dataset

Ground truth format (confirmed against a real sample of the file):
JSONL – one JSON object per line, each shaped like:
    {
      "content": "<full resume text>",
      "annotation": [
        {"label": ["Skills"], "points": [{"start": 1295, "end": 1621, "text": "..."}]},
        {"label": ["Designation"], "points": [{"start": 13, "end": 45, "text": "..."}]},
        ...
      ],
      "extras": null
    }

Observed ground-truth labels: Skills, Designation, Degree, College Name,
Companies worked at, Graduation Year, Email Address, Location, Name,
Years of Experience

Currently it only extracts a subset of these – Skills, titles (-> Designation),
education (-> Degree), years_experience (-> Years of Experience). Name,
Email, Location, College Name, Companies worked at, Graduation Year are out
of scope for now and not scored here

WHY OVERLAP SCORING, NOT EXACT MATCH:
Ground truth spans and our extracted spans operate at different granularity
by design, not by accident:
  - Designation: ground truth is a short title string ("Application
    Development Associate"); our heuristic grabs the whole line it's found
    on. Exact match would always fail even when we found the right line
  - Skills: ground truth sometimes annotates one whole skills paragraph as
    a single span; we extract individual ESCO-taxonomy terms within it
  - Degree: mostly comparable in size, exact match would mostly work here,
    but keeping the same overlap metric for consistency
So we score two overlap-based numbers instead of exact-match precision/recall:
  - precision: fraction of OUR spans that overlap at least one ground-truth
    span for that label (did we find something real, even if we grabbed
    more/less text around it?)
  - coverage: fraction of ground-truth CHARACTERS that fall within at least
    one of our extracted spans (did we find the substance of what the
    annotator marked, even if our span boundaries differ?)

Years of Experience has no comparable output from us (extract_years_experience
returns bare ints, not text spans), so it's reported as a hit/miss count
instead: for each record with a ground-truth Years-of-Experience span, did
our years_experience list contain an integer that plausibly matches the
annotated text?

Usage:
    python -m tests.validate_against_kaggle_ner data/raw/kaggle_resume_entities/resume_entities.json
    python -m tests.validate_against_kaggle_ner <path> 20   # limit to first 20 records
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass

from src.nlp.extract_entities import extract_all


@dataclass
class LabelStats:
    our_spans_total: int = 0
    our_spans_matched: int = 0
    gt_chars_total: int = 0
    gt_chars_covered: int = 0

    def precision(self):
        return self.our_spans_matched / self.our_spans_total if self.our_spans_total else None

    def coverage(self):
        return self.gt_chars_covered / self.gt_chars_total if self.gt_chars_total else None


def load_records(path: str) -> list[dict]:
    """Handles both JSONL (one object per line) and a single JSON array,
    since Kaggle exports of this dataset have appeared in both forms."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    stripped = text.strip()
    if stripped.startswith("["):
        return json.loads(stripped)

    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def gt_spans_for_label(record: dict, label: str) -> list[tuple[int, int]]:
    spans = []
    for ann in record.get("annotation", []) or []:
        if label in (ann.get("label") or []):
            for p in ann.get("points", []) or []:
                if "start" in p and "end" in p:
                    spans.append((p["start"], p["end"]))
    return spans


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def score_label(our_spans: list[tuple[int, int]], gt_spans: list[tuple[int, int]], stats: LabelStats) -> None:
    stats.our_spans_total += len(our_spans)
    for os_, oe in our_spans:
        if any(_overlaps(os_, oe, gs, ge) for gs, ge in gt_spans):
            stats.our_spans_matched += 1

    for gs, ge in gt_spans:
        span_len = ge - gs
        stats.gt_chars_total += span_len
        covered = 0
        for os_, oe in our_spans:
            if _overlaps(os_, oe, gs, ge):
                covered += min(oe, ge) - max(os_, gs)
        stats.gt_chars_covered += min(covered, span_len)


def _find_spans(content: str, strings: list[str]) -> list[tuple[int, int]]:
    """Our title/education extractors return matched strings, not offsets –
    recover offsets by locating each string in the original content. Safe
    here since these are short, fairly distinctive substrings; a repeated
    substring only costs us finding the first occurrence, which is a minor
    undercount, not a false positive."""
    spans = []
    for s in strings:
        idx = content.find(s)
        if idx != -1:
            spans.append((idx, idx + len(s)))
    return spans


_YEARS_NUM_PATTERN = re.compile(r"(\d{1,2}(?:\.\d)?)")


def years_hit(gt_text: str, our_years: list[int]) -> bool:
    """Ground truth years-of-experience text is free-form ('6.8 years',
    '15 Months', '3.2-years'). Rather than re-deriving an exact number,
    check whether any digit token in the ground truth text is within 1 of
    something we extracted – close enough to confirm we're in the right
    neighborhood. Ground truth also includes months and 'Yrs', which the
    extractor doesn't read, so exact-match would understate it."""
    if not our_years:
        return False
    gt_numbers = [float(n) for n in _YEARS_NUM_PATTERN.findall(gt_text)]
    return any(abs(gt_n - our_n) <= 1 for gt_n in gt_numbers for our_n in our_years)


def main(path: str, limit: int | None = None) -> None:
    records = load_records(path)
    if limit:
        records = records[:limit]

    stats = {
        "Skills": LabelStats(),
        "Designation": LabelStats(),
        "Degree": LabelStats(),
    }
    years_total = 0
    years_hits = 0

    for record in records:
        content = record.get("content", "")
        if not content.strip():
            continue

        extracted = extract_all(content)

        our_skill_spans = [(s.start_char, s.end_char) for s in extracted.skills]
        our_title_spans = _find_spans(content, extracted.titles)
        our_edu_spans = _find_spans(content, extracted.education)

        score_label(our_skill_spans, gt_spans_for_label(record, "Skills"), stats["Skills"])
        score_label(our_title_spans, gt_spans_for_label(record, "Designation"), stats["Designation"])
        score_label(our_edu_spans, gt_spans_for_label(record, "Degree"), stats["Degree"])

        for gs, ge in gt_spans_for_label(record, "Years of Experience"):
            years_total += 1
            if years_hit(content[gs:ge], extracted.years_experience):
                years_hits += 1

    print(f"Validated against {len(records)} records\n")
    for label, s in stats.items():
        p, c = s.precision(), s.coverage()
        print(f"{label}:")
        print(f"  our extracted spans: {s.our_spans_total}")
        print(f"  precision (our spans that overlap a ground-truth span): "
              f"{'n/a' if p is None else f'{p:.1%}'}")
        print(f"  coverage (ground-truth chars we captured): "
              f"{'n/a' if c is None else f'{c:.1%}'}")
        print()

    print("Years of Experience:")
    print(f"  ground-truth mentions: {years_total}")
    print(f"  matched within ±1 year of something we extracted: "
          f"{'n/a' if years_total == 0 else f'{years_hits}/{years_total} ({years_hits/years_total:.1%})'}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/kaggle_resume_entities/resume_entities.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(path, limit)