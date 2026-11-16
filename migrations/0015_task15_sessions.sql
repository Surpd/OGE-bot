BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task15_per_user
    ON sessions (user_id) WHERE mode = 'task15' AND finished_at IS NULL;
COMMIT;
