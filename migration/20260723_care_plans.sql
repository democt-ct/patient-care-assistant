CREATE TABLE IF NOT EXISTS care_plans (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL REFERENCES patients(id),
    hospital_id VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_id VARCHAR(36) NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    confirmed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_care_plans_patient_id ON care_plans (patient_id);
CREATE INDEX IF NOT EXISTS ix_care_plans_hospital_id ON care_plans (hospital_id);
CREATE INDEX IF NOT EXISTS ix_care_plans_source_type ON care_plans (source_type);
CREATE INDEX IF NOT EXISTS ix_care_plans_source_id ON care_plans (source_id);
CREATE INDEX IF NOT EXISTS ix_care_plans_status ON care_plans (status);

CREATE TABLE IF NOT EXISTS care_plan_items (
    id VARCHAR(36) PRIMARY KEY,
    care_plan_id VARCHAR(36) NOT NULL REFERENCES care_plans(id) ON DELETE CASCADE,
    patient_id VARCHAR(36) NOT NULL REFERENCES patients(id),
    task_type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    instructions TEXT,
    priority VARCHAR(16) NOT NULL DEFAULT 'routine',
    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
    due_at TIMESTAMP,
    evidence_source_type VARCHAR(32) NOT NULL,
    evidence_source_id VARCHAR(36) NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    needs_patient_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_care_plan_items_care_plan_id ON care_plan_items (care_plan_id);
CREATE INDEX IF NOT EXISTS ix_care_plan_items_patient_id ON care_plan_items (patient_id);
CREATE INDEX IF NOT EXISTS ix_care_plan_items_status ON care_plan_items (status);
CREATE INDEX IF NOT EXISTS ix_care_plan_items_due_at ON care_plan_items (due_at);

CREATE TABLE IF NOT EXISTS care_plan_item_events (
    id VARCHAR(36) PRIMARY KEY,
    care_plan_item_id VARCHAR(36) NOT NULL REFERENCES care_plan_items(id) ON DELETE CASCADE,
    event_type VARCHAR(32) NOT NULL,
    note TEXT,
    actor_type VARCHAR(32) NOT NULL DEFAULT 'patient',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_care_plan_item_events_item_id ON care_plan_item_events (care_plan_item_id);
