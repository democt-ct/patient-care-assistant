-- Versioned Agent quality-evaluation history.
-- Raw answers are intentionally excluded: result_json contains score details
-- and an answer SHA-256 fingerprint only.

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL,
    case_id VARCHAR(100) NOT NULL,
    case_version VARCHAR(64) NOT NULL,
    scoring_version VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'completed',
    passed VARCHAR(8) NOT NULL,
    total_score DOUBLE PRECISION NOT NULL,
    duration_seconds DOUBLE PRECISION,
    model_version VARCHAR(255),
    prompt_version VARCHAR(255),
    knowledge_base_version VARCHAR(255),
    trace_id VARCHAR(64),
    result_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_evaluation_runs_run_id ON evaluation_runs (run_id);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_case_id ON evaluation_runs (case_id);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_status ON evaluation_runs (status);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_trace_id ON evaluation_runs (trace_id);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_created_at ON evaluation_runs (created_at);
