BEGIN;

-- Reuse immutable issued problem snapshots and attempts while keeping each
-- student's task-6 and task-9 workout state isolated by session mode.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task9_per_user
    ON sessions (user_id) WHERE mode = 'task9' AND finished_at IS NULL;

COMMIT;
