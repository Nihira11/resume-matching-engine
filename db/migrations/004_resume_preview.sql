-- First-page thumbnail of an uploaded resume.
--
-- Stored on the row rather than as a file on disk so that it shares the
-- resume's lifecycle: ON DELETE it goes too, which matters now that
-- session data is swept on a TTL. A directory of orphaned page images
-- would outlive the data it belongs to.
--
-- ~100-200KB per resume at the render settings in src/ingestion/preview.py.
-- NULL for DOCX uploads and for anything that failed to render.

ALTER TABLE resumes
    ADD COLUMN IF NOT EXISTS preview_png BYTEA;
