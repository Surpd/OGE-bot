BEGIN;
-- A practice session retains earlier blocks when the learner continues.
ALTER TABLE adaptive_sessions ALTER COLUMN position TYPE integer;
ALTER TABLE adaptive_slots ALTER COLUMN position TYPE integer;
ALTER TABLE adaptive_session_deltas ALTER COLUMN position TYPE integer;
COMMIT;
