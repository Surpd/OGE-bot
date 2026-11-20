BEGIN;
CREATE TABLE IF NOT EXISTS part2_grades (
    issue_id bigint REFERENCES part2_issues, revision integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), model text NOT NULL,
    prompt_version text NOT NULL, rubric_version integer NOT NULL,
    status text NOT NULL CHECK(status IN ('pending','graded','unreadable','uncertain','error')),
    score smallint CHECK(score BETWEEN 0 AND 2),
    result jsonb, input_tokens integer, output_tokens integer,
    reserved_usd numeric NOT NULL CHECK(reserved_usd >= 0), cost_usd numeric,
    PRIMARY KEY(issue_id,revision),
    CHECK ((status='graded') = (score IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS part2_grade_month ON part2_grades(created_at);
ALTER TABLE part2_grades ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON part2_grades FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON part2_grades FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON part2_grades FROM authenticated;
    END IF;
END $$;

COMMIT;
