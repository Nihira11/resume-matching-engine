"""
Reads what the ingestion pipeline wrote into `resume_entities` /
`jd_entities` and turns
it into the shape the scorers want.

The scorers are all pure functions over these two dataclasses, with no DB
access of their own. That is what makes tests/test_matching.py runnable
with no database and no spaCy model load.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.matching.config import PREFERRED_MARKERS, REQUIRED_MARKERS
from src.utils.db import get_connection


@dataclass
class ResumeProfile:
    resume_id: int
    cleaned_text: str = ""
    skill_ids: set[int] = field(default_factory=set)
    skill_names: dict[int, str] = field(default_factory=dict)
    skill_mentions: dict[int, int] = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    years_experience: int | None = None
    parsability_score: float | None = None


@dataclass
class JDProfile:
    jd_id: int
    title: str = ""
    cleaned_text: str = ""
    required_skill_ids: set[int] = field(default_factory=set)
    preferred_skill_ids: set[int] = field(default_factory=set)
    skill_names: dict[int, str] = field(default_factory=dict)
    skill_mentions: dict[int, int] = field(default_factory=dict)
    min_years: int | None = None
    seniority_level: str | None = None

    @property
    def all_skill_ids(self) -> set[int]:
        return self.required_skill_ids | self.preferred_skill_ids


# ---------------------------------------------------------------------
# Years of experience, JD side
# ---------------------------------------------------------------------
# extract_years_experience() takes the UPPER bound of a range, so "3-5" is
# stored as 5 and the 3 is discarded before it ever reaches jd_entities.
# On a resume that is a defensible proxy for career length. On a JD it
# inverts the meaning: the advertised bar is 3, and scoring against 5
# penalises every candidate sitting exactly at the stated minimum.
#
# Because the lower bound is lost at extraction time, it cannot be
# recovered from the stored entities -- it has to be re-derived from
# job_descriptions.cleaned_text. Done here rather than by changing
# extract_years_experience(), which is doing the right thing for the input
# it was designed for; this is a JD-specific reading of the same text, not
# a bug fix to the extractor.
_JD_YEARS_RE = re.compile(
    r"(?<![\d.])(\d{1,2})(?!\.\d)\s*(?:\+|-|–|–|to|or more|or above)?\s*(?:\d{1,2})?\s*\+?\s*years?\b",
    re.IGNORECASE,
)
_MINIMUM_CUES = (
    "minimum", "at least", "at a minimum", "no less than",
    "required", "requirement", "must have", "must-have", "essential",
)


def extract_jd_min_years(text: str) -> int | None:
    """Lowest advertised years requirement, taking the LOWER bound of ranges.

    Two passes. Values sitting near explicit minimum language ("minimum 3
    years", "at least 2 years of SQL") are preferred, because a JD that
    bothers to write "minimum" is telling you exactly where the bar is.
    Failing that, the smallest figure anywhere in the posting is used --
    the conservative reading, since JDs routinely name per-skill years
    ("5 years Python, 2 years Spark") where the smallest sits closer to a
    real screening floor than the largest does.
    """
    if not text:
        return None

    lowered = text.lower()
    cued: list[int] = []
    all_values: list[int] = []

    for match in _JD_YEARS_RE.finditer(lowered):
        value = int(match.group(1))
        all_values.append(value)
        window = lowered[max(0, match.start() - 60): match.start()]
        if any(cue in window for cue in _MINIMUM_CUES):
            cued.append(value)

    if cued:
        return min(cued)
    return min(all_values) if all_values else None


# ---------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------
def load_resume_profile(resume_id: int) -> ResumeProfile:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT cleaned_text, raw_text, parsability_score FROM resumes WHERE resume_id = %s",
        (resume_id,),
    )
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise ValueError(f"no resume with resume_id={resume_id}")
    cleaned_text, raw_text, parsability = row

    # LEFT JOIN for the canonical taxonomy label. entity_value holds
    # SkillMatch.matched_text -- the surface form exactly as it appeared in
    # the document, so an alias or a lowercase mention is stored verbatim.
    # That is the right thing to store (it is what refresh_is_required
    # searches for in the raw text) but the wrong thing to compare or
    # display: ESCO adjacency lookups key on preferredLabel, and a UI that
    # says "missing: pyhton" in the employer's casing looks broken.
    cur.execute(
        """
        SELECT e.entity_type, e.entity_value, e.skill_id, s.skill_name
        FROM resume_entities e
        LEFT JOIN skills_taxonomy s ON s.skill_id = e.skill_id
        WHERE e.resume_id = %s
        """,
        (resume_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    profile = ResumeProfile(
        resume_id=resume_id,
        cleaned_text=cleaned_text or raw_text or "",
        parsability_score=float(parsability) if parsability is not None else None,
    )

    years: list[int] = []
    for entity_type, entity_value, skill_id, canonical_name in rows:
        if entity_type == "skill" and skill_id is not None:
            profile.skill_ids.add(skill_id)
            profile.skill_names[skill_id] = canonical_name or entity_value
            # The matcher emits one row per occurrence, so the row count
            # per skill_id is a free, exact mention count.
            profile.skill_mentions[skill_id] = profile.skill_mentions.get(skill_id, 0) + 1
        elif entity_type == "title":
            profile.titles.append(entity_value)
        elif entity_type == "education":
            profile.education.append(entity_value)
        elif entity_type == "years_experience":
            parsed = _safe_int(entity_value)
            if parsed is not None:
                years.append(parsed)

    # MAX on the resume side: the regex fires on every "N years" phrase in
    # the document, including per-skill claims like "3 years of Python".
    # The largest is the best available proxy for total career length.
    profile.years_experience = max(years) if years else None
    return profile


def load_jd_profile(jd_id: int) -> JDProfile:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT title, cleaned_text, raw_text, seniority_level "
        "FROM job_descriptions WHERE jd_id = %s",
        (jd_id,),
    )
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise ValueError(f"no job description with jd_id={jd_id}")
    title, cleaned_text, raw_text, seniority = row

    cur.execute(
        """
        SELECT e.entity_type, e.entity_value, e.skill_id, e.is_required, s.skill_name
        FROM jd_entities e
        LEFT JOIN skills_taxonomy s ON s.skill_id = e.skill_id
        WHERE e.jd_id = %s
        """,
        (jd_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    profile = JDProfile(
        jd_id=jd_id,
        title=title or "",
        cleaned_text=cleaned_text or raw_text or "",
        seniority_level=seniority,
    )

    stored_years: list[int] = []
    title_entities: list[str] = []

    for entity_type, entity_value, skill_id, is_required, canonical_name in rows:
        if entity_type == "skill" and skill_id is not None:
            target = (
                profile.required_skill_ids if is_required
                else profile.preferred_skill_ids
            )
            target.add(skill_id)
            profile.skill_names[skill_id] = canonical_name or entity_value
            profile.skill_mentions[skill_id] = profile.skill_mentions.get(skill_id, 0) + 1
        elif entity_type == "title":
            title_entities.append(entity_value)
        elif entity_type in ("min_years_experience", "years_experience"):
            parsed = _safe_int(entity_value)
            if parsed is not None:
                stored_years.append(parsed)

    # job_descriptions.title is nullable and manual-paste JDs frequently
    # leave it empty, which would drop the entire title component. The
    # extracted title entities are noisier (extract_titles keeps whole lines) but
    # the title scorer uses asymmetric containment precisely so that extra
    # context costs nothing -- it copes here too.
    if not profile.title.strip() and title_entities:
        profile.title = title_entities[0]

    # Re-derive from text rather than trusting the stored upper bounds.
    # Falls back to the entities only when the text yields nothing.
    profile.min_years = extract_jd_min_years(profile.cleaned_text)
    if profile.min_years is None and stored_years:
        profile.min_years = min(stored_years)

    return profile


def _safe_int(value: str) -> int | None:
    match = re.search(r"\d{1,2}", str(value))
    return int(match.group(0)) if match else None


# ---------------------------------------------------------------------
# Required vs preferred backfill
# ---------------------------------------------------------------------
# jd_pipeline defaults `is_required` to TRUE for every JD entity, with the
# distinction explicitly deferred to here. Run this once per JD before
# scoring it.
_HEADING_RE = re.compile(r"^\s*(?:[-*•]\s*)?([A-Z][^.!?]{2,60}:?)\s*$")


def split_requirement_sections(text: str) -> list[tuple[str, bool]]:
    """Split JD text into (block_text, is_required) pairs.

    Works at section level rather than sentence level because that is how
    JDs actually signal it -- a "Nice to have" heading followed by six
    bullets, not six bullets each containing the word "preferred". The
    mode set by a heading carries forward until the next heading changes
    it, and text before any heading defaults to required.
    """
    blocks: list[tuple[str, bool]] = []
    current: list[str] = []
    is_required = True

    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        looks_like_heading = bool(_HEADING_RE.match(stripped)) or lowered.endswith(":")

        if looks_like_heading and stripped:
            if any(marker in lowered for marker in PREFERRED_MARKERS):
                if current:
                    blocks.append(("\n".join(current), is_required))
                    current = []
                is_required = False
            elif any(marker in lowered for marker in REQUIRED_MARKERS):
                if current:
                    blocks.append(("\n".join(current), is_required))
                    current = []
                is_required = True

        current.append(line)

    if current:
        blocks.append(("\n".join(current), is_required))
    return blocks


def refresh_is_required(jd_id: int) -> int:
    """Set jd_entities.is_required per section. Returns rows changed.

    A skill is downgraded to preferred only when *every* occurrence of it
    falls inside a preferred block. Something listed under both "Required"
    and "Nice to have" is required -- the stricter reading is the one an
    ATS would take.

    Matches on entity_value (the verbatim surface form) rather than the
    canonical taxonomy label, because this searches the original text and
    the surface form is what is actually in there.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(cleaned_text, raw_text) FROM job_descriptions WHERE jd_id = %s",
        (jd_id,),
    )
    row = cur.fetchone()
    if row is None or not row[0]:
        cur.close()
        conn.close()
        return 0

    blocks = split_requirement_sections(row[0])
    required_text = "\n".join(b for b, req in blocks if req).lower()
    preferred_text = "\n".join(b for b, req in blocks if not req).lower()

    cur.execute(
        "SELECT entity_id, entity_value FROM jd_entities "
        "WHERE jd_id = %s AND entity_type = 'skill'",
        (jd_id,),
    )
    entities = cur.fetchall()

    changed = 0
    for entity_id, entity_value in entities:
        term = (entity_value or "").lower().strip()
        if not term:
            continue
        if term in preferred_text and term not in required_text:
            cur.execute(
                "UPDATE jd_entities SET is_required = FALSE WHERE entity_id = %s",
                (entity_id,),
            )
            changed += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()
    return changed