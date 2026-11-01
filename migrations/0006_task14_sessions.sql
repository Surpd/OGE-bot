BEGIN;

-- Keep task-14 progression practice sessions independent from other numbers.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task14_per_user
    ON sessions (user_id) WHERE mode = 'task14' AND finished_at IS NULL;

COMMIT;
