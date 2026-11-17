BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task19_per_user
    ON sessions (user_id) WHERE mode = 'task19' AND finished_at IS NULL;
COMMIT;
