"""
Spot-check tool for the Skills metric from validate_against_kaggle_ner.py

The aggregate Skills precision/coverage numbers conflate two different
things: whether the skill matcher found real, correct ESCO terms, and
whether those terms happened to fall inside the specific text span an
annotator boxed as "Skills". A skill mentioned inside a job description
("developed reports using SQL...") is a genuine, correct match – but it
scores as a false positive under the overlap metric because it's outside
the labeled Skills block

This script sidesteps that confusion by just showing you both things
side by side for a handful of real resumes, so you can judge with your
own eyes whether the matches are actually good

Usage:
    python -m tests.spot_check_skills data/raw/kaggle_resume_entities/resume_entities.json 5
    (second argument is how many resumes to sample, default 5)
"""
from __future__ import annotations

import sys

from src.nlp.extract_entities import extract_all
from tests.validate_against_kaggle_ner import gt_spans_for_label, load_records


def main(path: str, n: int = 5) -> None:
    records = load_records(path)
    sample = records[:n]

    for i, record in enumerate(sample, 1):
        content = record.get("content", "")
        if not content.strip():
            continue

        name = None
        for ann in record.get("annotation", []) or []:
            if "Name" in (ann.get("label") or []):
                pts = ann.get("points", [])
                if pts:
                    name = pts[0]["text"].strip()
                break

        print("=" * 80)
        print(f"Record {i}{f' – {name}' if name else ''}")
        print("=" * 80)

        extracted = extract_all(content)
        our_skills = sorted({s.matched_text for s in extracted.skills})

        gt_spans = gt_spans_for_label(record, "Skills")
        gt_texts = [content[s:e].strip() for s, e in gt_spans]

        print(f"\nOur extracted skills ({len(our_skills)} unique terms):")
        print(", ".join(our_skills) if our_skills else "  (none)")

        print(f"\nGround-truth 'Skills' block(s) ({len(gt_texts)}):")
        for t in gt_texts:
            print(f"  ---\n  {t}\n")

        # quick eyeball check: how many of our terms literally appear as a
        # substring of one of the ground-truth blocks (a stricter check
        # than the overlap-span scoring, but easy to read at a glance)
        gt_blob = " ".join(gt_texts).lower()
        in_block = [s for s in our_skills if s.lower() in gt_blob]
        outside_block = [s for s in our_skills if s.lower() not in gt_blob]
        print(f"Of our extracted skills: {len(in_block)} appear literally inside "
              f"the labeled Skills block, {len(outside_block)} were found elsewhere "
              f"in the resume (job descriptions, summaries, etc.)")
        if outside_block:
            print(f"  Found elsewhere: {', '.join(outside_block)}")
        print()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/kaggle_resume_entities/resume_entities.json"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    main(path, n)
