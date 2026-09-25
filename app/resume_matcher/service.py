"""
Everything the UI needs from the pipeline, as plain functions.

Kept out of state.py on purpose: Reflex state classes are awkward to test
(they need an app context), while these are ordinary functions over the
same code paths the CLI uses. tests/test_ui_service.py covers the
formatting helpers without a database.

Every function here is synchronous and blocking -- spaCy, the embedding
model and psycopg2 all are. The state layer runs them in a worker thread
so the websocket event loop keeps serving.
"""
from __future__ import annotations

import base64

from src.ingestion.jd_pipeline import run as ingest_jd
from src.ingestion.pipeline import run as ingest_resume
from src.matching.config import (
    CALIBRATION_SET_SIZE,
    DATA_ROOT,
    VERDICT_BORDERLINE_THRESHOLD,
    VERDICT_PASS_THRESHOLD,
)
from src.matching.embeddings import load_chunk_vectors
from src.matching.match_pipeline import PreloadedDocuments, run_match
from src.matching.score import fit_band, percentile_against_calibration
from src.matching.profiles import load_jd_profile, load_resume_profile, refresh_is_required
from src.utils.db import connection, get_connection

COMPONENT_LABELS = {
    "skill_overlap": "Skill overlap",
    "keyword_bm25": "Keyword (BM25)",
    "title_seniority": "Title & seniority",
    "experience": "Experience",
    "semantic": "Semantic similarity",
}

COMPONENT_HELP = {
    "skill_overlap": "Taxonomy skills in the posting that also appear on the resume. Weighted highest — it is what a real ATS keyword screen does.",
    "keyword_bm25": "Free-text term overlap, IDF-weighted against ~2.4k resumes. Catches terms the taxonomy does not cover.",
    "title_seniority": "Role family and seniority distance between the resume's titles and the posting's title.",
    "experience": "Years stated on the resume against the minimum advertised. Dropped when the posting states no minimum.",
    "semantic": "Sentence-transformer similarity, pooled per posting section. A secondary signal by design.",
}

VERDICT_LABELS = {
    "likely_pass": "Likely pass",
    "borderline": "Borderline",
    "likely_reject": "Likely reject",
}

VERDICT_COLORS = {"likely_pass": "grass", "borderline": "amber", "likely_reject": "tomato"}

# Shown under every verdict. Calibrated 24 Sep 2026 on 40 real postings
# labelled by the candidate; the thresholds separate that set cleanly but
# come from one resume and one labeller, so the wording says what the
# score is comparable to rather than implying a hiring decision.
VERDICT_CAVEAT = (
    f"Thresholds ({VERDICT_PASS_THRESHOLD:.0f} pass / {VERDICT_BORDERLINE_THRESHOLD:.0f} "
    "borderline) were calibrated on 40 real postings labelled by one candidate: no "
    "posting they called a good fit was rejected, and none they ruled out passed. "
    "Scores compare postings against each other, not against an external standard."
)


# Dropdown labels are what the user reads, so they are names and dates,
# not primary keys. Postgres never reuses a deleted id, so raw ids show up
# as gaps ("#3, #4, #5" with no #1) that look like missing data but are
# just rows deleted during earlier testing. The id stays in the payload
# for the handlers; only the label is human.
def _unique_labels(rows: list[dict]) -> list[dict]:
    """Disambiguate identical labels -- rx.select keys on the label."""
    seen: dict[str, int] = {}
    for row in rows:
        seen[row["label"]] = seen.get(row["label"], 0) + 1
    used: dict[str, int] = {}
    for row in rows:
        if seen[row["label"]] > 1:
            used[row["label"]] = used.get(row["label"], 0) + 1
            row["label"] = f"{row['label']} ({used[row['label']]})"
    return rows


