"""
Matching CLI entrypoint. One resume + one JD in, one match_results row out.

    python -m src.matching.match_pipeline --resume-id 1 --jd-id 3
    python -m src.matching.match_pipeline --resume-id 1 --jd-id 3 --refresh-embeddings
    python -m src.matching.match_pipeline --resume-id 1 --jd-id 3 --json

Mirrors the shape of src/ingestion/pipeline.py deliberately, so both
entrypoints are driven the same way.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.matching.bm25_scorer import BM25Scorer
from src.matching.embeddings import embed_and_store, load_chunk_vectors
from src.matching.experience_match import score_experience
from src.matching.gap_analysis import analyse_gaps
from src.matching.profiles import (
    load_jd_profile,
    load_resume_profile,
    refresh_is_required,
)
from src.matching.score import build_match_score, persist
from src.matching.semantic import score_semantic
from src.matching.skill_overlap import score_skill_overlap
from src.matching.title_match import score_title_match


def run_match(
    resume_id: int,
    jd_id: int,
    refresh_embeddings: bool = False,
    refresh_requirements: bool = True,
    save: bool = True,
):
    if refresh_requirements:
        # jd_pipeline defaults every JD entity to is_required=TRUE. Re-derive
        # it from section headings before scoring, otherwise every wishlist
        # item is treated as a hard requirement.
        refresh_is_required(jd_id)

    resume = load_resume_profile(resume_id)
    jd = load_jd_profile(jd_id)

    overlap = score_skill_overlap(resume, jd)
    title = score_title_match(resume, jd)
    experience = score_experience(resume, jd)

    try:
        scorer = BM25Scorer.from_stats_file()
        keyword = scorer.score(resume.cleaned_text, jd.cleaned_text)
    except FileNotFoundError:
        print(
            "warning: BM25 corpus stats not found – run "
            "scripts/build_bm25_corpus.py. Scoring without the keyword "
            "component; its weight is redistributed across the rest.",
            file=sys.stderr,
        )
        from src.matching.bm25_scorer import BM25Result
        keyword = BM25Result(score=None)

    if refresh_embeddings:
        embed_and_store("resume", resume_id, resume.cleaned_text)
        embed_and_store("jd", jd_id, jd.cleaned_text)

    resume_vectors = load_chunk_vectors("resume", resume_id)
    jd_vectors = load_chunk_vectors("jd", jd_id)
    if resume_vectors.size == 0 or jd_vectors.size == 0:
        print(
            "warning: no chunk embeddings stored for this pair – re-run with "
            "--refresh-embeddings. Scoring without the semantic component.",
            file=sys.stderr,
        )
    semantic = score_semantic(resume_vectors, jd_vectors)

    gaps = analyse_gaps(
        resume, jd, overlap,
        resume_states_no_years=experience.resume_states_no_years,
    )

    match = build_match_score(
        resume, jd, overlap, keyword, title, experience, semantic, gaps
    )
    if save:
        persist(match)
    return match


def _print_human(match) -> None:
    print(f"\nresume {match.resume_id}  vs  jd {match.jd_id}")
    print(f"  final score : {match.final_score:.2f} / 100   ({match.verdict})")
    print("  components  :")
    for name, value in match.component_scores.items():
        weight = match.weights_used.get(name, 0.0)
        print(f"    {name:<16} {value * 100:6.2f}   (weight {weight:.3f})")
    if match.dropped_components:
        print(f"    dropped (no signal): {', '.join(match.dropped_components)}")

    skills = match.breakdown["skills"]
    print(f"\n  matched required : {', '.join(skills['matched_required']) or '–'}")
    print(f"  missing required : {', '.join(skills['missing_required']) or '–'}")

    if match.breakdown["suggestions"]:
        print("\n  suggestions:")
        for suggestion in match.breakdown["suggestions"]:
            print(f"    - {suggestion}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one resume against one JD.")
    parser.add_argument("--resume-id", type=int, required=True)
    parser.add_argument("--jd-id", type=int, required=True)
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument("--no-refresh-requirements", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    match = run_match(
        resume_id=args.resume_id,
        jd_id=args.jd_id,
        refresh_embeddings=args.refresh_embeddings,
        refresh_requirements=not args.no_refresh_requirements,
        save=not args.no_save,
    )

    if args.json:
        print(json.dumps(match.breakdown, indent=2, default=str))
    else:
        _print_human(match)


if __name__ == "__main__":
    main()