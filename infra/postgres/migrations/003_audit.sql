-- Hash-chained audit log per architecture spec §7.1.
-- Halt events (architecture spec §5.6) are written here for the
-- Postgres-poll fallback path.
CREATE TABLE IF NOT EXISTS audit.events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    payload     JSONB,
    prev_hash   BYTEA,
    hash        BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_ts     ON audit.events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit.events(action);
