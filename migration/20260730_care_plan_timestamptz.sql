-- Care-plan timestamps were historically stored as UTC-naive TIMESTAMP values.
-- Interpret existing values as UTC while converting PostgreSQL columns to TIMESTAMPTZ.

ALTER TABLE care_plans
    ALTER COLUMN confirmed_at TYPE TIMESTAMPTZ USING confirmed_at AT TIME ZONE 'UTC',
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE care_plan_items
    ALTER COLUMN due_at TYPE TIMESTAMPTZ USING due_at AT TIME ZONE 'UTC',
    ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING completed_at AT TIME ZONE 'UTC',
    ALTER COLUMN snoozed_until TYPE TIMESTAMPTZ USING snoozed_until AT TIME ZONE 'UTC',
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE care_plan_item_events
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';

ALTER TABLE care_cases
    ALTER COLUMN acknowledged_at TYPE TIMESTAMPTZ USING acknowledged_at AT TIME ZONE 'UTC',
    ALTER COLUMN resolved_at TYPE TIMESTAMPTZ USING resolved_at AT TIME ZONE 'UTC',
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC',