def list_resumes(session_token: str) -> list[dict]:
    """Only this browser session's resumes.

    Resumes carry names, phone numbers and addresses. A dropdown listing
    every resume ever uploaded is the reason this app could not be
    deployed; scoping by the Reflex client token is what makes it
    possible. A missing token lists nothing rather than everything --
    failing closed is the only safe direction here.
    """
    if not session_token:
        return []
    rows = _query(
        "SELECT resume_id, file_name, parsability_score, uploaded_at "
        "FROM resumes WHERE session_token = %s "
        "ORDER BY uploaded_at DESC, resume_id DESC",
        (session_token,),
    )
    return _unique_labels(
        [
            {
                "id": r[0],
                "label": f"{r[1]} · added {r[3]:%d %b %Y}" if r[3] else str(r[1]),
                "file_name": r[1],
                "parsability": float(r[2]) if r[2] is not None else 0.0,
            }
            for r in rows
        ]
    )


def list_jds(session_token: str) -> list[dict]:
    if not session_token:
        return []
    rows = _query(
        "SELECT jd_id, title, company FROM job_descriptions "
        "WHERE session_token = %s ORDER BY jd_id DESC",
        (session_token,),
    )
    return _unique_labels(
        [
            {
                "id": r[0],
                "label": (r[1] or "Untitled posting")[:70] + (f" — {r[2]}" if r[2] else ""),
                "title": r[1] or "Untitled posting",
                "company": r[2] or "",
            }
            for r in rows
        ]
    )


def add_resume(file_path: str, session_token: str) -> int:
    resume_id = ingest_resume(file_path, session_token=session_token)
    clear_caches()
    return resume_id


def add_jd(text: str, session_token: str, title: str = "", company: str = "",
           source: str = "pasted_in_ui", source_url: str | None = None) -> int:
    title = title.strip() or _first_line(text)
    jd_id = ingest_jd(
        text, title=title, company=company.strip() or None,
        source=source, source_url=source_url, session_token=session_token,
    )
    clear_caches()
    return jd_id


def ensure_embeddings(kind: str, doc_id: int) -> None:
    """Embed a document only if pgvector has no chunks for it yet.

    run_match(refresh_embeddings=True) re-embeds unconditionally, which is
    wasted work on a re-score and 13x wasted work on the leaderboard. The
    chunks are already persisted; recompute only when they are missing.
    Re-ingesting a resume writes a new row with a new id, so a stale cache
    is not a case that arises here.
    """
    table = "resume_chunks" if kind == "resume" else "jd_chunks"
    id_column = "resume_id" if kind == "resume" else "jd_id"
    rows = _query(f"SELECT count(*) FROM {table} WHERE {id_column} = %s", (doc_id,))
    if rows and rows[0][0]:
        return

    from src.matching.embeddings import embed_and_store

    text_rows = _query(
        "SELECT COALESCE(cleaned_text, raw_text) FROM "
        + ("resumes WHERE resume_id = %s" if kind == "resume" else "job_descriptions WHERE jd_id = %s"),
        (doc_id,),
    )
    if text_rows and text_rows[0][0]:
        embed_and_store(kind, doc_id, text_rows[0][0])


# Postings whose required-vs-preferred flags have already been re-derived
# in this process. refresh_is_required rewrites them from the JD text,
# which never changes once stored, so doing it per score is ~2s of
# round trips for an identical result.
_REQUIREMENTS_REFRESHED: set[int] = set()

# Profiles and chunk vectors for documents already scored in this process.
# Each is several round trips to a remote database at ~550ms apiece, and
# the UI scores one resume against posting after posting, re-reading
# identical rows every time. Cleared whenever a document is ingested or
# re-extracted, which is the only way stored rows change while the app is
# running.
_resume_cache: dict[int, tuple] = {}
_jd_cache: dict[int, tuple] = {}


def clear_caches() -> None:
    _resume_cache.clear()
    _jd_cache.clear()
    _REQUIREMENTS_REFRESHED.clear()


def _resume_docs(resume_id: int) -> tuple:
    if resume_id not in _resume_cache:
        ensure_embeddings("resume", resume_id)
        _resume_cache[resume_id] = (
            load_resume_profile(resume_id),
            load_chunk_vectors("resume", resume_id),
        )
    return _resume_cache[resume_id]


