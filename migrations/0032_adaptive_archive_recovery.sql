BEGIN;

-- Supabase's transaction pool may assign a different server session after an
-- asyncpg connection reset. A custom session GUC is therefore not a reliable
-- write-capture switch. Queueing is cheap and idempotent; projection stays
-- on-demand, so capture authoritative changes unconditionally.
CREATE OR REPLACE FUNCTION adaptive_queue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE learner uuid; ref text; src text := TG_ARGV[0];
BEGIN
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

CREATE OR REPLACE TRIGGER adaptive_question_start BEFORE INSERT OR UPDATE OF status
 ON oge15_question_progress FOR EACH ROW EXECUTE FUNCTION adaptive_question_start();
CREATE OR REPLACE TRIGGER adaptive_grade_start BEFORE INSERT ON part2_grades
 FOR EACH ROW EXECUTE FUNCTION adaptive_grade_context();

-- Source tables are authoritative.  Adaptive projection was introduced after
-- some learners already had training history, so enqueue that history once on
-- upgrade.  The queue primary key makes this safe on repeated startup runs and
-- leaves existing evidence, milestones, sessions and learner state untouched.
INSERT INTO adaptive_dirty(owner, source, task)
SELECT owner, source, task
FROM (
    SELECT user_id AS owner, 'ordinary'::text AS source, id::text AS task
    FROM issued_problems

    UNION ALL
    SELECT session.user_id, 'mixed', problem.id::text
    FROM mixed_training_problems AS problem
    JOIN mixed_training_sessions AS session ON session.id = problem.session_id

    UNION ALL
    SELECT session.user_id, 'scenario',
           session.id::text || ':' || progress.position::text
    FROM oge15_question_progress AS progress
    JOIN oge15_sessions AS session ON session.id = progress.session_id
    WHERE progress.status <> 'pending'

    UNION ALL
    SELECT app_user.id, 'written', issue.id::text
    FROM part2_issues AS issue
    JOIN users AS app_user ON app_user.telegram_user_id = issue.owner

    UNION ALL
    SELECT user_id, 'replay', id::text
    FROM training_error_replays
) AS archive
ON CONFLICT (owner, source, task) DO NOTHING;

COMMIT;
