-- Matching engine – schema additions
-- Run after db/schema.sql. Idempotent; safe to re-run.

-- ---------------------------------------------------------------
-- match_results: the original schema has four score columns, but the
-- scoring blend has five components. `keyword_score` is re-scoped to
-- mean specifically the BM25 free-text signal, and hard skill overlap
-- (the ATS-mirroring core) gets its own column rather than being
-- collapsed into it -- they answer different questions and the UI in
-- the UI needs to show them separately.
-- ---------------------------------------------------------------
ALTER TABLE match_results
    ADD COLUMN IF NOT EXISTS skill_overlap_score NUMERIC(5,2);

-- Full component breakdown: per-component raw scores, matched/missing
-- skill detail with required-vs-preferred flags, top BM25-contributing
-- terms, and the gap analysis. Stored at match time because the UI
-- needs "which keywords drove this score" and recomputing it in the UI
-- layer means re-loading spaCy and the embedding model per page render.
ALTER TABLE match_results
    ADD COLUMN IF NOT EXISTS score_breakdown JSONB;

-- The weights actually used for this row. Calibration will change them, and
-- components with no signal are dropped and the rest renormalized, so
-- the weights are not constant across rows -- storing them makes an old
-- score reproducible instead of mysterious.
ALTER TABLE match_results
    ADD COLUMN IF NOT EXISTS weights_used JSONB;

-- ---------------------------------------------------------------
-- Chunk-level embeddings.
-- resumes.embedding / job_descriptions.embedding stay as-is (one vector
-- per document, useful for cheap candidate retrieval in batch
-- scoring). They are NOT what the semantic score uses: a single vector
-- for a 3-page resume averages out to a generic "this is a resume"
-- direction and every pair lands around the same similarity. The
-- semantic component pools over these per-section chunks instead.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resume_chunks (
    chunk_id     SERIAL PRIMARY KEY,
    resume_id    INT REFERENCES resumes(resume_id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    chunk_text   TEXT NOT NULL,
    embedding    vector(384),
    UNIQUE(resume_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS jd_chunks (
    chunk_id     SERIAL PRIMARY KEY,
    jd_id        INT REFERENCES job_descriptions(jd_id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    chunk_text   TEXT NOT NULL,
    embedding    vector(384),
    UNIQUE(jd_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_resume_chunks_resume ON resume_chunks(resume_id);
CREATE INDEX IF NOT EXISTS idx_jd_chunks_jd ON jd_chunks(jd_id);

-- ---------------------------------------------------------------
-- Optional but recommended: ESCO URI on skills_taxonomy.
-- Gap analysis wants occupationSkillRelations (the third CSV pulled in
-- during dataset staging and so far unused), keyed by ESCO URI. Without this
-- column the join has to go through preferredLabel string matching,
-- which works but is lossy on the 21 duplicate labels that were skipped
-- with ON CONFLICT DO NOTHING during the original load.
-- Uncomment and re-run load_taxonomy.py with URI capture to use it.
-- ---------------------------------------------------------------
-- ALTER TABLE skills_taxonomy ADD COLUMN IF NOT EXISTS esco_uri TEXT;
-- CREATE INDEX IF NOT EXISTS idx_skills_taxonomy_uri ON skills_taxonomy(esco_uri);