def _jd_docs(jd_id: int) -> tuple:
    if jd_id not in _jd_cache:
        ensure_embeddings("jd", jd_id)
        if jd_id not in _REQUIREMENTS_REFRESHED:
            # rewrites is_required from the JD text, which never changes
            # once stored -- once per posting per process is enough
            refresh_is_required(jd_id)
            _REQUIREMENTS_REFRESHED.add(jd_id)
        _jd_cache[jd_id] = (load_jd_profile(jd_id), load_chunk_vectors("jd", jd_id))
    return _jd_cache[jd_id]


def _match(resume_id: int, jd_id: int):
    resume, resume_vectors = _resume_docs(resume_id)
    jd, jd_vectors = _jd_docs(jd_id)
    return run_match(
        resume_id,
        jd_id,
        refresh_embeddings=False,
        refresh_requirements=False,
        preloaded=PreloadedDocuments(
            resume=resume, jd=jd,
            resume_vectors=resume_vectors, jd_vectors=jd_vectors,
        ),
    )


def score_pair(resume_id: int, jd_id: int) -> dict:
    return to_view(_match(resume_id, jd_id))


def board_row(resume_id: int, jd: dict) -> dict:
    """One leaderboard row. Called per posting so the UI can fill the
    table as results land instead of blocking on the whole set -- the
    database is remote and every match is several round trips."""
    match = _match(resume_id, jd["id"])
    return {
        "jd_id": jd["id"],
        "title": jd["title"],
        "company": jd["company"],
        "score": match.final_score,
        "verdict": VERDICT_LABELS.get(match.verdict, match.verdict),
        "verdict_color": VERDICT_COLORS.get(match.verdict, "gray"),
        "matched": len(match.breakdown["skills"]["matched_required"]),
        "missing": len(match.breakdown["skills"]["missing_required"]),
    }


def rank_all(resume_id: int, session_token: str) -> list[dict]:
    """Every posting in this session, scored and ordered best first.

    The UI does not use this -- it calls board_row per posting so the
    table fills in as results land -- but scripts and any future batch
    path want the whole list in one call.
    """
    rows = [board_row(resume_id, jd) for jd in list_jds(session_token)]
    return sorted(rows, key=lambda r: r["score"], reverse=True)


# ---------------------------------------------------------------------
# Shaping for the UI. Reflex state vars have to be JSON-serialisable, so
# everything below returns plain dicts/lists of primitives.
# ---------------------------------------------------------------------
def to_view(match) -> dict:
    b = match.breakdown
    components = [
        {
            "key": key,
            "label": COMPONENT_LABELS.get(key, key),
            "help": COMPONENT_HELP.get(key, ""),
            "score": round(value * 100, 1),
            "weight_pct": round(match.weights_used.get(key, 0.0) * 100),
            "contribution": round(value * match.weights_used.get(key, 0.0) * 100, 1),
        }
        for key, value in match.component_scores.items()
    ]
    components.sort(key=lambda c: c["contribution"], reverse=True)

    # A bare "50 / 100" reads as half marks; on the calibration set it is
    # the highest score observed. The band and percentile say what the
    # number means, and the raw score stays on screen next to them.
    percentile = percentile_against_calibration(match.final_score)
    top_percent = max(1, 100 - percentile)

    return {
        "resume_id": match.resume_id,
        "jd_id": match.jd_id,
        "final_score": match.final_score,
        "fit_band": fit_band(match.final_score),
        "percentile_label": f"top {top_percent}% of the {CALIBRATION_SET_SIZE}-posting calibration set",
        "verdict": VERDICT_LABELS.get(match.verdict, match.verdict),
        "verdict_color": VERDICT_COLORS.get(match.verdict, "gray"),
        "components": components,
        "dropped": [COMPONENT_LABELS.get(d, d) for d in match.dropped_components],
        "matched_required": b["skills"]["matched_required"],
        "matched_preferred": b["skills"]["matched_preferred"],
        "missing_required": b["skills"]["missing_required"],
        "missing_preferred": b["skills"]["missing_preferred"],
        "gaps": [
            {
                "skill_name": g["skill_name"],
                "is_required": g["is_required"],
                "requirement": "Required" if g["is_required"] else "Nice to have",
                "mentions": g["jd_mentions"],
                "adjacent": ", ".join(g["adjacent_skills_you_have"]),
            }
            for g in b["gaps"]
        ],
        "suggestions": b["suggestions"],
        "keyword_terms": [t for t, _ in b["keyword"]["top_terms"]][:12],
        "keyword_matched": b["keyword"]["matched_term_count"],
        "keyword_total": b["keyword"]["query_term_count"],
        "parsability": float(b.get("parsability_score") or 0.0),
        "title_note": _title_note(b["title"]),
        "experience_note": _experience_note(b["experience"]),
    }


