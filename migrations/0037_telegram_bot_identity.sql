-- Zero preserves rows whose original Telegram bot cannot be identified reliably.
ALTER TABLE telegram_updates ADD COLUMN IF NOT EXISTS bot_id bigint NOT NULL DEFAULT 0;
ALTER TABLE telegram_updates DROP CONSTRAINT telegram_updates_pkey,
    ADD PRIMARY KEY (bot_id, update_id);

ALTER TABLE attempts ADD COLUMN IF NOT EXISTS bot_id bigint NOT NULL DEFAULT 0;
DROP INDEX IF EXISTS attempts_user_telegram_message_unique;
CREATE UNIQUE INDEX attempts_user_telegram_message_unique
    ON attempts (user_id, bot_id, telegram_message_id) WHERE telegram_message_id IS NOT NULL;

ALTER TABLE oge15_attempts ADD COLUMN IF NOT EXISTS bot_id bigint NOT NULL DEFAULT 0;
ALTER TABLE oge15_attempts
    DROP CONSTRAINT IF EXISTS oge15_attempts_session_id_telegram_message_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS oge15_attempts_session_bot_message_unique
    ON oge15_attempts (session_id, bot_id, telegram_message_id);

ALTER TABLE mixed_training_attempts ADD COLUMN IF NOT EXISTS bot_id bigint NOT NULL DEFAULT 0;
DROP INDEX IF EXISTS mixed_training_attempt_message_unique;
CREATE UNIQUE INDEX mixed_training_attempt_message_unique
    ON mixed_training_attempts (problem_id, bot_id, telegram_message_id);

ALTER TABLE part2_work ADD COLUMN IF NOT EXISTS bot_id bigint NOT NULL DEFAULT 0;
ALTER TABLE part2_work DROP CONSTRAINT part2_work_pkey,
    ADD PRIMARY KEY (issue_id, bot_id, message_id);
