BEGIN;

-- Keep task-11 graph matching sessions independent from other task numbers.
-- Immutable graph snapshots (including PNG bytes, renderer version and image hash),
-- attempts, hints and outcomes use the shared issued_problems/session tables.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task11_per_user
    ON sessions (user_id) WHERE mode = 'task11' AND finished_at IS NULL;

COMMIT;
