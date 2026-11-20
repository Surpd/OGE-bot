BEGIN;
ALTER TABLE part2_versions ADD COLUMN IF NOT EXISTS reviewed boolean NOT NULL DEFAULT false;
ALTER TABLE part2_issues ADD COLUMN IF NOT EXISTS solution_viewed_at timestamptz;
ALTER TABLE part2_grades ADD COLUMN IF NOT EXISTS failure_reason text;
CREATE TABLE IF NOT EXISTS part2_api_tests (
 owner bigint NOT NULL, confirmation bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL DEFAULT 'pending',
 reserved_usd numeric NOT NULL CHECK (reserved_usd >= 0), cost_usd numeric CHECK (cost_usd >= 0),
 input_tokens integer, output_tokens integer, score smallint CHECK (score BETWEEN 0 AND 2),
 model text NOT NULL, failure_reason text, elapsed_ms integer,
 PRIMARY KEY(owner,confirmation)
);
CREATE INDEX IF NOT EXISTS part2_api_tests_month ON part2_api_tests(created_at);
ALTER TABLE part2_api_tests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON part2_api_tests FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
  REVOKE ALL ON part2_api_tests FROM anon;
 END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
  REVOKE ALL ON part2_api_tests FROM authenticated;
 END IF;
END $$;
COMMIT;
