BEGIN;
ALTER TABLE part2_issues ADD COLUMN IF NOT EXISTS skipped_at timestamptz;
ALTER TABLE part2_issues ADD COLUMN IF NOT EXISTS repeat_kind text
    CHECK (repeat_kind IN ('errors', 'skipped', 'all'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS part2_intro_seen boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS part2_open_by_number ON part2_issues(owner,number,touched_at DESC)
    WHERE NOT closed;
CREATE INDEX IF NOT EXISTS part2_owner_card ON part2_issues(owner,task_id);
DROP INDEX IF EXISTS part2_open_number;
COMMIT;
