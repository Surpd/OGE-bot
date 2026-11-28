-- A metadata-only projection for a separately configured reporting login.
-- Scope the schema to current_schema() so isolated test schemas do not collide.
DO $migration$
DECLARE
    source_schema text := current_schema();
    analytics_schema text := current_schema() || '_admin';
BEGIN
    IF source_schema IS NULL THEN
        RAISE EXCEPTION 'admin analytics migration requires a configured search_path';
    END IF;
    -- Record the entry mode for new full-cycle sessions in both bot namespaces.
    -- Earlier sessions could use the same catalog under a shuffled route.
    EXECUTE format('ALTER TABLE %I.mixed_training_sessions
        ADD COLUMN IF NOT EXISTS training_mode text CHECK (training_mode = ''full_part'')',
        source_schema);

    IF octet_length(analytics_schema) > 63 THEN
        RAISE EXCEPTION 'admin analytics schema name would be truncated';
    END IF;

    IF source_schema ~ '^oge_test_bot_[0-9]+$' THEN
        RAISE NOTICE 'skipping admin analytics projections for isolated bot schema %', source_schema;
    ELSE

    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', analytics_schema);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', analytics_schema);

    -- Helpful for event-time dashboards and joins in the projections.
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_issued_time ON %I.issued_problems (issued_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_mixed_issued_time ON %I.mixed_training_problems (issued_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_scenario_issued_time ON %I.oge15_question_progress (adaptive_issued_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_attempt_time ON %I.attempts (created_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_mixed_attempt_time ON %I.mixed_training_attempts (created_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_scenario_attempt_time ON %I.oge15_attempts (created_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_written_issued ON %I.part2_issues (issued_at)', source_schema);
    EXECUTE format('CREATE INDEX IF NOT EXISTS admin_replay_time ON %I.training_error_replays (created_at)', source_schema);

    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.accounts AS
        SELECT u.id AS user_id, md5(u.telegram_user_id::text) AS identity_key,
               date_trunc('day', u.created_at) AS created_day
        FROM %I.users u
    $view$, analytics_schema, source_schema);

    EXECUTE format($view$
        CREATE OR REPLACE VIEW %1$I.tasks AS
        WITH base AS (
            SELECT 'ordinary'::text AS source, p.id::text AS task_key, p.user_id,
                   coalesce((SELECT a.strategy FROM %2$I.adaptive_slots sl
                             JOIN %2$I.adaptive_sessions a ON a.id=sl.session_id
                             WHERE sl.problem=p.id LIMIT 1), 'unknown') AS mode,
                   coalesce(substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int,
                            substring(s.mode from '^task([0-9]+)$')::int,
                            substring(p.snapshot->>'exam_number' from '^([0-9]{1,2})$')::int,
                            substring(p.snapshot->>'number' from '^([0-9]{1,2})$')::int,
                            substring(p.snapshot->>'mixed_number' from '^([0-9]{1,2})$')::int) AS number,
                   p.family_id, p.issued_at,
                   NULL::timestamptz AS skipped_at,
                   p.solution_viewed_at AS solution_at,
                   CASE WHEN p.hints_used > 0 THEN true ELSE NULL::boolean END AS hinted,
                   NULL::boolean AS novel
            FROM %2$I.issued_problems p LEFT JOIN %2$I.sessions s ON s.id=p.session_id
            WHERE p.outcome <> 'pending'
            UNION ALL
            SELECT 'mixed', p.id::text, s.user_id, coalesce(s.training_mode,'unknown'),
                   p.number::int, p.family_id,
                   p.issued_at, NULL::timestamptz,
                   p.solution_viewed_at, CASE WHEN p.hints_used>0 THEN true ELSE NULL::boolean END,
                   NULL::boolean
            FROM %2$I.mixed_training_problems p JOIN %2$I.mixed_training_sessions s ON s.id=p.session_id
            UNION ALL
        SELECT 'scenario', s.id::text || ':' || q.position::text, s.user_id,
                   'scenario_' || s.mode,
                   q.position::int,
                   coalesce(sc.snapshot->'questions'->(q.position-1)->>'family_id', sc.story_code),
                   q.adaptive_issued_at,
                   CASE WHEN q.status='skipped' THEN q.updated_at END,
                   q.solution_viewed_at, CASE WHEN q.hints_used>0 THEN true ELSE NULL::boolean END,
                   NULL::boolean
            FROM %2$I.oge15_question_progress q JOIN %2$I.oge15_sessions s ON s.id=q.session_id
            JOIN %2$I.oge15_scenarios sc ON sc.id=s.scenario_id
            WHERE q.status <> 'pending'
        ), all_tasks AS (
        SELECT * FROM base
        UNION ALL
        SELECT 'replay', r.id::text, r.user_id, 'replay', t.number, t.family_id,
               r.created_at, CASE WHEN r.status='failed' THEN r.finished_at END,
               r.solution_viewed_at, CASE WHEN r.hints_used>0 THEN true ELSE NULL::boolean END,
               NULL::boolean
        FROM %2$I.training_error_replays r
        LEFT JOIN LATERAL (
          SELECT p.family_id, coalesce(substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int,
                    substring(sess.mode from '^task([0-9]+)$')::int) AS number
          FROM %2$I.issued_problems p LEFT JOIN %2$I.sessions sess ON sess.id=p.session_id
          WHERE r.source_type='ordinary' AND p.id=r.source_id AND p.user_id=r.user_id
          UNION ALL
          SELECT p.family_id,p.number::int FROM %2$I.mixed_training_problems p
          JOIN %2$I.mixed_training_sessions s ON s.id=p.session_id
          WHERE r.source_type='mixed' AND p.id=r.source_id AND s.user_id=r.user_id
          UNION ALL
          SELECT coalesce(sc.snapshot->'questions'->(r.source_position-1)->>'family_id', sc.story_code), r.source_position::int
          FROM %2$I.oge15_sessions s JOIN %2$I.oge15_scenarios sc ON sc.id=s.scenario_id
          WHERE r.source_type='scenario' AND s.id=r.source_id AND s.user_id=r.user_id
        ) t ON true
        )
        SELECT task.source,task.task_key,task.user_id,task.mode,task.number,task.family_id,
               task.issued_at,task.skipped_at,task.solution_at,task.hinted,
               CASE WHEN task.source='replay' THEN false
                    WHEN task.source='ordinary' AND EXISTS (
                      SELECT FROM %2$I.adaptive_slots repeated
                      WHERE repeated.problem=CASE WHEN task.source='ordinary' THEN task.task_key::uuid END
                        AND repeated.selection='repeat'
                    ) THEN false
                    WHEN task.source='ordinary' AND EXISTS (
                      SELECT FROM %2$I.issued_problems current_problem
                      JOIN %2$I.issued_problems previous
                        ON previous.user_id=current_problem.user_id
                       AND previous.fingerprint=current_problem.fingerprint
                       AND previous.id<>current_problem.id
                       AND previous.issued_at<=current_problem.issued_at
                      WHERE current_problem.id=CASE WHEN task.source='ordinary'
                                THEN task.task_key::uuid END
                        AND current_problem.fingerprint<>current_problem.id::text
                        AND (previous.family_id=current_problem.family_id
                             OR task.number=19 AND previous.family_id LIKE 'OGE19-%%')
                    ) THEN false
                    WHEN own.variant IS NULL THEN NULL::boolean
                    ELSE NOT EXISTS (
                      SELECT FROM %2$I.adaptive_evidence previous
                      WHERE previous.owner=own.owner
                        AND (previous.skill=own.skill OR task.number=19 AND previous.number=19)
                        AND previous.variant=own.variant AND previous.outcome='issued'
                        AND (previous.source,previous.task)<>(own.source,own.task)
                        AND previous.occurred<=coalesce(answer.occurred,own.occurred)
                    )
               END AS novel
        FROM all_tasks task
        LEFT JOIN %2$I.adaptive_evidence own ON own.owner=task.user_id
          AND own.source=CASE WHEN task.source='ordinary'
               AND task.mode IN ('personal','mixed','number','family') THEN 'personal'
               ELSE task.source END
          AND own.task=task.task_key AND own.ordinal=0
          AND own.outcome='issued' AND own.variant<>''
        LEFT JOIN %2$I.adaptive_evidence answer
          ON (answer.owner,answer.source,answer.task,answer.ordinal)
            =(own.owner,own.source,own.task,1)
    $view$, analytics_schema, source_schema);

    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.replay_attempt_details AS
        SELECT r.id AS replay_id,r.user_id,(entry->>'attempt_no')::int AS attempt_no,
               (entry->>'is_correct')::boolean AS is_correct,
               (entry->>'used_hint')::boolean AS hinted,
               CASE WHEN (entry->>'used_hint')::boolean IS TRUE
                      OR r.solution_viewed_at <= CASE
                          WHEN entry->>'created_at' IS NOT NULL
                            THEN (entry->>'created_at')::timestamptz
                          WHEN r.status IN ('solved','failed')
                            AND (entry->>'attempt_no')::int=r.attempt_count THEN r.finished_at
                          ELSE NULL::timestamptz END THEN true
                    WHEN entry->>'used_hint'='false' THEN false
                    ELSE NULL::boolean END AS assisted,
               CASE WHEN entry->>'created_at' IS NOT NULL
                      THEN (entry->>'created_at')::timestamptz
                    WHEN r.status IN ('solved','failed')
                      AND (entry->>'attempt_no')::int=r.attempt_count THEN r.finished_at
                    ELSE NULL::timestamptz END AS created_at
        FROM %I.training_error_replays r
        CROSS JOIN LATERAL jsonb_array_elements(r.attempts) entry
    $view$, analytics_schema, source_schema);

    EXECUTE format($view$
        CREATE OR REPLACE VIEW %1$I.attempts AS
        WITH events AS (
            SELECT a.user_id,'ordinary'::text AS source,p.id::text AS task_key,
                   coalesce(ats.strategy,'unknown') AS mode,
                   coalesce(substring(s.mode from '^task([0-9]+)$')::int,
                            substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int,
                            substring(coalesce(p.snapshot->>'exam_number',p.snapshot->>'number',
                                               p.snapshot->>'mixed_number') from '^[0-9]{1,2}$')::int)
                       AS number,
                   p.family_id,a.attempt_no::int,a.is_correct AS correct,
                   CASE WHEN a.used_hint THEN true
                        WHEN a.telegram_message_id IS NULL THEN NULL::boolean
                        ELSE false END AS hinted,
                   CASE WHEN a.used_hint OR p.solution_viewed_at<=a.created_at THEN true
                        WHEN a.telegram_message_id IS NULL THEN NULL::boolean
                        ELSE false END AS assisted,
                   a.created_at
            FROM %2$I.attempts a
            JOIN %2$I.issued_problems p ON p.id=a.problem_id
            LEFT JOIN %2$I.sessions s ON s.id=p.session_id
            LEFT JOIN %2$I.adaptive_slots sl ON sl.problem=p.id
            LEFT JOIN %2$I.adaptive_sessions ats ON ats.id=sl.session_id
            UNION ALL
            SELECT s.user_id,'mixed',p.id::text,coalesce(s.training_mode,'unknown'),
                   p.number::int,p.family_id,
                   a.attempt_no::int,a.is_correct,a.used_hint,
                   a.used_hint OR coalesce(p.solution_viewed_at<=a.created_at,false),a.created_at
            FROM %2$I.mixed_training_attempts a
            JOIN %2$I.mixed_training_problems p ON p.id=a.problem_id
            JOIN %2$I.mixed_training_sessions s ON s.id=p.session_id
            UNION ALL
            SELECT s.user_id,'scenario',s.id::text||':'||a.position::text,
                   'scenario_' || s.mode,
                   a.position::int,
                   coalesce(sc.snapshot->'questions'->(a.position-1)->>'family_id',sc.story_code),
                   a.attempt_no::int,a.is_correct,a.used_hint,
                   a.used_hint OR coalesce(q.solution_viewed_at<=a.created_at,false),a.created_at
            FROM %2$I.oge15_attempts a JOIN %2$I.oge15_sessions s ON s.id=a.session_id
            JOIN %2$I.oge15_question_progress q ON q.session_id=a.session_id AND q.position=a.position
            JOIN %2$I.oge15_scenarios sc ON sc.id=s.scenario_id
            WHERE q.status<>'pending'
            UNION ALL
            SELECT t.user_id,'replay',t.task_key,'replay',t.number,t.family_id,
                   r.attempt_no,r.is_correct,r.hinted,r.assisted,r.created_at
            FROM %1$I.replay_attempt_details r
            JOIN %1$I.tasks t ON t.source='replay' AND t.task_key=r.replay_id::text
              AND t.user_id=r.user_id
        )
        SELECT e.*,
               CASE WHEN e.source='replay' THEN false
                    WHEN e.correct AND e.attempt_no=1 AND e.assisted IS FALSE THEN (
                        SELECT t.novel FROM %1$I.tasks t
                        WHERE t.source=e.source AND t.task_key=e.task_key AND t.user_id=e.user_id
                    ) END AS novel
        FROM events e
    $view$, analytics_schema, source_schema);

    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.written_issues AS
        SELECT i.id AS issue_id, u.id AS user_id, i.number, i.subtype_id,
               c.title, i.issued_at
        FROM %I.part2_issues i JOIN %I.users u ON u.telegram_user_id=i.owner
        JOIN %I.part2_subtypes c ON c.subtype_id=i.subtype_id
    $view$, analytics_schema, source_schema, source_schema, source_schema);
    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.written_checks AS
        SELECT i.id AS issue_id, g.revision, u.id AS user_id, i.number, i.subtype_id,
               c.title, g.created_at, g.status, g.score, g.cost_usd
        FROM %I.part2_grades g JOIN %I.part2_issues i ON i.id=g.issue_id
        JOIN %I.users u ON u.telegram_user_id=i.owner
        JOIN %I.part2_subtypes c ON c.subtype_id=i.subtype_id
    $view$, analytics_schema, source_schema, source_schema, source_schema, source_schema);
    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.charges AS
        SELECT false AS diagnostic, g.created_at,g.dispatched_at,g.status,g.cost_usd,g.reserved_usd
        FROM %I.part2_grades g
        UNION ALL
        SELECT true, d.created_at,d.dispatched_at,d.status,d.cost_usd,d.reserved_usd
        FROM %I.part2_api_tests d
    $view$, analytics_schema, source_schema, source_schema);
    EXECUTE format($view$
        CREATE OR REPLACE VIEW %I.operations AS
        SELECT u.claimed_at,u.status,u.bot_id FROM %I.telegram_updates u
    $view$, analytics_schema, source_schema);
    -- This time stream stays independent of the task detail and novelty joins.
    EXECUTE format($view$
        CREATE OR REPLACE VIEW %1$I.activity AS
        SELECT a.user_id,a.created_at,'ordinary'::text AS source,a.problem_id::text AS task_key
        FROM %2$I.attempts a
        UNION ALL
        SELECT s.user_id,a.created_at,'mixed',p.id::text
        FROM %2$I.mixed_training_attempts a
        JOIN %2$I.mixed_training_problems p ON p.id=a.problem_id
        JOIN %2$I.mixed_training_sessions s ON s.id=p.session_id
        UNION ALL
        SELECT s.user_id,a.created_at,'scenario',a.session_id::text||':'||a.position::text
        FROM %2$I.oge15_attempts a JOIN %2$I.oge15_sessions s ON s.id=a.session_id
        JOIN %2$I.oge15_question_progress q ON q.session_id=a.session_id AND q.position=a.position
        WHERE q.status<>'pending'
        UNION ALL
        SELECT user_id,created_at,'replay',replay_id::text
        FROM %1$I.replay_attempt_details WHERE created_at IS NOT NULL
        UNION ALL
        SELECT user_id,created_at,'written',issue_id::text FROM %1$I.written_checks
    $view$, analytics_schema, source_schema);

    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', analytics_schema);
    FOREACH source_schema IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT FROM pg_roles WHERE rolname=source_schema) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA %I FROM %I', analytics_schema, source_schema);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', analytics_schema, source_schema);
        END IF;
    END LOOP;
    END IF;
END
$migration$;
