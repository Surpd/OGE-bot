BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sessions_active_problem_id_fkey'
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT sessions_active_problem_id_fkey
            FOREIGN KEY (active_problem_id) REFERENCES issued_problems(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task6_per_user
    ON sessions (user_id) WHERE mode = 'task6' AND finished_at IS NULL;

COMMIT;
