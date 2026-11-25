BEGIN;

-- Existing archive rows are either queued already or represented in evidence.
-- Re-read the latter through the original snapshot, including replay sources.
INSERT INTO adaptive_dirty(owner, source, task)
SELECT DISTINCT owner, source, task
FROM adaptive_evidence
WHERE split_part(skill, '-', 1) IN ('PAPER', 'GARDEN', 'FLAT', 'TARIFF')
ON CONFLICT DO NOTHING;

DELETE FROM adaptive_unavailable
WHERE split_part(skill, '-', 1) IN ('PAPER', 'GARDEN', 'FLAT', 'TARIFF');

COMMIT;
