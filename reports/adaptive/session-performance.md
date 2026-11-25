# Short-session persistence performance

Measured locally on the disposable PostgreSQL 17 instance on 2026-11-25.

| Operation | Samples | Median | p95 |
|---|---:|---:|---:|
| PR #110 baseline: resume existing session | 40 | 2.076 ms | — |
| Current: resume existing five-position session | 40 | 2.014 ms | — |

The paired measurement alternated the baseline and current implementation against the same
pool, schema, active session and local database. It includes pool acquisition, owner row
locking, foreground-state update, and transaction commit; Telegram and generation are excluded.
The ~3% difference is below the precision appropriate for a local microbenchmark, so the result
supports parity rather than a speedup claim.
