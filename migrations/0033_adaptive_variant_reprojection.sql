BEGIN;

ALTER TABLE adaptive_slots DROP CONSTRAINT IF EXISTS adaptive_slot_selection;
ALTER TABLE adaptive_slots ADD CONSTRAINT adaptive_slot_selection
    CHECK (selection IN ('strategy', 'similar', 'repeat'));

-- Scenario signatures are derived from the immutable source snapshots. Re-read
-- archived training rows once so adaptive evidence adopts the canonical
-- semantic variant key without changing snapshots or attempts.
INSERT INTO adaptive_dirty(owner, source, task)
SELECT owner, source, task
FROM (
    SELECT user_id AS owner, 'ordinary'::text AS source, id::text AS task
    FROM issued_problems
    WHERE jsonb_typeof(snapshot->'scenario_snapshot') = 'object'

    UNION ALL
    SELECT session.user_id, 'mixed', problem.id::text
    FROM mixed_training_problems AS problem
    JOIN mixed_training_sessions AS session ON session.id = problem.session_id
    WHERE problem.number BETWEEN 1 AND 5

    UNION ALL
    SELECT session.user_id, 'scenario',
           session.id::text || ':' || progress.position::text
    FROM oge15_question_progress AS progress
    JOIN oge15_sessions AS session ON session.id = progress.session_id
    WHERE progress.status <> 'pending'

    UNION ALL
    SELECT user_id, 'replay', id::text
    FROM training_error_replays
) AS archive
ON CONFLICT (owner, source, task) DO NOTHING;

-- These are temporary generator cooldowns. A corrected signature makes old
-- exclusions irrelevant, so let the fixed planner try those skills again.
DELETE FROM adaptive_unavailable;

COMMIT;
