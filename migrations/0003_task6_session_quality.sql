BEGIN;

ALTER TABLE issued_problems
    ADD COLUMN IF NOT EXISTS outcome text NOT NULL DEFAULT 'issued',
    ADD COLUMN IF NOT EXISTS solution_viewed_at timestamptz,
    ADD COLUMN IF NOT EXISTS hints_used smallint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS selection_attempts smallint NOT NULL DEFAULT 1;

ALTER TABLE attempts
    ADD COLUMN IF NOT EXISTS telegram_message_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'issued_problems_outcome_check'
    ) THEN
        ALTER TABLE issued_problems
            ADD CONSTRAINT issued_problems_outcome_check
            CHECK (outcome IN ('issued', 'solved', 'failed', 'skipped', 'solution_viewed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'issued_problems_hints_used_check'
    ) THEN
        ALTER TABLE issued_problems
            ADD CONSTRAINT issued_problems_hints_used_check CHECK (hints_used >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'issued_problems_selection_attempts_check'
    ) THEN
        ALTER TABLE issued_problems
            ADD CONSTRAINT issued_problems_selection_attempts_check
            CHECK (selection_attempts > 0);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS issued_problems_recent_fingerprint
    ON issued_problems (user_id, fingerprint, issued_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS attempts_user_telegram_message_unique
    ON attempts (user_id, telegram_message_id) WHERE telegram_message_id IS NOT NULL;

COMMIT;
