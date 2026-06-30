# Strategy registry

Deployment-eligible strategies discovered by the autoresearch loop — promoted by
the Phase-2 fortress AND held up on the held-out vault. Each `<run_id>.json` is one
survivor (params + provenance + train/vault Sharpe). The loop writes them here; the
durable, queryable record is Postgres `strategies.registry` (see
`infra/postgres/migrations/005_experiments.sql`). Committing/tagging promoted
strategies to a branch namespace is a later (Layer-3 / operator) step.
