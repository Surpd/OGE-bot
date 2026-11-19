BEGIN;

-- A replay stores only a reference to its original task. The immutable source
-- snapshots remain in issued_problems, mixed_training_problems or oge15_scenarios.
CREATE TABLE IF NOT EXISTS training_error_replays (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type text NOT NULL CHECK (source_type IN ('ordinary', 'mixed', 'scenario')),
    source_id uuid NOT NULL,
    source_position smallint NOT NULL DEFAULT 0 CHECK (source_position BETWEEN 0 AND 5),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'solved', 'failed', 'solution_viewed')),
    attempt_count smallint NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 2),
    attempts jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(attempts) = 'array'),
    hints_used smallint NOT NULL DEFAULT 0 CHECK (hints_used >= 0),
    solution_viewed_at timestamptz,
    prompt_message_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (user_id, source_type, source_id, source_position),
    CHECK (
        (source_type = 'scenario' AND source_position BETWEEN 1 AND 5)
        OR (source_type <> 'scenario' AND source_position = 0)
    ),
    CHECK ((status = 'active') = (finished_at IS NULL))
);
CREATE INDEX IF NOT EXISTS training_error_replays_by_user
    ON training_error_replays (user_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS training_error_replays_one_active_per_user
    ON training_error_replays (user_id) WHERE status = 'active';

ALTER TABLE training_error_replays ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON training_error_replays FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON training_error_replays FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON training_error_replays FROM authenticated;
    END IF;
END $$;

COMMIT;
