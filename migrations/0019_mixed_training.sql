BEGIN;

CREATE TABLE IF NOT EXISTS mixed_training_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed')),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    state jsonb NOT NULL CHECK (jsonb_typeof(state) = 'object'),
    started_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CHECK ((status = 'completed') = (finished_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS mixed_training_one_open_per_user
    ON mixed_training_sessions (user_id) WHERE status <> 'completed';
CREATE INDEX IF NOT EXISTS mixed_training_by_user
    ON mixed_training_sessions (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS mixed_training_problems (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES mixed_training_sessions(id) ON DELETE CASCADE,
    number smallint NOT NULL CHECK (number BETWEEN 1 AND 19),
    family_id text NOT NULL,
    fingerprint text NOT NULL,
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    snapshot_sha256 char(64) NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    outcome text NOT NULL DEFAULT 'issued'
        CHECK (outcome IN ('issued', 'solved', 'failed', 'skipped', 'solution_viewed')),
    attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 2),
    hints_used smallint NOT NULL DEFAULT 0 CHECK (hints_used >= 0),
    prompt_message_id bigint,
    issued_at timestamptz NOT NULL DEFAULT now(),
    solution_viewed_at timestamptz
);
CREATE INDEX IF NOT EXISTS mixed_training_problems_by_session
    ON mixed_training_problems (session_id, issued_at DESC);
CREATE INDEX IF NOT EXISTS mixed_training_problems_by_fingerprint
    ON mixed_training_problems (session_id, fingerprint);

CREATE TABLE IF NOT EXISTS mixed_training_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id uuid NOT NULL REFERENCES mixed_training_problems(id) ON DELETE CASCADE,
    attempt_no smallint NOT NULL CHECK (attempt_no IN (1, 2)),
    telegram_message_id bigint NOT NULL,
    raw_answer text NOT NULL,
    is_correct boolean NOT NULL,
    used_hint boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (problem_id, attempt_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS mixed_training_attempt_message_unique
    ON mixed_training_attempts (problem_id, telegram_message_id);
CREATE INDEX IF NOT EXISTS mixed_training_attempts_by_problem
    ON mixed_training_attempts (problem_id, attempt_no);

ALTER TABLE mixed_training_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE mixed_training_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE mixed_training_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON mixed_training_sessions, mixed_training_problems,
    mixed_training_attempts FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON mixed_training_sessions, mixed_training_problems,
            mixed_training_attempts FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON mixed_training_sessions, mixed_training_problems,
            mixed_training_attempts FROM authenticated;
    END IF;
END $$;

COMMIT;
