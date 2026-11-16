-- Independent active session per user for regular OGE №17 practice.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task17_per_user
    ON sessions (user_id) WHERE mode = 'task17' AND finished_at IS NULL;
