-- Knowledge provenance and clinical-review metadata.
-- Apply to PostgreSQL before deploying code that reads these columns.

ALTER TABLE memory_knowledge_chunks
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS evidence_level VARCHAR(32) NOT NULL DEFAULT 'unrated',
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'unreviewed',
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_memory_knowledge_chunks_review_status
    ON memory_knowledge_chunks (review_status);

CREATE INDEX IF NOT EXISTS ix_memory_knowledge_chunks_source_id
    ON memory_knowledge_chunks (source_id);
