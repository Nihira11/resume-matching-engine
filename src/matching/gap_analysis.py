"""
Gap analysis: what the JD asks for that the resume does not show, ranked,
plus adjacent skills the candidate already has.

The adjacency piece is what `esco_occupation_skill_relations.csv` is for.
It was downloaded and staged during setup and has sat unused since. It maps
occupations to their constituent skills, so for any missing skill it can
answer "which occupations require this, and what else do those occupations
require that this candidate already has?" -- which turns a flat "you're
missing Airflow" into "you're missing Airflow, but you have Luigi and
cron-based scheduling, so lead with those".

Reads a committed, gzipped cache of the derived map by preference; the
CSVs are only parsed when that is missing. The CSVs are 36MB and
ESCO-licensed so they are gitignored, which meant every deployment lost
this feature silently until the cache existed.

Degrades gracefully: with neither cache nor CSVs the adjacency lookup
returns nothing and the rest of the gap analysis is unaffected.
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.matching.config import (
    ESCO_ADJACENCY_CACHE_PATH,
    ESCO_RELATIONS_PATH,
    ESCO_SKILLS_PATH,
    MAX_ADJACENT_SUGGESTIONS,
    MIN_ADJACENCY_CO_OCCURRENCES,
)
from src.matching.profiles import JDProfile, ResumeProfile
from src.matching.skill_overlap import SkillOverlapResult

_adjacency: dict[str, set[str]] | None = None


@dataclass
class SkillGap:
    skill_id: int
    skill_name: str
    is_required: bool
    jd_mentions: int
    adjacent_skills_you_have: list[str] = field(default_factory=list)


@dataclass
class GapAnalysisResult:
    gaps: list[SkillGap] = field(default_factory=list)
    matched_skill_names: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _load_adjacency() -> dict[str, set[str]]:
    """label -> set of labels that co-occur in at least one ESCO occupation.

    Joined through preferredLabel rather than URI because skills_taxonomy
    has no esco_uri column yet (see the commented migration in
    002_matching_engine.sql). Lossy on the 21 duplicate labels dropped by
    ON CONFLICT during the taxonomy load, which is acceptable for a
    suggestion feature -- a missing suggestion costs nothing, a wrong score
    would.
    """
    global _adjacency
    if _adjacency is not None:
        return _adjacency

    _adjacency = {}

    # Prefer the committed cache. The CSVs are gitignored, so outside a
    # development machine that has downloaded them this is the only path
    # that produces suggestions at all -- see ESCO_ADJACENCY_CACHE_PATH.
    cache_path = Path(ESCO_ADJACENCY_CACHE_PATH)
    if cache_path.exists():
        try:
            with gzip.open(cache_path, "rt", encoding="utf-8") as handle:
                _adjacency = json.load(handle)
            return _adjacency
        except (OSError, ValueError) as error:
            # a corrupt cache falls through to the CSVs rather than
            # taking the feature down
            print(f"adjacency cache unreadable ({error}); falling back to the CSVs")
            _adjacency = {}

    skills_path = Path(ESCO_SKILLS_PATH)
    relations_path = Path(ESCO_RELATIONS_PATH)
    if not skills_path.exists() or not relations_path.exists():
        return _adjacency

    uri_to_label: dict[str, str] = {}
    with skills_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            uri = row.get("conceptUri") or row.get("skillUri")
            label = (row.get("preferredLabel") or "").strip().lower()
            if uri and label:
                uri_to_label[uri] = label

    occupation_skills: dict[str, set[str]] = defaultdict(set)
    with relations_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            occupation = row.get("occupationUri")
            label = uri_to_label.get(row.get("skillUri", ""))
            if occupation and label:
                occupation_skills[occupation].add(label)

    # Counted, not just collected. Co-occurring in one occupation means
    # very little -- it put "3d lighting" and "abap" next to Python --
    # while co-occurring in several is a real signal: the same ranking by
    # count puts computer programming, C++, C# and Java at the top.
    adjacency: dict[str, Counter] = defaultdict(Counter)
    for labels in occupation_skills.values():
        # Occupations with enormous skill lists produce near-universal
        # adjacency and make every suggestion meaningless, so skip them.
        if len(labels) > 80:
            continue
        for label in labels:
            adjacency[label].update(labels - {label})

    _adjacency = {
        label: {
            neighbour: count
            for neighbour, count in counts.items()
            if count >= MIN_ADJACENCY_CO_OCCURRENCES
        }
        for label, counts in adjacency.items()
    }
    return _adjacency


def analyse_gaps(
    resume: ResumeProfile,
    jd: JDProfile,
    overlap: SkillOverlapResult,
    resume_states_no_years: bool = False,
    resume_states_no_title: bool = False,
) -> GapAnalysisResult:
    resume_labels = {name.lower() for name in resume.skill_names.values()}
    adjacency = _load_adjacency()

    # Mention counts come straight from the entity rows. The skill matcher
    # emits one row per occurrence, so counting rows per skill_id is exact
    # -- and it correctly counts multi-word skills and alias forms, which a
    # token-frequency proxy over the raw JD text gets wrong.
    gaps: list[SkillGap] = []
    for skill_id in overlap.missing_required + overlap.missing_preferred:
        name = jd.skill_names.get(skill_id, str(skill_id))
        neighbours = adjacency.get(name.lower(), {})
        # strongest association first, not alphabetical
        related = sorted(
            (n for n in neighbours if n in resume_labels),
            key=lambda n: (-neighbours[n], n),
        )[:MAX_ADJACENT_SUGGESTIONS]
        gaps.append(
            SkillGap(
                skill_id=skill_id,
                skill_name=name,
                is_required=skill_id in overlap.missing_required,
                jd_mentions=jd.skill_mentions.get(skill_id, 0),
                adjacent_skills_you_have=related,
            )
        )

    # Required first, then by how often the JD repeats the term. Repetition
    # is a decent proxy for how much the employer cares -- a skill named
    # once in a wishlist and one named in the title, the summary and three
    # bullets are not equally important, and a flat alphabetical list of
    # missing skills buries that.
    gaps.sort(key=lambda g: (not g.is_required, -g.jd_mentions, g.skill_name))

    suggestions: list[str] = []
    if resume_states_no_years:
        suggestions.append(
            "This posting states a minimum years-of-experience requirement, but "
            "the resume never states a total. Adding an explicit figure to the "
            "summary line gives a keyword screen something to match."
        )
    if resume_states_no_title:
        suggestions.append(
            "No job-title line was found on the resume, so the title match is "
            "scored neutral. A headline such as \"Data Science Student\" or a "
            "role title on each position gives an ATS title filter something "
            "to match against this posting's title."
        )
    top_required = [g for g in gaps if g.is_required][:5]
    if top_required:
        suggestions.append(
            "Highest-impact additions, if they are true: "
            + ", ".join(g.skill_name for g in top_required)
        )
    for gap in top_required:
        if gap.adjacent_skills_you_have:
            suggestions.append(
                f"For '{gap.skill_name}', you already list related experience "
                f"({', '.join(gap.adjacent_skills_you_have)}) – worth surfacing "
                f"that in the same bullet rather than claiming the missing skill."
            )

    return GapAnalysisResult(
        gaps=gaps,
        matched_skill_names=sorted(
            jd.skill_names.get(sid, str(sid)) for sid in overlap.matched_ids
        ),
        suggestions=suggestions,
    )