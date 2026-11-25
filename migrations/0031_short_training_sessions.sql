BEGIN;
ALTER TABLE adaptive_sessions
 ADD COLUMN IF NOT EXISTS strategy text NOT NULL DEFAULT 'personal',
 ADD COLUMN IF NOT EXISTS scope jsonb NOT NULL DEFAULT '{}'::jsonb,
 ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 0;
DO $$ BEGIN
 ALTER TABLE adaptive_sessions ADD CONSTRAINT adaptive_session_strategy
 CHECK(strategy IN ('personal','mixed','number','family'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
ALTER TABLE adaptive_slots
 ADD COLUMN IF NOT EXISTS selection text NOT NULL DEFAULT 'strategy';
DO $$ BEGIN
 ALTER TABLE adaptive_slots ADD CONSTRAINT adaptive_slot_selection
 CHECK(selection IN ('strategy','similar'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE TABLE IF NOT EXISTS adaptive_session_deltas (
 session_id uuid NOT NULL REFERENCES adaptive_sessions ON DELETE CASCADE,
 position smallint NOT NULL, ordinal integer NOT NULL, skill text NOT NULL,
 before_state jsonb, after_state jsonb NOT NULL,
 reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(session_id,position,ordinal)
);
ALTER TABLE adaptive_session_deltas ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_session_deltas FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
 IF EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
 EXECUTE format('REVOKE ALL ON adaptive_session_deltas FROM %I',r);
 END IF; END LOOP; END $$;
COMMIT;
