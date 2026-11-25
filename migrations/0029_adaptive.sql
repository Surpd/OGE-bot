BEGIN;
-- Small transactional work list. Source attempts and snapshots remain authoritative.
CREATE TABLE IF NOT EXISTS adaptive_dirty (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, source text NOT NULL,
 task text NOT NULL, PRIMARY KEY(owner,source,task)
);
CREATE TABLE IF NOT EXISTS adaptive_evidence (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, skill text NOT NULL,
 number smallint NOT NULL, source text NOT NULL, task text NOT NULL, ordinal smallint NOT NULL,
 variant text NOT NULL, occurred timestamptz NOT NULL, outcome text NOT NULL,
 assisted boolean, attempt smallint NOT NULL, score smallint, grade_status text,
 reason text, stage_after text, policy integer,
 PRIMARY KEY(owner,source,task,ordinal)
);
CREATE INDEX IF NOT EXISTS adaptive_evidence_skill ON adaptive_evidence(owner,skill,occurred);
CREATE INDEX IF NOT EXISTS adaptive_seen ON adaptive_evidence(owner,skill,variant,occurred)
 WHERE outcome='issued';
CREATE TABLE IF NOT EXISTS adaptive_skills (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, skill text NOT NULL, number smallint NOT NULL,
 state jsonb NOT NULL, latest timestamptz NOT NULL, policy integer NOT NULL, PRIMARY KEY(owner,skill)
);
CREATE TABLE IF NOT EXISTS adaptive_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner uuid NOT NULL REFERENCES users ON DELETE CASCADE,
 plan jsonb NOT NULL, position smallint NOT NULL DEFAULT 0, problem uuid REFERENCES issued_problems,
 prompt bigint, finished timestamptz, completed boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS adaptive_slots (
 session_id uuid NOT NULL REFERENCES adaptive_sessions ON DELETE CASCADE,
 position smallint NOT NULL, problem uuid UNIQUE NOT NULL REFERENCES issued_problems ON DELETE CASCADE,
 PRIMARY KEY(session_id,position)
);
ALTER TABLE adaptive_slots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_slots FROM PUBLIC;
CREATE UNIQUE INDEX IF NOT EXISTS adaptive_open ON adaptive_sessions(owner) WHERE finished IS NULL;
ALTER TABLE part2_grades ADD COLUMN IF NOT EXISTS adaptive_helped boolean;
CREATE TABLE IF NOT EXISTS adaptive_origins (
 owner uuid NOT NULL REFERENCES users ON DELETE CASCADE, source text NOT NULL, task text NOT NULL,
 original_source text NOT NULL, original_task text NOT NULL, PRIMARY KEY(owner,source,task)
);
ALTER TABLE adaptive_origins ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_origins FROM PUBLIC;
CREATE OR REPLACE VIEW adaptive_learning_events WITH (security_invoker=true) AS
 SELECT e.*,CASE WHEN o.task IS NOT NULL THEN 'similar' ELSE e.source END AS activity,
 COALESCE(o.original_source,r.source_type,e.source) AS original_source,
 COALESCE(o.original_task,r.source_id::text ||
   CASE WHEN r.source_type='scenario' THEN ':'||r.source_position ELSE '' END,e.task) AS original_task
 FROM adaptive_evidence e LEFT JOIN adaptive_origins o USING(owner,source,task)
 LEFT JOIN training_error_replays r ON e.source='replay' AND r.user_id=e.owner AND r.id::text=e.task;
REVOKE ALL ON adaptive_learning_events FROM PUBLIC;
CREATE OR REPLACE FUNCTION adaptive_grade_context() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 SELECT i.hints>0 OR i.solution_viewed_at IS NOT NULL INTO NEW.adaptive_helped
 FROM part2_issues i WHERE i.id=NEW.issue_id;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER adaptive_grade_start BEFORE INSERT ON part2_grades FOR EACH ROW
 WHEN (current_setting('bop.adaptive',true)='on') EXECUTE FUNCTION adaptive_grade_context();
CREATE OR REPLACE FUNCTION adaptive_queue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE learner uuid; ref text; src text := TG_ARGV[0];
BEGIN
 IF current_setting('bop.adaptive',true) IS DISTINCT FROM 'on' THEN RETURN NULL; END IF;
 CASE TG_TABLE_NAME
 WHEN 'issued_problems' THEN learner:=NEW.user_id; ref:=NEW.id::text;
 WHEN 'attempts' THEN learner:=NEW.user_id; ref:=NEW.problem_id::text;
 WHEN 'mixed_training_problems' THEN
   SELECT user_id INTO learner FROM mixed_training_sessions WHERE id=NEW.session_id;
   ref:=NEW.id::text;
 WHEN 'mixed_training_attempts' THEN
   SELECT s.user_id INTO learner FROM mixed_training_sessions s JOIN mixed_training_problems p
     ON p.session_id=s.id WHERE p.id=NEW.problem_id;
   ref:=NEW.problem_id::text;
 WHEN 'oge15_question_progress','oge15_attempts' THEN
   SELECT user_id INTO learner FROM oge15_sessions WHERE id=NEW.session_id;
   ref:=NEW.session_id::text || ':' || NEW.position;
 WHEN 'training_error_replays' THEN learner:=NEW.user_id; ref:=NEW.id::text;
 WHEN 'part2_issues' THEN
   SELECT id INTO learner FROM users WHERE telegram_user_id=NEW.owner; ref:=NEW.id::text;
 WHEN 'part2_grades' THEN
   SELECT u.id INTO learner FROM users u JOIN part2_issues i ON i.owner=u.telegram_user_id
    WHERE i.id=NEW.issue_id; ref:=NEW.issue_id::text;
 END CASE;
 INSERT INTO adaptive_dirty VALUES(learner,src,ref) ON CONFLICT(owner,source,task)
 DO UPDATE SET task=excluded.task;
 RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF outcome,solution_viewed_at ON issued_problems
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('ordinary');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT ON attempts
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('ordinary');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF outcome,solution_viewed_at ON mixed_training_problems
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('mixed');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT ON mixed_training_attempts
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('mixed');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF status ON oge15_question_progress
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('scenario');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT ON oge15_attempts
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('scenario');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF solution_viewed_at ON part2_issues
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('written');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF status ON part2_grades
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('written');
CREATE OR REPLACE TRIGGER adaptive_change AFTER INSERT OR UPDATE OF status,attempt_count ON training_error_replays
 FOR EACH ROW EXECUTE FUNCTION adaptive_queue('replay');
ALTER TABLE adaptive_dirty ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_dirty FROM PUBLIC;
ALTER TABLE adaptive_evidence ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_evidence FROM PUBLIC;
ALTER TABLE adaptive_skills ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_skills FROM PUBLIC;
ALTER TABLE adaptive_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON adaptive_sessions FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
 IF EXISTS(SELECT FROM pg_roles WHERE rolname=role_name) THEN
 EXECUTE format('REVOKE ALL ON adaptive_dirty,adaptive_evidence,adaptive_skills,adaptive_sessions,adaptive_slots,adaptive_origins,adaptive_learning_events FROM %I',role_name);
 END IF; END LOOP; END $$;
COMMIT;
