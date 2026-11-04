BEGIN;

-- A single immutable JSON snapshot contains the shared context and all five
-- question snapshots. Per-question rows contain only progress, never a copy.
CREATE TABLE IF NOT EXISTS oge15_scenarios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    story_code text NOT NULL CHECK (story_code IN
        ('TYRES', 'PAPER', 'STOVE', 'TARIFF', 'ROUTE', 'GARDEN', 'FLAT')),
    seed bigint NOT NULL CHECK (seed >= 0),
    generator_version text NOT NULL,
    snapshot_schema_version smallint NOT NULL CHECK (snapshot_schema_version = 1),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    snapshot_sha256 char(64) NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz
);
CREATE INDEX IF NOT EXISTS oge15_scenarios_by_user
    ON oge15_scenarios (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS oge15_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scenario_id uuid NOT NULL REFERENCES oge15_scenarios(id) ON DELETE CASCADE,
    mode text NOT NULL CHECK (mode IN ('single', 'full')),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed')),
    current_position smallint NOT NULL CHECK (current_position BETWEEN 1 AND 5),
    navigation_revision bigint NOT NULL DEFAULT 0 CHECK (navigation_revision >= 0),
    control_message_id bigint,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (id, scenario_id),
    CHECK ((status = 'completed') = (finished_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS oge15_one_open_session_per_user
    ON oge15_sessions (user_id) WHERE status <> 'completed';
CREATE INDEX IF NOT EXISTS oge15_sessions_by_user
    ON oge15_sessions (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS oge15_question_progress (
    session_id uuid NOT NULL REFERENCES oge15_sessions(id) ON DELETE CASCADE,
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'solved', 'failed', 'solution_viewed', 'skipped')),
    attempt_count smallint NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 2),
    hints_used smallint NOT NULL DEFAULT 0 CHECK (hints_used >= 0),
    prompt_message_id bigint,
    solution_viewed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, position)
);

CREATE TABLE IF NOT EXISTS oge15_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL,
    position smallint NOT NULL,
    attempt_no smallint NOT NULL CHECK (attempt_no IN (1, 2)),
    telegram_message_id bigint NOT NULL,
    raw_answer text NOT NULL,
    normalized_answer text,
    is_correct boolean NOT NULL,
    used_hint boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (session_id, position)
        REFERENCES oge15_question_progress(session_id, position) ON DELETE CASCADE,
    UNIQUE (session_id, position, attempt_no),
    UNIQUE (session_id, telegram_message_id)
);
CREATE INDEX IF NOT EXISTS oge15_attempts_by_position
    ON oge15_attempts (session_id, position, created_at);

CREATE TABLE IF NOT EXISTS oge15_callback_claims (
    telegram_callback_query_id text PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES oge15_sessions(id) ON DELETE CASCADE,
    action text NOT NULL,
    claimed_at timestamptz NOT NULL DEFAULT now()
);

-- The same stored image can be referenced by multiple scenarios. No PNG bytes
-- belong in question snapshots; assets remain protected while a session is open.
CREATE TABLE IF NOT EXISTS oge15_assets (
    sha256 char(64) PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_key text NOT NULL,
    content_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS oge15_scenario_assets (
    scenario_id uuid NOT NULL REFERENCES oge15_scenarios(id) ON DELETE CASCADE,
    asset_sha256 char(64) NOT NULL REFERENCES oge15_assets(sha256) ON DELETE RESTRICT,
    PRIMARY KEY (scenario_id, asset_sha256)
);
CREATE INDEX IF NOT EXISTS oge15_scenario_assets_by_asset
    ON oge15_scenario_assets (asset_sha256);

CREATE OR REPLACE VIEW oge15_protected_assets AS
SELECT DISTINCT link.asset_sha256
FROM oge15_scenario_assets AS link
JOIN oge15_scenarios AS scenario ON scenario.id = link.scenario_id
JOIN oge15_sessions AS session ON session.scenario_id = scenario.id
WHERE session.status <> 'completed' AND scenario.archived_at IS NULL;

CREATE OR REPLACE VIEW oge15_position_stats AS
WITH question_counts AS (
    SELECT
        session.user_id,
        progress.position,
        count(*)::bigint AS issued,
        count(*) FILTER (WHERE progress.status = 'solved')::bigint AS correct,
        count(*) FILTER (WHERE progress.status = 'skipped')::bigint AS skipped,
        count(*) FILTER (WHERE progress.solution_viewed_at IS NOT NULL)::bigint AS solutions_viewed,
        coalesce(sum(progress.hints_used), 0)::bigint AS hints_used
    FROM oge15_question_progress AS progress
    JOIN oge15_sessions AS session ON session.id = progress.session_id
    WHERE progress.status <> 'pending'
    GROUP BY session.user_id, progress.position
), attempt_counts AS (
    SELECT
        session.user_id,
        attempt.position,
        count(*)::bigint AS attempts,
        count(*) FILTER (WHERE attempt.attempt_no = 1)::bigint AS first_attempts,
        count(*) FILTER (WHERE attempt.attempt_no = 2)::bigint AS second_attempts
    FROM oge15_attempts AS attempt
    JOIN oge15_sessions AS session ON session.id = attempt.session_id
    GROUP BY session.user_id, attempt.position
), position_rows AS (
    SELECT
        question_counts.user_id,
        question_counts.position,
        question_counts.issued,
        question_counts.correct,
        question_counts.skipped,
        question_counts.solutions_viewed,
        question_counts.hints_used,
        coalesce(attempt_counts.attempts, 0)::bigint AS attempts,
        coalesce(attempt_counts.first_attempts, 0)::bigint AS first_attempts,
        coalesce(attempt_counts.second_attempts, 0)::bigint AS second_attempts
    FROM question_counts
    LEFT JOIN attempt_counts USING (user_id, position)
)
SELECT * FROM position_rows
UNION ALL
SELECT
    user_id,
    0::smallint AS position,
    sum(issued)::bigint,
    sum(correct)::bigint,
    sum(skipped)::bigint,
    sum(solutions_viewed)::bigint,
    sum(hints_used)::bigint,
    sum(attempts)::bigint,
    sum(first_attempts)::bigint,
    sum(second_attempts)::bigint
FROM position_rows
GROUP BY user_id;

ALTER TABLE oge15_scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_question_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_callback_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE oge15_scenario_assets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON oge15_scenarios, oge15_sessions, oge15_question_progress,
    oge15_attempts, oge15_callback_claims, oge15_assets, oge15_scenario_assets
    FROM PUBLIC;
REVOKE ALL ON oge15_protected_assets, oge15_position_stats FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON oge15_scenarios, oge15_sessions, oge15_question_progress,
            oge15_attempts, oge15_callback_claims, oge15_assets, oge15_scenario_assets,
            oge15_protected_assets, oge15_position_stats FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON oge15_scenarios, oge15_sessions, oge15_question_progress,
            oge15_attempts, oge15_callback_claims, oge15_assets, oge15_scenario_assets,
            oge15_protected_assets, oge15_position_stats FROM authenticated;
    END IF;
END $$;

COMMIT;
