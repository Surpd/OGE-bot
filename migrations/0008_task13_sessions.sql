BEGIN;

-- Keep task-13 inequality practice sessions independent from other numbers.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task13_per_user
    ON sessions (user_id) WHERE mode = 'task13' AND finished_at IS NULL;

COMMIT;
