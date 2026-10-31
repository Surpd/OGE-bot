BEGIN;

-- Keep task-10 practice sessions independent from task 6 and task 9.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active_task10_per_user
    ON sessions (user_id) WHERE mode = 'task10' AND finished_at IS NULL;

COMMIT;
