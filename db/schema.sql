-- Resume-Job Matching System – core schema
-- Run init_pgvector.sql first
-- Embedding dim = 384 to match sentence-transformers/all-MiniLM-L6-v2
-- Change the vector(384) dimension if you swap embedding models

-- Reference: skills taxonomy (seeded from ESCO)
CREATE TABLE IF NOT EXISTS skills_taxonomy (
    skill_id        SERIAL PRIMARY KEY,
    skill_name      TEXT UNIQUE NOT NULL,
    skill_category  TEXT,              -- e.g. 'technical', 'soft', 'tool', 'certification'
    source          TEXT,              -- 'ESCO', 'manual'
    aliases         TEXT[]             -- e.g. {'ml','machine-learning'} for 'machine learning'
);

-- resumes
CREATE TABLE IF NOT EXISTS resumes (
    resume_id           SERIAL PRIMARY KEY,
    uploaded_at          TIMESTAMPTZ DEFAULT now(),
    file_name            TEXT,
    raw_text             TEXT NOT NULL,
    cleaned_text          TEXT,
    embedding             vector(384),

    -- ATS parsability signals
    has_tables            BOOLEAN DEFAULT FALSE,
    has_multi_column       BOOLEAN DEFAULT FALSE,
    has_images             BOOLEAN DEFAULT FALSE,
    has_headers_footers     BOOLEAN DEFAULT FALSE,
    parsability_score      NUMERIC(5,2),   -- 0-100, higher = more ATS-safe
    parsability_flags       JSONB           -- list of specific issues found
);

CREATE TABLE IF NOT EXISTS resume_entities (
    entity_id     SERIAL PRIMARY KEY,
    resume_id      INT REFERENCES resumes(resume_id) ON DELETE CASCADE,
    entity_type    TEXT NOT NULL,   -- 'skill','title','education','years_experience','certification'
    entity_value   TEXT NOT NULL,
    skill_id       INT REFERENCES skills_taxonomy(skill_id),  -- populated if entity_type='skill'
    confidence     NUMERIC(4,3)
);

-- job descriptions
CREATE TABLE IF NOT EXISTS job_descriptions (
    jd_id            SERIAL PRIMARY KEY,
    fetched_at        TIMESTAMPTZ DEFAULT now(),
    source            TEXT,             -- 'adzuna','manual_paste'
    source_url        TEXT,
    title             TEXT,
    company           TEXT,
    location          TEXT,
    seniority_level    TEXT,             -- inferred: junior/mid/senior
    raw_text          TEXT NOT NULL,
    cleaned_text       TEXT,
    embedding          vector(384)
);

CREATE TABLE IF NOT EXISTS jd_entities (
    entity_id     SERIAL PRIMARY KEY,
    jd_id          INT REFERENCES job_descriptions(jd_id) ON DELETE CASCADE,
    entity_type    TEXT NOT NULL,   -- 'skill','title','min_years_experience','education_requirement'
    entity_value   TEXT NOT NULL,
    skill_id       INT REFERENCES skills_taxonomy(skill_id),
    is_required    BOOLEAN DEFAULT TRUE  -- required vs "nice to have"
);

-- match results
CREATE TABLE IF NOT EXISTS match_results (
    match_id             SERIAL PRIMARY KEY,
    resume_id             INT REFERENCES resumes(resume_id) ON DELETE CASCADE,
    jd_id                 INT REFERENCES job_descriptions(jd_id) ON DELETE CASCADE,
    computed_at            TIMESTAMPTZ DEFAULT now(),

    keyword_score          NUMERIC(5,2),   -- weighted highest (mirrors real ATS)
    semantic_score          NUMERIC(5,2),   -- cosine similarity, secondary signal
    title_seniority_score    NUMERIC(5,2),
    experience_match_score   NUMERIC(5,2),
    final_blended_score      NUMERIC(5,2),

    matched_skills          TEXT[],
    missing_skills           TEXT[],
    verdict                 TEXT,           -- 'likely_pass','borderline','likely_reject'

    UNIQUE(resume_id, jd_id)
);

-- indexes
CREATE INDEX IF NOT EXISTS idx_resume_entities_resume ON resume_entities(resume_id);
CREATE INDEX IF NOT EXISTS idx_jd_entities_jd ON jd_entities(jd_id);
CREATE INDEX IF NOT EXISTS idx_match_results_resume ON match_results(resume_id);
CREATE INDEX IF NOT EXISTS idx_match_results_jd ON match_results(jd_id);

-- Vector similarity indexes (IVFFlat) – build later, after data is loaded
-- CREATE INDEX ON resumes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- CREATE INDEX ON job_descriptions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);