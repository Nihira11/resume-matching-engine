-- Run this once, before schema.sql, on a fresh database
-- Requires the pgvector extension available on the Postgres server
-- On most managed Postgres (Supabase, Neon, RDS w/ pgvector, local via apt/brew) this is available

CREATE EXTENSION IF NOT EXISTS vector;
