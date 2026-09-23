"""
Matches free text against the ESCO skills taxonomy dataset (13,939 skills
via load_taxonomy.py) plus the curated tech skills in tech_skills.py

Uses spaCy's PhraseMatcher for exact/alias matching (case-insensitive)
against every skill_name + alias in the taxonomy. Deliberately exact-match
rather than fuzzy: fuzzy matching against a ~14k-term list produces too
many false positives (e.g. "R" the language matching inside unrelated
words). Fuzzy/embedding-based similarity is left for later, where it's
scored as a secondary semantic signal instead of a hard skill match

Every surface form maps to exactly one skill, resolved by precedence:
curated term > ESCO skill name > ESCO alias. Without that, the same span
could match two skills and whichever PhraseMatcher returned first won --
which is how "TensorFlow" came out as "computer vision"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import spacy
from spacy.matcher import PhraseMatcher
from spacy.util import filter_spans

from src.nlp.tech_skills import CASE_SENSITIVE_TERMS

# Real skill/technology names that are also extremely common English
# words – case-insensitive matching treats "LESS" (the CSS preprocessor)
# and "less" (the word) identically, so these false-positive constantly
# on ordinary prose ("less than 1 year", "less experience", etc.).
# Found via validation against the Kaggle NER dataset (LESS matched inside
# every "(Less than 1 year)" skill-proficiency annotation in the ground
# truth). "source" and "CFD" were found scoring real job postings:
# "open-source" matched a game engine, and CFD (the trading product)
# matched computational fluid dynamics
AMBIGUOUS_SKILL_TERMS = {
    "less",    # CSS preprocessor language, also an ordinary English word
    "source",  # "Source (digital game creation systems)" alias
    "cfd",     # computational fluid dynamics vs contract for difference
}

# A single all-lowercase word used as an ESCO *alias* is almost always a
# generic English word standing in for a broader competency: "patterns"
# -> dies, "brands" -> trademarks, "integrity" -> morality, "logistic"
# (from "logistic regression") -> logistics. The first Phase 1 validation
# documented this as a known limitation and left it, on the grounds that
# a stoplist can't keep up. Scoring 13 real postings showed it dominating
# the extracted skill lists, so it's filtered by shape instead of by list:
# 518 aliases dropped, and 22 of the 26 matches that disappeared on the
# validation set were wrong. Capitalised and mixed-case aliases (Python,
# TensorFlow, SQL) and multi-word aliases are kept, and ESCO skill names
# themselves are never filtered
_GENERIC_ALIAS_RE = re.compile(r"^[a-z]+$")

CURATED_SOURCE = "curated"

# precedence: lower wins
_CURATED, _ESCO_NAME, _ESCO_ALIAS = 0, 1, 2


@dataclass
class SkillMatch:
    skill_id: int
    skill_name: str
    matched_text: str
    start_char: int
    end_char: int


def build_term_maps(
    rows, case_sensitive_terms=CASE_SENSITIVE_TERMS
) -> tuple[dict[str, tuple[int, str]], dict[str, tuple[int, str]]]:
    """Resolve taxonomy rows to (case-insensitive map, case-sensitive map).

    rows are (skill_id, skill_name, aliases, source). The insensitive map
    is keyed by lowercased term, the sensitive map by the exact term. A
    curated case-sensitive term also claims its lowercase form away from
    ESCO -- otherwise ESCO's "SPARK" (the Ada language) would still match
    "Spark" case-insensitively and the case-sensitive pass would be
    pointless.
    """
    best: dict[str, tuple[int, int, str]] = {}  # lower term -> (rank, id, name)
    sensitive: dict[str, tuple[int, str]] = {}

    def offer(term: str, rank: int, skill_id: int, name: str) -> None:
        key = term.strip().lower()
        if len(key) <= 2 or key in AMBIGUOUS_SKILL_TERMS:
            # 1-2 char terms (bare "R", "C") false-positive too often
            # without a dedicated short-token allowlist
            return
        current = best.get(key)
        if current is None or rank < current[0]:
            best[key] = (rank, skill_id, name)

    for skill_id, skill_name, aliases, source in rows:
        if skill_name.strip().lower() in AMBIGUOUS_SKILL_TERMS:
            continue
        if source == CURATED_SOURCE:
            for term in [skill_name] + list(aliases or []):
                if term in case_sensitive_terms:
                    sensitive[term] = (skill_id, skill_name)
                    # claim the lowercase form with top precedence, then
                    # drop it from the insensitive map below
                    best[term.lower()] = (-1, skill_id, skill_name)
                else:
                    offer(term, _CURATED, skill_id, skill_name)
        else:
            offer(skill_name, _ESCO_NAME, skill_id, skill_name)
            for alias in aliases or []:
                if alias and not _GENERIC_ALIAS_RE.match(alias.strip()):
                    offer(alias, _ESCO_ALIAS, skill_id, skill_name)

    insensitive = {
        term: (skill_id, name)
        for term, (rank, skill_id, name) in best.items()
        if rank >= 0
    }
    return insensitive, sensitive


class SkillMatcher:
    def __init__(self, nlp: spacy.language.Language, rows=None):
        """rows defaults to the skills_taxonomy table; pass them directly
        to build a matcher without a database (tests)."""
        self.nlp = nlp
        if rows is None:
            rows = self._fetch_taxonomy()
        insensitive, sensitive = build_term_maps(rows)
        self.matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        self.sensitive_matcher = PhraseMatcher(nlp.vocab, attr="ORTH")
        self._lookup: dict[int, tuple[int, str]] = {}  # hash -> (skill_id, skill_name)
        self._add(self.matcher, insensitive)
        self._add(self.sensitive_matcher, sensitive)

    @staticmethod
    def _fetch_taxonomy():
        # cached locally: the rows are 10MB over the wire and change only
        # when a loader script runs (see taxonomy_cache.py)
        from src.nlp.taxonomy_cache import load_taxonomy_rows

        return load_taxonomy_rows()

    def _add(self, matcher: PhraseMatcher, term_map: dict[str, tuple[int, str]]) -> None:
        by_skill: dict[tuple[int, str], list[str]] = {}
        for term, skill in term_map.items():
            by_skill.setdefault(skill, []).append(term)
        for (skill_id, skill_name), terms in by_skill.items():
            key = str(skill_id)
            matcher.add(key, [self.nlp.make_doc(t) for t in terms])
            self._lookup[self.nlp.vocab.strings[key]] = (skill_id, skill_name)

    def match(self, doc: spacy.tokens.Doc) -> list[SkillMatch]:
        matches = self.matcher(doc) + self.sensitive_matcher(doc)
        results = []
        seen_spans = set()

        for match_id, start, end in matches:
            span = doc[start:end]
            key = (span.start_char, span.end_char)
            if key in seen_spans:
                continue
            seen_spans.add(key)

            skill_id, skill_name = self._lookup.get(match_id, (None, None))
            if skill_id is None:
                continue

            results.append(
                SkillMatch(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    matched_text=span.text,
                    start_char=span.start_char,
                    end_char=span.end_char,
                )
            )

        spans = [doc.char_span(r.start_char, r.end_char) for r in results]
        keep = {(s.start_char, s.end_char) for s in filter_spans([s for s in spans if s])}
        results = [r for r in results if (r.start_char, r.end_char) in keep]

        return results
