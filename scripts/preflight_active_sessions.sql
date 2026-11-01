-- Read-only release preflight. No rows are returned when all target modes are clear.
WITH duplicate_users AS (
    SELECT mode, user_id, count(*) AS active_sessions
    FROM sessions
    WHERE finished_at IS NULL
      AND mode IN ('task14', 'task13', 'task8')
    GROUP BY mode, user_id
    HAVING count(*) > 1
)
SELECT
    mode,
    count(*) AS affected_users,
    sum(active_sessions)::bigint AS affected_sessions,
    max(active_sessions)::bigint AS max_active_sessions
FROM duplicate_users
GROUP BY mode
ORDER BY CASE mode
    WHEN 'task14' THEN 1
    WHEN 'task13' THEN 2
    WHEN 'task8' THEN 3
END;
