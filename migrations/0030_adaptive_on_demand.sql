BEGIN;
-- Preserve milestones already recorded under the former policy before reprojection.
CREATE TABLE IF NOT EXISTS adaptive_past_milestones (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, source text NOT NULL, task text NOT NULL,
 ordinal integer NOT NULL, policy integer NOT NULL, skill text NOT NULL, reason text NOT NULL,
 occurred timestamptz NOT NULL, PRIMARY KEY(owner,source,task,ordinal,policy)
);
INSERT INTO adaptive_past_milestones
 SELECT owner,source,task,ordinal,policy,skill,reason,occurred FROM adaptive_evidence
 WHERE policy=1 AND reason IN ('gap_opened','gap_closed','gap_reopened','skill_confirmed')
 ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS adaptive_unavailable (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, skill text NOT NULL,
 retry_after timestamptz NOT NULL, PRIMARY KEY(owner,skill)
);
ALTER TABLE adaptive_past_milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE adaptive_unavailable ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_past_milestones,adaptive_unavailable FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
 IF EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
 EXECUTE format('REVOKE ALL ON adaptive_past_milestones,adaptive_unavailable FROM %I',r);
 END IF; END LOOP; END $$;
COMMIT;
