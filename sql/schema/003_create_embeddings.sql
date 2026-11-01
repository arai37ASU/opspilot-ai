-- Embeddings of ticket descriptions, for similarity search.
--
-- One row per distinct description, because many tickets share the same text.
-- This table is kept when the tickets are reloaded: embeddings are slow to
-- build and depend only on the text, so a rerun of `python -m
-- opspilot.ai.embed_tickets` only has to add new descriptions.
--
-- The size must match the embedding model in src/opspilot/ai/embeddings.py.
-- There is no vector index: a full scan of this many rows is fast, and it is
-- exact, where an approximate index would trade accuracy for speed not needed here.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS description_embeddings (
    description TEXT PRIMARY KEY,
    embedding   vector(384) NOT NULL
);
