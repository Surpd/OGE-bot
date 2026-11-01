BEGIN;

-- Keep task-12 formula practice sessions independent from all other numbers.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task12_per_user
    ON sessions (user_id) WHERE mode = 'task12' AND finished_at IS NULL;

COMMIT;
