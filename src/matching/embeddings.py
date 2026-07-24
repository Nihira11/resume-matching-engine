"""
Sentence-transformer embeddings and pgvector persistence.

The important decision here is chunking. Embedding a whole resume as one
vector does not work: a 3-page document averages out to a generic "this is
a professional CV" direction, and every resume-JD pair then lands within a
few points of the same cosine similarity, so the component contributes
nothing but noise to the blend. Chunking per section and pooling the
per-chunk similarities keeps the signal.

Document-level embeddings are still written to resumes.embedding /
job_descriptions.embedding, because cheap whole-document retrieval is
exactly what batch leaderboard scoring needs -- they are just not what
the semantic score reads.
"""
from __future__ import annotations

import re

import numpy as np

from src.matching.config import (
    CHUNK_MIN_CHARS,
    CHUNK_TARGET_CHARS,
    EMBEDDING_MODEL,
)
from src.utils.db import get_connection

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def chunk_text(text: str) -> list[str]:
    """Split on blank lines, then greedily pack into ~CHUNK_TARGET_CHARS.

    Blank lines are the split point because the ingestion clean_text()
    deliberately preserves line structure -- section boundaries in a
    resume are almost always blank lines, and this gets section-shaped
    chunks for free without a heading classifier.

    Short trailing fragments are merged forward rather than kept: a
    12-character chunk containing just a section heading embeds to
    something meaningless and pollutes the max-pool.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for para in paragraphs:
        if not buffer:
            buffer = para
        elif len(buffer) + len(para) + 1 <= CHUNK_TARGET_CHARS:
            buffer = f"{buffer}\n{para}"
        else:
            chunks.append(buffer)
            buffer = para

    if buffer:
        if chunks and len(buffer) < CHUNK_MIN_CHARS:
            chunks[-1] = f"{chunks[-1]}\n{buffer}"
        else:
            chunks.append(buffer)

    return chunks


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings, so cosine similarity is a dot product."""
    if not texts:
        return np.zeros((0, 0))
    return get_model().encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    )


def _to_pgvector(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vector) + "]"


def embed_and_store(kind: str, doc_id: int, text: str) -> int:
    """Embed one document, write its chunks and its document vector.

    kind is 'resume' or 'jd'. Returns the number of chunks written.
    Idempotent: existing chunks for the document are replaced.
    """
    if kind not in ("resume", "jd"):
        raise ValueError("kind must be 'resume' or 'jd'")

    chunks = chunk_text(text)
    if not chunks:
        return 0

    vectors = embed_texts(chunks)
    # Mean of the normalised chunk vectors, renormalised -- a reasonable
    # document-level summary that costs no extra model calls.
    doc_vector = vectors.mean(axis=0)
    doc_vector = doc_vector / (np.linalg.norm(doc_vector) or 1.0)

    chunk_table = "resume_chunks" if kind == "resume" else "jd_chunks"
    doc_table = "resumes" if kind == "resume" else "job_descriptions"
    id_column = "resume_id" if kind == "resume" else "jd_id"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {chunk_table} WHERE {id_column} = %s", (doc_id,))
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        cur.execute(
            f"INSERT INTO {chunk_table} ({id_column}, chunk_index, chunk_text, embedding) "
            f"VALUES (%s, %s, %s, %s)",
            (doc_id, index, chunk, _to_pgvector(vector)),
        )
    cur.execute(
        f"UPDATE {doc_table} SET embedding = %s WHERE {id_column} = %s",
        (_to_pgvector(doc_vector), doc_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return len(chunks)


def load_chunk_vectors(kind: str, doc_id: int) -> np.ndarray:
    table = "resume_chunks" if kind == "resume" else "jd_chunks"
    id_column = "resume_id" if kind == "resume" else "jd_id"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT embedding FROM {table} WHERE {id_column} = %s ORDER BY chunk_index",
        (doc_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return np.zeros((0, 0))
    return np.array([_parse_pgvector(row[0]) for row in rows], dtype=float)


def _parse_pgvector(value) -> list[float]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [float(x) for x in str(value).strip("[]").split(",") if x.strip()]