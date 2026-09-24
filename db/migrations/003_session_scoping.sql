-- Session scoping.
--
-- Everything uploaded was previously visible to everyone who opened the
-- app, permanently. Resumes carry names, phone numbers and addresses, so
-- a shared dropdown of them is not something that can be deployed.
--
-- Each browser session now stamps what it creates with its Reflex client
-- token, and the UI only ever lists rows carrying the current token.
-- Rows are deleted on a TTL (see service.purge_expired) because no
-- "browser closed" signal is reliable -- a tab can be killed without the
-- server ever hearing about it.
--
-- Rows created before this migration keep NULL and therefore disappear
-- from the UI while remaining available to the calibration scripts,
-- which address them by id.

ALTER TABLE resumes
    ADD COLUMN IF NOT EXISTS session_token TEXT;

ALTER TABLE job_descriptions
    ADD COLUMN IF NOT EXISTS session_token TEXT;

-- every dropdown query filters on this
CREATE INDEX IF NOT EXISTS idx_resumes_session ON resumes(session_token);
CREATE INDEX IF NOT EXISTS idx_jds_session ON job_descriptions(session_token);

-- the TTL sweep orders by these
CREATE INDEX IF NOT EXISTS idx_resumes_uploaded_at ON resumes(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_jds_fetched_at ON job_descriptions(fetched_at);
