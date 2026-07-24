"""
Semantic similarity -- the secondary signal.

Pooling is deliberately asymmetric. For each JD chunk, take the best-
matching resume chunk, then average across JD chunks. That asks "is every
part of what this job wants covered somewhere in this resume?", which is
the screening question. The reverse direction ("is every part of the
resume relevant to the job?") would penalise a strong candidate for having
a hobbies section, which is not a real problem.

This component is weighted below skill overlap on purpose. Embeddings are
good at "this person works in roughly this field" and bad at "this person
has Airflow" -- and the second question is the one that gets resumes
filtered out of a real pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.matching.config import SEMANTIC_CEILING, SEMANTIC_FLOOR


@dataclass
class SemanticResult:
    score: float | None
    raw_similarity: float | None = None
    weakest_jd_chunks: list[tuple[int, float]] = field(default_factory=list)


def score_semantic(
    resume_vectors: np.ndarray, jd_vectors: np.ndarray
) -> SemanticResult:
    if resume_vectors.size == 0 or jd_vectors.size == 0:
        return SemanticResult(score=None)

    # Vectors are stored L2-normalised, so the dot product is cosine.
    similarity = jd_vectors @ resume_vectors.T      # (n_jd, n_resume)
    best_per_jd_chunk = similarity.max(axis=1)      # (n_jd,)
    raw = float(best_per_jd_chunk.mean())

    # Rescale. Raw MiniLM cosine between any two pieces of professional
    # English sits in a narrow band, so an unrescaled score would put every
    # pair within a few points of each other and the component would stop
    # discriminating. The band bounds live in config.py and are the most
    # provisional numbers in the engine -- calibration should replace them
    # the observed distribution across real postings rather than an
    # estimate.
    span = SEMANTIC_CEILING - SEMANTIC_FLOOR
    rescaled = (raw - SEMANTIC_FLOOR) / span if span else 0.0
    rescaled = float(min(max(rescaled, 0.0), 1.0))

    # The JD chunks the resume covers worst -- directly useful in the
    # explainability panel in the UI, since a low semantic score is
    # otherwise completely opaque to a user.
    weakest = sorted(
        ((i, float(s)) for i, s in enumerate(best_per_jd_chunk)),
        key=lambda pair: pair[1],
    )[:3]

    return SemanticResult(score=rescaled, raw_similarity=raw, weakest_jd_chunks=weakest)