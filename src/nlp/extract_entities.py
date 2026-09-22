"""
Entity extraction for resumes and JDs: skills, job titles, education,
years of experience

Skills route through the ESCO-taxonomy PhraseMatcher (skill_matcher.py).
Titles/education/years-of-experience are regex + keyword heuristics rather
than spaCy's built-in NER labels – ESCO occupation labels are too noisy for
reliable free-text title extraction, and years-of-experience needs numeric
range handling regex does better than any NER label
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import spacy

_nlp = None
_skill_matcher = None


def get_nlp() -> spacy.language.Language:
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_lg")
    return _nlp


def get_skill_matcher():
    global _skill_matcher
    if _skill_matcher is None:
        from src.nlp.skill_matcher import SkillMatcher
        _skill_matcher = SkillMatcher(get_nlp())
    return _skill_matcher


DEGREE_PATTERN = re.compile(
    r"\b(?:Bachelor(?:'s)?|Master(?:'s)?|PhD|Ph\.D\.?|Doctorate|"
    r"B\.?Sc\.?|M\.?Sc\.?|B\.?A\.?|M\.?A\.?|B\.?Eng\.?|M\.?Eng\.?|MBA|B\.?Com\.?|M\.?Com\.?)\b"
    r"(?:[ \t]*[:\-]?[ \t]*(?:of|in)?[ \t]*[A-Z][A-Za-z&,\- \t]{2,40})?"
    # "Associate" is handled separately and more strictly than the other
    # degree words above: unlike "Bachelor"/"Master"/etc., "Associate" is
    # extremely common as a job-title word ("Associate Consultant", "Sales
    # Associate"), so a bare "Associate" match would false-positive
    # constantly. It's only treated as a degree signal when followed by a
    # colon + field of study (e.g. "Associate : Accounting") or the
    # explicit word "degree" – a dash is deliberately NOT accepted here
    # since "Title - Company" uses dashes just as often as a real degree
    # line would
    r"|\bAssociate(?:'s|s)?\b[ \t]*:[ \t]*[A-Z][A-Za-z&,\- \t]{2,40}"
    r"|\bAssociate(?:'s|s)?\s+[Dd]egree(?:\s+in\s+[A-Z][A-Za-z&,\- \t]{2,40})?",
    re.IGNORECASE,
)

# decimals are captured as part of the number ("6.8 years" -> 6.8). The
# earlier version only took whole digits, so the \b before the "8" in
# "6.8" let it match "8 years" and read 6.8 as 8. The lookbehind stops a
# match starting mid-number for the same reason
_YEARS_NUMBER = r"\d{1,2}(?:\.\d{1,2})?"
YEARS_EXPERIENCE_PATTERN = re.compile(
    r"(?<![\d.])(" + _YEARS_NUMBER + r")\+?\s*(?:-|to)?\s*(" + _YEARS_NUMBER + r")?\+?\s*years?\b"
    r"(?:\s+of)?(?:\s+experience)?",
    re.IGNORECASE,
)

# word-boundary regex per keyword – NOT plain substring matching. Plain
# substring checks ("director" in line.lower()) false-positive badly:
# "Directorate" contains "director", "Associates" contains "associate",
# "managerial" contains "manager". \b enforces whole-word matches only
TITLE_KEYWORDS = [
    "analyst", "engineer", "scientist", "developer", "manager", "consultant",
    "intern", "internship", "associate", "director", "lead", "architect",
    "specialist", "coordinator",
    # general-workforce titles — the original list only covered tech and
    # professional services, so the actual title header was missed on
    # accounting, admin, healthcare and trades resumes
    "accountant", "auditor", "administrator", "assistant", "clerk",
    "officer", "technician", "advisor", "supervisor", "representative",
]
_TITLE_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(TITLE_KEYWORDS) + r")\b", re.IGNORECASE
)


@dataclass
class ExtractedEntities:
    skills: list = field(default_factory=list)              # list[SkillMatch]
    titles: list = field(default_factory=list)              # list[str]
    education: list = field(default_factory=list)           # list[str]
    years_experience: list = field(default_factory=list)    # list[int | float]


def extract_titles(text: str) -> list[str]:
    """Scan lines for a whole-word title keyword, keep the whole line
    (trimmed) as the candidate title. Deduplicated, order-preserving. Lines
    over 80 chars are skipped – a line that long is almost always a bullet
    point, not a title/header line"""
    titles = []
    seen = set()
    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 80:
            continue
        if _TITLE_KEYWORD_PATTERN.search(line_clean) and line_clean not in seen:
            seen.add(line_clean)
            titles.append(line_clean)
    return titles


def extract_education(text: str) -> list[str]:
    results = []
    seen = set()
    for m in DEGREE_PATTERN.finditer(text):
        val = m.group(0).strip()
        if val not in seen:
            seen.add(val)
            results.append(val)
    return results


def _to_number(value: str) -> int | float:
    # whole numbers stay ints so "5 years" is still stored as "5", not "5.0"
    number = float(value)
    return int(number) if number.is_integer() else number


def extract_years_experience(text: str) -> list[int | float]:
    years = []
    for m in YEARS_EXPERIENCE_PATTERN.finditer(text):
        low, high = m.group(1), m.group(2)
        if high:
            years.append(_to_number(high))  # range given – take the upper bound
        elif low:
            years.append(_to_number(low))
    return sorted(set(years), reverse=True)


def extract_all(text: str) -> ExtractedEntities:
    nlp = get_nlp()
    matcher = get_skill_matcher()
    doc = nlp(text)

    return ExtractedEntities(
        skills=matcher.match(doc),
        titles=extract_titles(text),
        education=extract_education(text),
        years_experience=extract_years_experience(text),
    )
