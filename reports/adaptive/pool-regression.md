# Adaptive projection: pool and archive regression

## Incident result

Production read-only aggregates showed six completed personal issued problems
and seven attempts, while `adaptive_dirty`, `adaptive_evidence`, and
`adaptive_skills` were all empty. Migration 0029 and all public adaptive
triggers were present. The trigger function gated capture on the session GUC
`bop.adaptive=on`.

A fresh direct PostgreSQL 17 instance on port 56435 retained the startup GUC
across asyncpg acquire/release reset cycles. The exact GUC value on the backend
that handled the historical production writes is no longer independently
observable. However, the source rows, empty queue, installed triggers, and the
trigger's only early-return condition strongly isolate a missing GUC on those
writes (or an equivalent pooled-session loss) as the cause. The direct-server
test therefore did not prove the deployed connection boundary safe.

There was a second upgrade-time gap: forward-only triggers do not enqueue rows
already present before migration 0029.

## Recovery

Migration 0032 removes the session-GUC gate from cheap idempotent capture and
also performs an idempotent enqueue from the authoritative archive.
It does not insert projected evidence or synthesize answers. Existing evidence,
skills, milestones, sessions, learner histories, and indexes are preserved.
The `(owner, source, task)` primary key makes repeated migration execution safe.
Projection remains on-demand through the existing per-learner transaction lock.
Applying the migration while the feature UI is disabled only fills
`adaptive_dirty`; it does not call `sync`, create evidence/skills, grade written
work, invoke a model, or touch grading budgets. Source issued/attempt rows are
unchanged by the regression test.

## Event-source audit

| Training mode | Authoritative source queued | Normalizer |
|---|---|---|
| ordinary №1–19 | `issued_problems` (+ `attempts`) | `ordinary`; derives number/family/snapshot |
| personal | same ordinary problem linked by `adaptive_slots` | normalized to `personal`, without a second result |
| mixed | `mixed_training_problems` (+ attempts) | `mixed`; owner comes from mixed session |
| scenario №1–5 | non-pending question progress (+ attempts) | `scenario`; owner and position scoped to session |
| written №20–25 | `part2_issues` (+ grades/reviews) | `written`; uncertain grades remain ungraded |
| error replay | `training_error_replays` | `replay`; resolves and reuses the original normalized item |

All paths are owner-scoped. Existing normalized-source tests cover mixed,
scenario, written, replay, and personal behavior; the added PostgreSQL
regression covers archive recovery plus real pool reset/trigger behavior without
manually populating adaptive projection tables.

## Local verification

- PostgreSQL 17 disposable cluster: `127.0.0.1:56435`.
- Migration 0032 executed twice: one queue row, no duplicates.
- On-demand read projected the pre-existing ordinary result into OGE09-L1.
- Three separate issue and answer transactions in an asyncpg 1–5 connection pool
  kept capturing results after release and reuse without `bop.adaptive`.
  The normal personal session flow created three new evidence records.
