"""
BM25 free-text keyword overlap -- the safety net for JD terms ESCO does
not cover (dbt, Databricks, Snowflake, in-house framework names, and
anything newer than the taxonomy).

Why this is implemented directly instead of calling rank_bm25
--------------------------------------------------------------
BM25's whole value is IDF: it is what makes "Snowflake" outweigh
"communication". IDF is a property of a *corpus*. Handing rank_bm25 a
two-document collection consisting of one resume and one JD gives every
term a near-identical IDF and produces an expensive word counter with a
BM25 label on it. The IDF here comes from the ~2.4k staged Kaggle resumes
instead (see scripts/build_bm25_corpus.py), which is the population the
scored document is actually drawn from.

rank_bm25 also has no clean way to score a document that was not in the
corpus at index time, which is exactly what is needed here -- the corpus
is a fixed background population, and the resume being scored is new.
Implementing the formula directly is about fifteen lines and avoids
rebuilding the index per match.

Normalisation
-------------
Raw BM25 is unbounded, so it cannot go into a weighted blend as-is. The
reference point used is "a document containing each query term exactly
once, at average document length", whose BM25 score works out to exactly
the sum of the query IDFs. Scores are divided by that and clipped to
[0, 1], so 1.0 means roughly "this resume mentions every meaningful JD
term at least once".
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.matching.config import (
    BM25_B,
    BM25_CORPUS_STATS_PATH,
    BM25_K1,
    BM25_MAX_QUERY_TERMS,
    BM25_MIN_QUERY_DF,
    BM25_MIN_TOKEN_LEN,
)
from src.matching.jd_sections import strip_boilerplate

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")

# Deliberately short. BM25 already down-weights ubiquitous terms through
# IDF, so a large stoplist is redundant and risks dropping real signal
# ("C" is already excluded by the length floor, but "go" and "r" are the
# kind of thing an aggressive list gets wrong).
_STOPWORDS = frozenset("""
the and for you our with are will that this have from your not but they
who all can has was were would should could their its into out about
across over under more most other than then them these those may might
""".split())


def tokenize(text: str) -> list[str]:
    # "." and "-" are allowed inside a token for node.js / scikit-learn, but
    # a sentence-final full stop was being kept too, so "insights." and
    # "insights" counted as different terms and the punctuated one looked
    # rare
    tokens = (t.rstrip(".-") for t in _TOKEN_RE.findall((text or "").lower()))
    return [
        t for t in tokens
        if len(t) >= BM25_MIN_TOKEN_LEN and t not in _STOPWORDS
    ]


@dataclass
class BM25Result:
    score: float | None
    top_terms: list[tuple[str, float]] = field(default_factory=list)
    matched_term_count: int = 0
    query_term_count: int = 0


class BM25Scorer:
    def __init__(self, n_docs: int, avgdl: float, df: dict[str, int]):
        self.n_docs = n_docs
        self.avgdl = avgdl or 1.0
        self.df = df

    @classmethod
    def from_stats_file(cls, path: str | Path = BM25_CORPUS_STATS_PATH) -> "BM25Scorer":
        stats = json.loads(Path(path).read_text())
        return cls(
            n_docs=stats["n_docs"],
            avgdl=stats["avgdl"],
            df=stats["df"],
        )

    def idf(self, term: str) -> float:
        # Standard BM25 IDF with the +0.5 smoothing, floored at a small
        # positive value. Unfloored, a term appearing in more than half the
        # corpus gets a negative IDF and a resume is *penalised* for using
        # a common word, which is not the intent.
        df = self.df.get(term, 0)
        raw = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
        return max(raw, 0.01)

    def build_query(self, jd_text: str) -> list[str]:
        """Most distinctive JD terms, capped.

        Boilerplate sections are removed first, and terms fewer than
        BM25_MIN_QUERY_DF corpus resumes use are skipped -- see config.py
        for why ranking on IDF alone picked employer names and benefits
        vocabulary over the actual requirements. Ranked by IDF with a
        log boost for terms the JD repeats, since repetition is how a
        posting signals what it cares about.

        The cap matters: a long JD contributes a couple of hundred
        low-IDF filler terms whose combined weight starts to drown the
        handful of terms that actually distinguish candidates.
        """
        counts = Counter(tokenize(strip_boilerplate(jd_text)))
        candidates = [t for t in counts if self.df.get(t, 0) >= BM25_MIN_QUERY_DF]
        ranked = sorted(
            candidates,
            key=lambda t: self.idf(t) * (1 + math.log(counts[t])),
            reverse=True,
        )
        return ranked[:BM25_MAX_QUERY_TERMS]

    def score(self, doc_text: str, jd_text: str) -> BM25Result:
        query = self.build_query(jd_text)
        if not query:
            return BM25Result(score=None)

        doc_tokens = tokenize(doc_text)
        if not doc_tokens:
            return BM25Result(score=0.0, query_term_count=len(query))

        dl = len(doc_tokens)
        tf: dict[str, int] = {}
        for token in doc_tokens:
            tf[token] = tf.get(token, 0) + 1

        norm = BM25_K1 * (1 - BM25_B + BM25_B * dl / self.avgdl)

        total = 0.0
        reference = 0.0
        contributions: list[tuple[str, float]] = []
        matched = 0

        for term in query:
            idf = self.idf(term)
            reference += idf  # BM25 of a tf=1, dl=avgdl document

            freq = tf.get(term, 0)
            if freq == 0:
                continue
            matched += 1
            contribution = idf * (freq * (BM25_K1 + 1)) / (freq + norm)
            total += contribution
            contributions.append((term, contribution))

        contributions.sort(key=lambda pair: pair[1], reverse=True)

        return BM25Result(
            score=min(total / reference, 1.0) if reference else None,
            top_terms=contributions[:15],
            matched_term_count=matched,
            query_term_count=len(query),
        )