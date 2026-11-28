-- Run as a database administrator after 0038_admin_analytics.sql.
-- search_path must point first at the source schema (normally public).
DO $provision$
DECLARE
    source_schema text := current_schema();
    analytics_schema text := current_schema() || '_admin';
    source_table text;
    view_name text;
    projection_oid oid;
    owner_oid oid;
    needs_owner_transfer boolean;
    existing_role pg_roles%ROWTYPE;
    old_set boolean;
    old_inherit boolean;
    had_membership boolean := false;
    changed_membership boolean := false;
BEGIN
    IF source_schema IS NULL THEN
        RAISE EXCEPTION 'set search_path to the source schema before provisioning';
    END IF;
    IF to_regnamespace(analytics_schema) IS NULL THEN
        RAISE EXCEPTION 'analytics schema % does not exist; apply migration 0038 first', analytics_schema;
    END IF;

    PERFORM pg_advisory_xact_lock(74120609);
    SELECT * INTO existing_role FROM pg_roles WHERE rolname='oge_admin_projection';
    IF NOT FOUND THEN
        CREATE ROLE oge_admin_projection NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    ELSIF existing_role.rolcanlogin OR existing_role.rolsuper OR existing_role.rolcreatedb
       OR existing_role.rolcreaterole OR existing_role.rolreplication
       OR existing_role.rolbypassrls OR existing_role.rolinherit THEN
        ALTER ROLE oge_admin_projection NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    SELECT * INTO existing_role FROM pg_roles WHERE rolname='oge_admin_reader';
    IF NOT FOUND THEN
        CREATE ROLE oge_admin_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    ELSIF existing_role.rolcanlogin OR existing_role.rolsuper OR existing_role.rolcreatedb
       OR existing_role.rolcreaterole OR existing_role.rolreplication
       OR existing_role.rolbypassrls OR existing_role.rolinherit THEN
        ALTER ROLE oge_admin_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    SELECT oid INTO projection_oid FROM pg_roles WHERE rolname='oge_admin_projection';

    SELECT EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=analytics_schema AND c.relkind='v'
          AND c.relname IN ('tasks','attempts','charges','operations','activity')
          AND c.relowner<>projection_oid
    ) INTO needs_owner_transfer;
    IF needs_owner_transfer THEN
        SELECT m.set_option,m.inherit_option INTO old_set,old_inherit
        FROM pg_auth_members m JOIN pg_roles member_role ON member_role.oid=m.member
        WHERE m.roleid=projection_oid AND member_role.rolname=current_user;
        had_membership := FOUND;
        IF NOT had_membership THEN
            EXECUTE format('GRANT oge_admin_projection TO %I WITH SET TRUE, INHERIT TRUE', current_user);
            changed_membership := true;
        ELSIF NOT old_set THEN
            EXECUTE format('GRANT oge_admin_projection TO %I WITH SET TRUE, INHERIT %s',
                current_user, CASE WHEN old_inherit THEN 'TRUE' ELSE 'FALSE' END);
            changed_membership := true;
        END IF;
    END IF;

    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM oge_admin_reader, oge_admin_projection', source_schema);
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM oge_admin_reader, oge_admin_projection', source_schema);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO oge_admin_projection', source_schema);

    FOREACH source_table IN ARRAY ARRAY[
        'issued_problems','sessions','adaptive_slots','adaptive_sessions',
        'mixed_training_sessions','mixed_training_problems','mixed_training_attempts',
        'oge15_question_progress','oge15_sessions','oge15_scenarios','oge15_attempts',
        'training_error_replays','adaptive_evidence','attempts','part2_grades',
        'part2_api_tests','telegram_updates'
    ] LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', source_schema, source_table);
        EXECUTE format('DROP POLICY IF EXISTS admin_analytics_projection_read ON %I.%I', source_schema, source_table);
        EXECUTE format('CREATE POLICY admin_analytics_projection_read ON %I.%I FOR SELECT TO oge_admin_projection USING (true)', source_schema, source_table);
    END LOOP;

    EXECUTE format('GRANT SELECT (id,user_id,family_id,session_id,issued_at,outcome,solution_viewed_at,hints_used,snapshot,fingerprint) ON %I.issued_problems TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,mode) ON %I.sessions TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (problem,session_id,selection) ON %I.adaptive_slots TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,strategy) ON %I.adaptive_sessions TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,user_id,training_mode) ON %I.mixed_training_sessions TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,session_id,number,family_id,issued_at,outcome,solution_viewed_at,hints_used) ON %I.mixed_training_problems TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (problem_id,attempt_no,is_correct,used_hint,created_at) ON %I.mixed_training_attempts TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (session_id,position,status,adaptive_issued_at,updated_at,solution_viewed_at,hints_used) ON %I.oge15_question_progress TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,user_id,scenario_id,mode) ON %I.oge15_sessions TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,story_code,snapshot) ON %I.oge15_scenarios TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (session_id,position,attempt_no,is_correct,used_hint,created_at) ON %I.oge15_attempts TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (id,user_id,source_type,source_id,source_position,status,created_at,finished_at,solution_viewed_at,hints_used,attempt_count) ON %I.training_error_replays TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (owner,source,task,skill,number,variant,occurred,ordinal,outcome) ON %I.adaptive_evidence TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (problem_id,user_id,attempt_no,is_correct,used_hint,telegram_message_id,created_at) ON %I.attempts TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (issue_id,revision,created_at,dispatched_at,status,score,cost_usd,reserved_usd) ON %I.part2_grades TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (created_at,dispatched_at,status,cost_usd,reserved_usd) ON %I.part2_api_tests TO oge_admin_projection', source_schema);
    EXECUTE format('GRANT SELECT (claimed_at,status,bot_id) ON %I.telegram_updates TO oge_admin_projection', source_schema);

    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', analytics_schema);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM oge_admin_reader, oge_admin_projection', analytics_schema);
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO oge_admin_projection', analytics_schema);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO oge_admin_reader', analytics_schema);
    IF NOT EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=analytics_schema AND c.relkind='v'
          AND c.relowner=projection_oid
    ) THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM oge_admin_reader, oge_admin_projection', analytics_schema);
    END IF;

    EXECUTE format('GRANT SELECT ON %I.accounts, %I.written_issues, %I.written_checks, %I.replay_attempt_details TO oge_admin_projection',
        analytics_schema, analytics_schema, analytics_schema, analytics_schema);
    IF needs_owner_transfer THEN
        EXECUTE format('GRANT SELECT ON %I.accounts, %I.tasks, %I.attempts, %I.written_issues, %I.written_checks, %I.charges, %I.operations, %I.activity TO oge_admin_reader',
            analytics_schema, analytics_schema, analytics_schema, analytics_schema,
            analytics_schema, analytics_schema, analytics_schema, analytics_schema);
    ELSE
        EXECUTE format('GRANT SELECT ON %I.accounts, %I.written_issues, %I.written_checks TO oge_admin_reader',
            analytics_schema, analytics_schema, analytics_schema);
    END IF;
    FOREACH view_name IN ARRAY ARRAY['tasks','attempts','charges','operations','activity'] LOOP
        EXECUTE format('SELECT relowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%L AND c.relname=%L',
            analytics_schema, view_name) INTO owner_oid;
        IF owner_oid<>projection_oid THEN
            EXECUTE format('ALTER VIEW %I.%I OWNER TO oge_admin_projection', analytics_schema, view_name);
        END IF;
    END LOOP;
    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM oge_admin_projection', analytics_schema);
    IF changed_membership THEN
        IF had_membership THEN
            EXECUTE format('GRANT oge_admin_projection TO %I WITH SET %s, INHERIT %s',
                current_user, CASE WHEN old_set THEN 'TRUE' ELSE 'FALSE' END,
                CASE WHEN old_inherit THEN 'TRUE' ELSE 'FALSE' END);
        ELSE
            EXECUTE format('REVOKE oge_admin_projection FROM %I', current_user);
        END IF;
    END IF;
END
$provision$;
