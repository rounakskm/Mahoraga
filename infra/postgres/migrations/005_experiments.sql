-- Phase-3 Layer-1 provenance. The `experiments` + `strategies` schemas were created
-- in 002_schemas.sql; this adds their tables. Applied on fresh-DB init (compose
-- mounts migrations into docker-entrypoint-initdb.d); CREATE ... IF NOT EXISTS so
-- re-running is safe.

-- The autoresearch search audit trail: every candidate the loop evaluates (kept
-- AND discarded), with the gate reason. One row per iteration.
CREATE TABLE IF NOT EXISTS experiments.iterations (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id          TEXT NOT NULL,          -- one training run / campaign
    iteration       INTEGER NOT NULL,       -- index within the run
    candidate_hash  TEXT NOT NULL,          -- stable hash of the candidate params
    parent_hash     TEXT,                   -- lineage (null in Layer-1 mechanical loop)
    params          JSONB NOT NULL,         -- the regime -> window map
    train_sharpe    DOUBLE PRECISION,
    promoted        BOOLEAN NOT NULL,       -- passed the fortress (kept vs discarded)
    is_best         BOOLEAN NOT NULL,       -- new best in the run
    reason          TEXT NOT NULL           -- the gate verdict
);
CREATE INDEX IF NOT EXISTS idx_experiments_iterations_run      ON experiments.iterations(run_id);
CREATE INDEX IF NOT EXISTS idx_experiments_iterations_promoted ON experiments.iterations(promoted);

-- The deployment-eligible registry: promoted survivors that ALSO hold on the vault.
-- candidate_hash is unique so re-registering the same strategy is idempotent.
CREATE TABLE IF NOT EXISTS strategies.registry (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id              TEXT NOT NULL,
    candidate_hash      TEXT NOT NULL UNIQUE,
    params              JSONB NOT NULL,
    train_sharpe        DOUBLE PRECISION,
    vault_sharpe        DOUBLE PRECISION,
    vault_holds         BOOLEAN NOT NULL,
    deployment_eligible BOOLEAN NOT NULL,   -- promoted AND vault holds
    artifact_path       TEXT                -- the tracked strategies/<run>.json
);
