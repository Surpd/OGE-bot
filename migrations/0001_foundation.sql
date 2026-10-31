BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id bigint NOT NULL UNIQUE CHECK (telegram_user_id > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
    current_state jsonb NOT NULL DEFAULT '{"screen":"main_menu"}'::jsonb
);

CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode text NOT NULL,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    active_problem_id uuid
);
CREATE INDEX IF NOT EXISTS sessions_active_by_user
    ON sessions (user_id, started_at DESC) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS issued_problems (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id uuid REFERENCES sessions(id) ON DELETE SET NULL,
    family_id text NOT NULL,
    generator_version text NOT NULL,
    seed bigint,
    fingerprint text NOT NULL,
    shape_fingerprint text,
    snapshot jsonb NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS issued_problems_by_user
    ON issued_problems (user_id, issued_at DESC);
CREATE INDEX IF NOT EXISTS issued_problems_by_family
    ON issued_problems (user_id, family_id, issued_at DESC);

CREATE TABLE IF NOT EXISTS attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id uuid NOT NULL REFERENCES issued_problems(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attempt_no smallint NOT NULL CHECK (attempt_no > 0),
    raw_answer text NOT NULL,
    normalized_answer text,
    is_correct boolean NOT NULL,
    used_hint boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (problem_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS attempts_by_user ON attempts (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id bigint PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('processing', 'processed', 'failed')),
    claimed_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE issued_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_updates ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON users, sessions, issued_problems, attempts, telegram_updates FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON users, sessions, issued_problems, attempts, telegram_updates FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON users, sessions, issued_problems, attempts, telegram_updates FROM authenticated;
    END IF;
END $$;

COMMIT;
