-- Follow-up state records patient acknowledgement and reminder delivery state.
-- It does not assert clinical adherence without explicit evidence.
ALTER TABLE care_plan_items
    ADD COLUMN IF NOT EXISTS follow_up_status VARCHAR(32) NOT NULL DEFAULT 'awaiting_acknowledgement',
    ADD COLUMN IF NOT EXISTS patient_acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_patient_response_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_reminded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_reminder_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reminder_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS execution_evidence_type VARCHAR(32);

CREATE INDEX IF NOT EXISTS ix_care_plan_items_follow_up_status ON care_plan_items (follow_up_status);
CREATE INDEX IF NOT EXISTS ix_care_plan_items_next_reminder_at ON care_plan_items (next_reminder_at);