def _title_note(title: dict) -> str:
    if title.get("resume_states_no_title"):
        return "No job-title line found on the resume — scored neutral, not zero."
    best = title.get("best_matching_title")
    return f"Closest resume title: {best}" if best else ""


def _experience_note(exp: dict) -> str:
    if exp.get("score") is None:
        return "This posting states no minimum, so experience was dropped from the blend."
    if exp.get("resume_states_no_years"):
        return (
            f"Posting asks for {exp.get('jd_min_years')}+ years; the resume states no "
            "total, so this is scored neutral."
        )
    shortfall = exp.get("shortfall_years") or 0
    if shortfall > 0:
        return f"{shortfall} year(s) short of the advertised {exp.get('jd_min_years')}."
    return f"Meets the advertised {exp.get('jd_min_years')} years."


def parsability_flags(resume_id: int) -> list[str]:
    rows = _query(
        "SELECT parsability_flags FROM resumes WHERE resume_id = %s", (resume_id,)
    )
    if not rows or not rows[0][0]:
        return []
    flags = rows[0][0]
    return list(flags) if isinstance(flags, list) else []


def resume_summary(resume_id: int) -> dict:
    rows = _query(
        "SELECT file_name, parsability_score, preview_png FROM resumes WHERE resume_id = %s",
        (resume_id,),
    )
    if not rows:
        return {}
    counts = dict(
        _query(
            "SELECT entity_type, count(*) FROM resume_entities WHERE resume_id = %s "
            "GROUP BY entity_type",
            (resume_id,),
        )
    )
    # inlined as a data URI rather than served from a route: the image
    # belongs to one session's resume, and a URL for it would be another
    # thing to authorise and another thing to clean up
    preview = rows[0][2]
    preview_uri = ""
    if preview:
        preview_uri = "data:image/png;base64," + base64.b64encode(bytes(preview)).decode()

    return {
        "file_name": rows[0][0],
        "parsability": float(rows[0][1] or 0),
        "skills": counts.get("skill", 0),
        "titles": counts.get("title", 0),
        "flags": parsability_flags(resume_id),
        "preview": preview_uri,
    }


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:120]
    return "Untitled posting"


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------
def dashboard_stats(resume_id: int | None = None, session_token: str = "") -> dict:
    """Headline counts for the overview page, scoped to this session.

    Averages come from match_results, i.e. matches actually run -- not a
    projection over postings never scored. The counts are session-scoped
    for the same reason the dropdowns are: "41 postings stored" is a lie
    to a visitor who has added two, and leaks how much other people have
    uploaded. Only the taxonomy size is global, because it is.
    """
    counts = _query(
        "SELECT (SELECT count(*) FROM resumes WHERE session_token = %s), "
        "(SELECT count(*) FROM job_descriptions WHERE session_token = %s), "
        "(SELECT count(*) FROM match_results m JOIN resumes r USING (resume_id) "
        " WHERE r.session_token = %s), "
        "(SELECT count(*) FROM skills_taxonomy)",
        (session_token, session_token, session_token),
    )[0]

    best_title, best_score, avg_score = "", 0.0, 0.0
    if resume_id:
        rows = _query(
            "SELECT j.title, m.final_blended_score FROM match_results m "
            "JOIN job_descriptions j USING (jd_id) WHERE m.resume_id = %s "
            "ORDER BY m.final_blended_score DESC LIMIT 1",
            (resume_id,),
        )
        if rows:
            best_title, best_score = rows[0][0] or "", float(rows[0][1] or 0)
        avg_rows = _query(
            "SELECT avg(final_blended_score) FROM match_results WHERE resume_id = %s",
            (resume_id,),
        )
        avg_score = float(avg_rows[0][0] or 0) if avg_rows else 0.0

    return {
        "resumes": counts[0],
        "postings": counts[1],
        "matches": counts[2],
        "skills": counts[3],
        "best_title": best_title,
        "best_score": round(best_score, 1),
        "avg_score": round(avg_score, 1),
    }


