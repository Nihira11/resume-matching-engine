"""
Matches free text against the ESCO skills taxonomy dataset (13,939 skills
via load_taxonomy.py) plus the curated tech skills in tech_skills.py

Exact/alias matching (case-insensitive) against every skill_name +
alias in the taxonomy, via a token n-gram dict -- see SkillMatcher. Deliberately exact-match
rather than fuzzy: fuzzy matching against a ~14k-term list produces too
many false positives (e.g. "R" the language matching inside unrelated
words). Fuzzy/embedding-based similarity is left for later, where it's
scored as a secondary semantic signal instead of a hard skill match

Every surface form maps to exactly one skill, resolved by precedence:
curated term > ESCO skill name > ESCO alias. Without that, the same span
could match two skills and whichever lookup returned first won --
which is how "TensorFlow" came out as "computer vision"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import spacy
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
    """Token n-gram lookup over the taxonomy.

    Was a pair of spaCy PhraseMatchers. They hold one Doc per pattern, and
    the taxonomy expands to 99,400 surface forms, which cost 313MB of
    resident memory -- more than torch and MiniLM together, and the reason
    a 1GB deployment was OOM-killed during ingestion.

    A dict keyed on the space-joined tokens of each term does the same job
    for a fraction of that. It is exactly equivalent: the pattern keys are
    built with this same tokenizer, so a key matches a span if and only if
    the PhraseMatcher's token-by-token comparison would have matched it.
    Overlaps are resolved afterwards by filter_spans, as before.
    """

    def __init__(self, nlp: spacy.language.Language, rows=None):
        """rows defaults to the skills_taxonomy table; pass them directly
        to build a matcher without a database (tests)."""
        self.nlp = nlp
        if rows is None:
            rows = self._fetch_taxonomy()
        insensitive, sensitive = build_term_maps(rows)
        self._lower = self._index(insensitive, lower=True)
        self._orth = self._index(sensitive, lower=False)
        self._max_tokens = max(
            [len(key.split(" ")) for key in (*self._lower, *self._orth)] or [1]
        )

    @staticmethod
    def _fetch_taxonomy():
        # cached locally: the rows are 10MB over the wire and change only
        # when a loader script runs (see taxonomy_cache.py)
        from src.nlp.taxonomy_cache import load_taxonomy_rows

        return load_taxonomy_rows()

    def _index(
        self, term_map: dict[str, tuple[int, str]], lower: bool
    ) -> dict[str, tuple[int, str]]:
        """Surface forms keyed by their tokenisation, not by raw string.

        Tokenising here is what makes the lookup equivalent to the
        PhraseMatcher: "scikit-learn" is three tokens to spaCy, so the key
        has to be "scikit - learn" for it to match the same span in a
        document. The Docs are discarded as they are built -- holding them
        is precisely the cost this class exists to avoid.
        """
        index: dict[str, tuple[int, str]] = {}
        tokenizer = self.nlp.tokenizer
        for term, skill in term_map.items():
            tokens = [t.lower_ if lower else t.text for t in tokenizer(term) if not t.is_space]
            if not tokens:
                continue
            index.setdefault(" ".join(tokens), skill)
        return index

    def match(self, doc: spacy.tokens.Doc) -> list[SkillMatch]:
        tokens = [t for t in doc if not t.is_space]
        lowered = [t.lower_ for t in tokens]
        exact = [t.text for t in tokens]

        results: list[SkillMatch] = []
        seen_spans: set[tuple[int, int]] = set()

        for start in range(len(tokens)):
            limit = min(self._max_tokens, len(tokens) - start)
            for length in range(limit, 0, -1):
                end = start + length
                skill = self._lower.get(" ".join(lowered[start:end]))
                if skill is None:
                    skill = self._orth.get(" ".join(exact[start:end]))
                if skill is None:
                    continue

                first, last = tokens[start], tokens[end - 1]
                key = (first.idx, last.idx + len(last.text))
                if key in seen_spans:
                    continue
                seen_spans.add(key)

                skill_id, skill_name = skill
                results.append(
                    SkillMatch(
                        skill_id=skill_id,
                        skill_name=skill_name,
                        matched_text=doc.text[key[0]:key[1]],
                        start_char=key[0],
                        end_char=key[1],
                    )
                )

        spans = [doc.char_span(r.start_char, r.end_char) for r in results]
        keep = {(s.start_char, s.end_char) for s in filter_spans([s for s in spans if s])}
        results = [r for r in results if (r.start_char, r.end_char) in keep]

        return results
