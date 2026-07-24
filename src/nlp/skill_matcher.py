"""
Matches free text against the ESCO skills taxonomy dataset (13,939 skills 
via load_taxonomy.py)

Uses spaCy's PhraseMatcher for exact/alias matching (case-insensitive)
against every skill_name + alias in the taxonomy. Deliberately exact-match
rather than fuzzy: fuzzy matching against a ~14k-term list produces too
many false positives (e.g. "R" the language matching inside unrelated
words). Fuzzy/embedding-based similarity is left for later, where it's
scored as a secondary semantic signal instead of a hard skill match
"""
from __future__ import annotations

from dataclasses import dataclass

import spacy
from spacy.matcher import PhraseMatcher
from spacy.util import filter_spans

from src.utils.db import get_connection

# Real skill/technology names that are also extremely common English
# words – case-insensitive matching treats "LESS" (the CSS preprocessor)
# and "less" (the word) identically, so these false-positive constantly
# on ordinary prose ("less than 1 year", "less experience", etc.).
# Found via validation against the Kaggle NER dataset (LESS matched inside
# every "(Less than 1 year)" skill-proficiency annotation in the ground
# truth). Excluded entirely rather than handled with case-sensitive
# matching, since spaCy's PhraseMatcher attr="LOWER" applies to the whole
# matcher, not per-pattern – case-sensitive matching would need a second,
# separate PhraseMatcher instance just for this handful of terms, which
# isn't worth the complexity for a handful of known offenders. If more
# turn up during validation, add them here rather than special-casing
# a second matcher
AMBIGUOUS_SKILL_TERMS = {
    "less",  # CSS preprocessor language, also an ordinary English word
}


@dataclass
class SkillMatch:
    skill_id: int
    skill_name: str
    matched_text: str
    start_char: int
    end_char: int


class SkillMatcher:
    def __init__(self, nlp: spacy.language.Language):
        self.nlp = nlp
        self.matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        self._lookup: dict[int, tuple[int, str]] = {}  # hash -> (skill_id, skill_name)
        self._load_taxonomy()

    def _load_taxonomy(self) -> None:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT skill_id, skill_name, aliases FROM skills_taxonomy")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for skill_id, skill_name, aliases in rows:
            if skill_name.strip().lower() in AMBIGUOUS_SKILL_TERMS:
                continue

            terms = [skill_name] + (aliases or [])
            # skip 1-2 char terms (e.g. bare "R", "C") – too many false
            # positives from PhraseMatcher without a dedicated short-token
            # allowlist. Also skip any alias that's itself an ambiguous
            # common word, even if the canonical skill_name wasn't caught
            # by the check above
            terms = [
                t for t in terms
                if t and len(t) > 2 and t.strip().lower() not in AMBIGUOUS_SKILL_TERMS
            ]
            if not terms:
                continue

            key = str(skill_id)
            patterns = [self.nlp.make_doc(t) for t in terms]
            self.matcher.add(key, patterns)
            self._lookup[self.nlp.vocab.strings[key]] = (skill_id, skill_name)

    def match(self, doc: spacy.tokens.Doc) -> list[SkillMatch]:
        matches = self.matcher(doc)
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