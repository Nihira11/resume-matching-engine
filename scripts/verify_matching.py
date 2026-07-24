"""
End-to-end health check for the matching engine.

    python -m scripts.verify_matching --resume-id 1
    python -m scripts.verify_matching --resume-id 1 --refresh-embeddings

Runs five stages and stops at the first one that fails hard:

    1. environment   -- DATABASE_URL, importable dependencies
    2. schema        -- every table and column the engine writes to
    3. corpus        -- BM25 statistics file
    4. data          -- row counts, embedding coverage
    5. rankings      -- score one resume against every stored JD

Stage 5 is the one that matters. A pipeline can pass every structural
check and still be useless if it hands out the same score to every
posting, so the rankings are followed by diagnostics that look for
exactly that: no spread across JDs, a component that never produces a
signal, a semantic score that never moves. Those are silent failures --
nothing raises, the numbers just stop meaning anything.

Exit code is 0 if everything passes, 1 if any hard check fails. Warnings
do not affect the exit code.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.matching.config import BM25_CORPUS_STATS_PATH

OK = "  ok   "
WARN = " warn  "
FAIL = " FAIL  "

_failures: list[str] = []
_warnings: list[str] = []


def report(status: str, message: str) -> None:
    print(f"[{status}] {message}")
    if status == FAIL:
        _failures.append(message)
    elif status == WARN:
        _warnings.append(message)


# ---------------------------------------------------------------------
# 1. Environment
# ---------------------------------------------------------------------
def check_environment() -> bool:
    print("\n--- environment ---")
    import os

    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("DATABASE_URL"):
        report(FAIL, "DATABASE_URL not set – check .env")
        return False
    report(OK, "DATABASE_URL is set")

    for module, label in [
        ("psycopg2", "psycopg2"),
        ("numpy", "numpy"),
        ("spacy", "spaCy"),
        ("sentence_transformers", "sentence-transformers"),
    ]:
        try:
            __import__(module)
            report(OK, f"{label} importable")
        except ImportError:
            report(FAIL, f"{label} not installed")
    return not _failures


# ---------------------------------------------------------------------
# 2. Schema
# ---------------------------------------------------------------------
REQUIRED = {
    "resumes": ["resume_id", "cleaned_text", "embedding", "parsability_score"],
    "resume_entities": ["resume_id", "entity_type", "entity_value", "skill_id"],
    "job_descriptions": ["jd_id", "title", "cleaned_text", "embedding"],
    "jd_entities": ["jd_id", "entity_type", "entity_value", "skill_id", "is_required"],
    "skills_taxonomy": ["skill_id", "skill_name", "aliases"],
    "match_results": [
        "resume_id", "jd_id", "skill_overlap_score", "keyword_score",
        "semantic_score", "title_seniority_score", "experience_match_score",
        "final_blended_score", "verdict", "score_breakdown", "weights_used",
    ],
    "resume_chunks": ["resume_id", "chunk_index", "chunk_text", "embedding"],
    "jd_chunks": ["jd_id", "chunk_index", "chunk_text", "embedding"],
}


def check_schema() -> bool:
    print("\n--- schema ---")
    from src.utils.db import get_connection

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    actual: dict[str, set[str]] = {}
    for table, column in cur.fetchall():
        actual.setdefault(table, set()).add(column)
    cur.close()
    conn.close()

    healthy = True
    for table, columns in REQUIRED.items():
        if table not in actual:
            report(FAIL, f"table '{table}' missing – run the migration")
            healthy = False
            continue
        missing = [c for c in columns if c not in actual[table]]
        if missing:
            report(FAIL, f"{table} missing columns: {', '.join(missing)}")
            healthy = False
        else:
            report(OK, f"{table} ({len(columns)} columns checked)")
    return healthy


# ---------------------------------------------------------------------
# 3. BM25 corpus
# ---------------------------------------------------------------------
def check_corpus() -> None:
    print("\n--- bm25 corpus ---")
    path = Path(BM25_CORPUS_STATS_PATH)
    if not path.exists():
        report(WARN, f"{path} missing – run scripts.build_bm25_corpus. "
                     "The keyword component will be dropped until you do.")
        return

    import json
    stats = json.loads(path.read_text())
    n_docs, vocab = stats["n_docs"], len(stats["df"])
    report(OK, f"{n_docs} documents, {vocab} vocabulary terms, "
               f"avgdl {stats['avgdl']:.0f}")

    if n_docs < 100:
        report(WARN, f"only {n_docs} documents – IDF is unreliable below ~100. "
                     "Re-run without --limit.")
    if vocab < 2000:
        report(WARN, f"vocabulary of {vocab} looks small; check that text "
                     "extraction actually succeeded on the corpus")


# ---------------------------------------------------------------------
# 4. Data
# ---------------------------------------------------------------------
def check_data() -> dict:
    print("\n--- data ---")
    from src.utils.db import get_connection

    conn = get_connection()
    cur = conn.cursor()
    counts = {}
    for table in ["skills_taxonomy", "resumes", "resume_entities",
                  "job_descriptions", "jd_entities", "resume_chunks",
                  "jd_chunks", "match_results"]:
        cur.execute(f"SELECT count(*) FROM {table}")
        counts[table] = cur.fetchone()[0]

    # Skill entities with a NULL skill_id never made it into the taxonomy,
    # which means set-based overlap silently ignores them.
    cur.execute(
        "SELECT count(*) FROM jd_entities "
        "WHERE entity_type = 'skill' AND skill_id IS NULL"
    )
    orphan_jd_skills = cur.fetchone()[0]
    cur.close()
    conn.close()

    for table, count in counts.items():
        status = OK if count else WARN
        report(status, f"{table}: {count} rows")

    if counts["skills_taxonomy"] < 10000:
        report(WARN, "skills_taxonomy looks short – expected ~13,939")
    if not counts["resumes"]:
        report(FAIL, "no resumes ingested – run src.ingestion.pipeline first")
    if not counts["job_descriptions"]:
        report(FAIL, "no job descriptions – run src.ingestion.jd_pipeline first")
    if orphan_jd_skills:
        report(WARN, f"{orphan_jd_skills} JD skill entities have NULL skill_id "
                     "and are invisible to skill overlap")
    return counts


# ---------------------------------------------------------------------
# 5. Rankings + diagnostics
# ---------------------------------------------------------------------
def run_rankings(resume_id: int, limit: int, refresh_embeddings: bool) -> None:
    print("\n--- rankings ---")
    from src.matching.embeddings import embed_and_store
    from src.matching.match_pipeline import run_match
    from src.matching.profiles import load_jd_profile, load_resume_profile
    from src.utils.db import get_connection

    resume = load_resume_profile(resume_id)
    print(f"\nresume {resume_id}")
    print(f"  skills extracted : {len(resume.skill_ids)}")
    print(f"  titles extracted : {len(resume.titles)}")
    print(f"  years stated     : {resume.years_experience}")
    print(f"  parsability      : {resume.parsability_score}")
    if not resume.skill_ids:
        report(FAIL, "resume has zero linked skills – skill overlap cannot work")
    if not resume.cleaned_text.strip():
        report(FAIL, "resume cleaned_text is empty – extraction did not store text")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT jd_id FROM job_descriptions ORDER BY jd_id LIMIT %s", (limit,)
    )
    jd_ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if refresh_embeddings:
        print("\nembedding (first run downloads the model, ~90MB)...")
        embed_and_store("resume", resume_id, resume.cleaned_text)
        for jd_id in jd_ids:
            jd = load_jd_profile(jd_id)
            embed_and_store("jd", jd_id, jd.cleaned_text)

    results = []
    for jd_id in jd_ids:
        try:
            match = run_match(resume_id, jd_id, refresh_embeddings=False)
        except Exception as exc:  # noqa: BLE001
            report(FAIL, f"scoring jd {jd_id} raised {type(exc).__name__}: {exc}")
            continue
        jd = load_jd_profile(jd_id)
        results.append((match, jd))

    if not results:
        report(FAIL, "no JD scored successfully")
        return

    results.sort(key=lambda pair: pair[0].final_score, reverse=True)

    header = f"\n{'jd':>4}  {'final':>6}  {'skill':>6}  {'kw':>6}  {'title':>6}  {'exp':>6}  {'sem':>6}  {'verdict':<14} title"
    print(header)
    print("-" * (len(header) + 25))
    for match, jd in results:
        def col(key: str) -> str:
            value = match.component_scores.get(key)
            return f"{value * 100:6.1f}" if value is not None else "     –"
        print(
            f"{jd.jd_id:>4}  {match.final_score:6.1f}  {col('skill_overlap')}  "
            f"{col('keyword_bm25')}  {col('title_seniority')}  {col('experience')}  "
            f"{col('semantic')}  {match.verdict:<14} {jd.title[:40]}"
        )

    diagnose([m for m, _ in results])


def diagnose(matches: list) -> None:
    """Look for the silent failures: nothing raises, numbers stop meaning anything."""
    print("\n--- diagnostics ---")
    scores = [m.final_score for m in matches]

    if len(matches) < 3:
        report(WARN, "fewer than 3 JDs scored – ingest more to judge discrimination")
    else:
        spread = max(scores) - min(scores)
        if spread < 10:
            report(FAIL, f"final scores span only {spread:.1f} points across "
                         f"{len(matches)} JDs – the engine is not discriminating. "
                         "Check that JD skill extraction is actually varying.")
        else:
            report(OK, f"final scores span {spread:.1f} points "
                       f"({min(scores):.1f} to {max(scores):.1f})")

    for component in ["skill_overlap", "keyword_bm25", "title_seniority",
                      "experience", "semantic"]:
        values = [m.component_scores.get(component) for m in matches]
        present = [v for v in values if v is not None]

        if not present:
            hint = {
                "skill_overlap": "no JD has linked skill entities",
                "keyword_bm25": "corpus stats file missing",
                "title_seniority": "job_descriptions.title is empty",
                "experience": "no JD states a years requirement",
                "semantic": "no chunk embeddings stored – use --refresh-embeddings",
            }[component]
            report(WARN, f"{component}: never produced a signal ({hint})")
            continue

        if len(present) < len(values):
            report(OK, f"{component}: present on {len(present)}/{len(values)} "
                       "(dropped elsewhere, weights renormalised)")

        if len(present) >= 3 and max(present) - min(present) < 0.02:
            report(WARN, f"{component}: identical across all JDs "
                         f"(~{present[0]:.3f}) – contributing no information")

    semantic_raw = [
        m.breakdown.get("semantic", {}).get("raw_similarity") for m in matches
    ]
    semantic_raw = [v for v in semantic_raw if v is not None]
    if len(semantic_raw) >= 3:
        spread = max(semantic_raw) - min(semantic_raw)
        if spread < 0.05:
            report(WARN, f"raw cosine spans only {spread:.3f} – chunking may be "
                         "collapsing documents. Check resume_chunks row counts.")
        clipped = sum(1 for v in semantic_raw if v <= 0.25 or v >= 0.75)
        if clipped > len(semantic_raw) / 2:
            report(WARN, f"{clipped}/{len(semantic_raw)} semantic scores hit the "
                         "rescale bounds – adjust SEMANTIC_FLOOR/CEILING in config")


def main() -> None:
    parser = argparse.ArgumentParser(description="Health check the matching engine.")
    parser.add_argument("--resume-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=10,
                        help="max JDs to score against")
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument("--skip-rankings", action="store_true")
    args = parser.parse_args()

    if not check_environment():
        _summary()
        return
    if not check_schema():
        _summary()
        return
    check_corpus()
    check_data()

    if not args.skip_rankings and not _failures:
        run_rankings(args.resume_id, args.limit, args.refresh_embeddings)

    _summary()


def _summary() -> None:
    print("\n" + "=" * 60)
    if _failures:
        print(f"{len(_failures)} failure(s):")
        for item in _failures:
            print(f"  - {item}")
    if _warnings:
        print(f"{len(_warnings)} warning(s):")
        for item in _warnings:
            print(f"  - {item}")
    if not _failures and not _warnings:
        print("all checks passed")
    print("=" * 60)
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
    