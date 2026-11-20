BEGIN;
ALTER TABLE part2_grades ADD COLUMN IF NOT EXISTS dispatched_at timestamptz;
ALTER TABLE part2_api_tests ADD COLUMN IF NOT EXISTS dispatched_at timestamptz;
ALTER TABLE part2_work ADD COLUMN IF NOT EXISTS superseded boolean NOT NULL DEFAULT false;
COMMIT;