def recent_matches(resume_id: int, limit: int = 6) -> list[dict]:
    """Latest score per posting for this resume, newest first."""
    rows = _query(
        "SELECT DISTINCT ON (m.jd_id) m.jd_id, j.title, j.company, m.final_blended_score, "
        "m.verdict, m.computed_at FROM match_results m JOIN job_descriptions j USING (jd_id) "
        "WHERE m.resume_id = %s ORDER BY m.jd_id, m.computed_at DESC",
        (resume_id,),
    )
    matches = [
        {
            "jd_id": r[0],
            "title": r[1] or "Untitled posting",
            "company": r[2] or "",
            "score": float(r[3] or 0),
            "verdict": VERDICT_LABELS.get(r[4], r[4] or ""),
            "verdict_color": VERDICT_COLORS.get(r[4], "gray"),
            "when": r[5].strftime("%d %b, %H:%M") if r[5] else "",
        }
        for r in rows
    ]
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:limit]


def resume_detail(resume_id: int, top_skills: int = 40) -> dict:
    """What extraction found in a resume -- the evidence behind its scores."""
    skills = _query(
        "SELECT s.skill_name, count(*) FROM resume_entities e JOIN skills_taxonomy s USING (skill_id) "
        "WHERE e.resume_id = %s AND e.entity_type = 'skill' GROUP BY s.skill_name "
        "ORDER BY count(*) DESC, s.skill_name LIMIT %s",
        (resume_id, top_skills),
    )
    other = _query(
        "SELECT entity_type, entity_value FROM resume_entities WHERE resume_id = %s "
        "AND entity_type IN ('title', 'education', 'years_experience') ORDER BY entity_id",
        (resume_id,),
    )
    return {
        "skills": [s[0] for s in skills],
        "titles": [v for kind, v in other if kind == "title"][:8],
        "education": [v for kind, v in other if kind == "education"][:6],
        "years": [v for kind, v in other if kind == "years_experience"][:4],
    }


def jd_detail(jd_id: int) -> dict:
    rows = _query(
        "SELECT s.skill_name, e.is_required FROM jd_entities e JOIN skills_taxonomy s USING (skill_id) "
        "WHERE e.jd_id = %s AND e.entity_type = 'skill' GROUP BY s.skill_name, e.is_required "
        "ORDER BY s.skill_name",
        (jd_id,),
    )
    text = _query("SELECT COALESCE(cleaned_text, raw_text) FROM job_descriptions WHERE jd_id = %s", (jd_id,))
    return {
        "required": [r[0] for r in rows if r[1]],
        "preferred": [r[0] for r in rows if not r[1]],
        "excerpt": (text[0][0][:700] + "…") if text and text[0][0] else "",
    }


# ---------------------------------------------------------------------
# Session data: loading postings, and getting rid of them again
# ---------------------------------------------------------------------
SAMPLES_DIR = DATA_ROOT / "data/samples"
SAMPLE_RESUMES_DIR = SAMPLES_DIR / "resumes"

# How long a session's uploads survive. There is no dependable "browser
# closed" signal -- a tab can be killed, a laptop can sleep, and the
# server hears nothing -- so a sweep on a timer is the mechanism that
# actually runs. The UI says so plainly rather than implying data
# disappears the moment the tab does.
SESSION_TTL_HOURS = 24


