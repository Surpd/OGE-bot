BEGIN;
ALTER TABLE part2_issues ADD COLUMN IF NOT EXISTS prompt_message_id bigint;
COMMIT;
