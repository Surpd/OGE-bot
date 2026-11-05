BEGIN;

-- A user may keep one unfinished session for each story/mode combination,
-- with at most one of those sessions accepting answers at a time.
ALTER TABLE oge15_sessions
    ADD COLUMN IF NOT EXISTS story_code text;
ALTER TABLE oge15_sessions
    ADD COLUMN IF NOT EXISTS last_used_at timestamptz NOT NULL DEFAULT now();

UPDATE oge15_sessions AS session
SET story_code = scenario.story_code
FROM oge15_scenarios AS scenario
WHERE scenario.id = session.scenario_id AND session.story_code IS NULL;

ALTER TABLE oge15_sessions ALTER COLUMN story_code SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'oge15_sessions_story_code_check'
          AND conrelid = 'oge15_sessions'::regclass
    ) THEN
        ALTER TABLE oge15_sessions
            ADD CONSTRAINT oge15_sessions_story_code_check
            CHECK (story_code IN ('TYRES', 'PAPER', 'STOVE', 'TARIFF', 'ROUTE', 'GARDEN', 'FLAT'));
    END IF;
END $$;

DROP INDEX IF EXISTS oge15_one_open_session_per_user;

CREATE UNIQUE INDEX IF NOT EXISTS oge15_one_open_session_per_story_mode
    ON oge15_sessions (user_id, story_code, mode) WHERE status <> 'completed';
CREATE UNIQUE INDEX IF NOT EXISTS oge15_one_foreground_session_per_user
    ON oge15_sessions (user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS oge15_sessions_by_last_use
    ON oge15_sessions (user_id, last_used_at DESC, id DESC) WHERE status <> 'completed';

COMMIT;
