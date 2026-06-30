-- Phase-3 Layer-3: the atomic master pointer. A singleton row (id=1) holding the
-- current promoted-best candidate_hash + its fitness. promote_pipeline does a
-- compare-and-set against this row under SERIALIZABLE, giving race-free parallel
-- Hunter promotion (only a strictly-higher fitness wins). IF NOT EXISTS = safe re-run.
CREATE TABLE IF NOT EXISTS strategies.master (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    candidate_hash  TEXT,
    fitness         DOUBLE PRECISION NOT NULL DEFAULT '-Infinity',
    run_id          TEXT,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO strategies.master (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
-- iterations gains the fitness it ranks on (Layer-1 stored only train_sharpe).
ALTER TABLE experiments.iterations ADD COLUMN IF NOT EXISTS fitness DOUBLE PRECISION;
