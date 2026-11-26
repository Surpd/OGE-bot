-- Resume a learner's most recent durable mixed cycle without scanning sessions.
CREATE INDEX IF NOT EXISTS adaptive_mixed_cycle_by_owner
    ON adaptive_sessions (owner, finished DESC NULLS FIRST, id DESC)
    WHERE strategy='mixed' AND scope ? 'mixed_rotation';