def load_sample_postings(session_token: str) -> int:
    """Fictional postings that ship with the repo.

    Written for this project, so they cannot go stale and belong to
    nobody. Used when the live fetch is unavailable, and as the offline
    path generally.
    """
    loaded = 0
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        add_jd(text, session_token, source="sample", source_url=None)
        loaded += 1
    return loaded


def load_sample_resumes(session_token: str) -> int:
    """Two fictional resumes, for showing the tool without uploading a CV.

    Deliberately a matched pair: one clean single-column layout that
    scores 100 on parsability, and one with a ruled skills table, an
    embedded photo and a running header -- the three things a real ATS
    mangles -- which scores 50. The difference between them is the whole
    argument for checking formatting separately from content.
    """
    loaded = 0
    for path in sorted(SAMPLE_RESUMES_DIR.glob("*.pdf")):
        add_resume(str(path), session_token)
        loaded += 1
    return loaded


def load_live_postings(session_token: str, limit: int = 5) -> int:
    """Current graduate/junior postings, pulled from company job boards.

    Real listings beat canned ones for a demo, and fetching them at click
    time means they can never be out of date -- which is exactly the
    problem with shipping a fixed set of real postings.

    Falls back to the fictional samples if the boards are unreachable.
    """
    from scripts.fetch_board_jds import (
        AUSTRALIA,
        BOARDS,
        FETCHERS,
        classify,
        looks_like_a_vacancy,
    )

    collected: list[dict] = []
    for provider, token, company in BOARDS:
        if len(collected) >= limit:
            break
        try:
            jobs = FETCHERS[provider](token)
        except Exception:  # noqa: BLE001 -- a dead board is not fatal here
            continue
        for job in jobs:
            if not AUSTRALIA.search(job.get("location", "")):
                continue
            if len(job.get("text", "")) < 400:
                continue
            if not looks_like_a_vacancy(job):
                continue
            level, domain = classify(job)
            if level != "entry" or domain == "unrelated":
                continue
            job["company"] = company
            job["_relevant"] = domain == "relevant"
            collected.append(job)

    # quant/data/AI roles are what the tool is for, and an "Associate,
    # Office of the CEO" makes a poor first demo. The dropdown lists
    # newest first, so the most relevant is ingested *last* to land at
    # the top of it.
    collected.sort(key=lambda j: not j["_relevant"])
    collected = collected[:limit]
    collected.reverse()

    if not collected:
        return load_sample_postings(session_token)

    for job in collected:
        body = f"{job['title']}\n{job['company']}\n{job.get('location', '')}\n\n{job['text']}"
        add_jd(
            body, session_token, title=job["title"], company=job["company"],
            source="job_board", source_url=job.get("url"),
        )
    return len(collected)


def clear_session(session_token: str) -> tuple[int, int]:
    """Delete everything this session added. Returns (resumes, postings).

    Entities, chunks and match results are removed by ON DELETE CASCADE.
    """
    if not session_token:
        return (0, 0)
    with connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM resumes WHERE session_token = %s", (session_token,))
        resumes = cur.rowcount
        cur.execute("DELETE FROM job_descriptions WHERE session_token = %s", (session_token,))
        postings = cur.rowcount
        conn.commit()
        cur.close()
    clear_caches()
    return (resumes, postings)


def purge_expired(ttl_hours: int = SESSION_TTL_HOURS) -> tuple[int, int]:
    """Delete session data older than the TTL. Never touches NULL-token
    rows, which are the CLI-created ones the calibration scripts use."""
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM resumes WHERE session_token IS NOT NULL "
            "AND uploaded_at < now() - make_interval(hours => %s)",
            (ttl_hours,),
        )
        resumes = cur.rowcount
        cur.execute(
            "DELETE FROM job_descriptions WHERE session_token IS NOT NULL "
            "AND fetched_at < now() - make_interval(hours => %s)",
            (ttl_hours,),
        )
        postings = cur.rowcount
        conn.commit()
        cur.close()
    return (resumes, postings)
