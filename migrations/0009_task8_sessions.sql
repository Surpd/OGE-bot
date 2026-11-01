BEGIN;

-- Keep task-8 practice sessions independent from all other numbers.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task8_per_user
    ON sessions (user_id) WHERE mode = 'task8' AND finished_at IS NULL;

COMMIT;
