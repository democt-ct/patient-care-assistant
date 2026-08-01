ALTER TABLE care_plan_items
    ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_care_plan_items_snoozed_until
    ON care_plan_items (snoozed_until);

CREATE TABLE IF NOT EXISTS care_cases (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL REFERENCES patients(id),
    hospital_id VARCHAR(64) NOT NULL,
    care_plan_item_id VARCHAR(36) NOT NULL REFERENCES care_plan_items(id) ON DELETE CASCADE,
    reason VARCHAR(64) NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'routine',
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    patient_note TEXT,
    coordinator_note TEXT,
    assignee_id VARCHAR(64),
    acknowledged_at TIMESTAMP,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_care_cases_patient_id ON care_cases (patient_id);
CREATE INDEX IF NOT EXISTS ix_care_cases_hospital_id ON care_cases (hospital_id);
CREATE INDEX IF NOT EXISTS ix_care_cases_care_plan_item_id ON care_cases (care_plan_item_id);
CREATE INDEX IF NOT EXISTS ix_care_cases_status ON care_cases (status);
