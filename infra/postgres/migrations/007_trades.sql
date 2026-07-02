-- Phase-5 transactional trade journal. The `trades` schema was created in
-- 002_schemas.sql; this adds its tables. Applied on fresh-DB init (compose
-- mounts migrations into docker-entrypoint-initdb.d); CREATE ... IF NOT EXISTS
-- so re-running is safe. ACID here (not Hindsight) because reconciliation / tax
-- / regulatory reporting need exact tabular queries.

-- Every order the executor produces (dry-run or live-paper), with the firewall
-- reason it carried and the fill state Alpaca reports back.
CREATE TABLE IF NOT EXISTS trades.orders (
    id               BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker           TEXT NOT NULL,
    side             TEXT NOT NULL,              -- BUY / SELL
    qty              DOUBLE PRECISION NOT NULL,
    order_type       TEXT NOT NULL,              -- MARKET / LIMIT
    limit_price      DOUBLE PRECISION,
    stop_price       DOUBLE PRECISION,
    status           TEXT NOT NULL,              -- NEW / SUBMITTED / FILLED / ...
    broker_order_id  TEXT,                       -- Alpaca order id (null when dry-run)
    reason           TEXT NOT NULL,              -- the decision / firewall context
    filled_qty       DOUBLE PRECISION NOT NULL DEFAULT 0,
    filled_avg_price DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_trades_orders_ticker_ts ON trades.orders(ticker, ts);

-- Individual executions against an order (an order may fill in multiple lots).
CREATE TABLE IF NOT EXISTS trades.fills (
    id        BIGSERIAL PRIMARY KEY,
    order_id  BIGINT REFERENCES trades.orders(id),
    ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    qty       DOUBLE PRECISION NOT NULL,
    price     DOUBLE PRECISION NOT NULL
);

-- Point-in-time position snapshots for reconciliation against the broker.
CREATE TABLE IF NOT EXISTS trades.positions (
    id            BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker        TEXT NOT NULL,
    qty           DOUBLE PRECISION NOT NULL,
    avg_entry     DOUBLE PRECISION NOT NULL,
    market_value  DOUBLE PRECISION NOT NULL,
    unrealized_pl DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_positions_ticker_ts ON trades.positions(ticker, ts);

-- One daily equity / P&L row (date-keyed) for the Sharpe / drawdown metrics.
CREATE TABLE IF NOT EXISTS trades.pnl_daily (
    d             DATE PRIMARY KEY,
    equity        DOUBLE PRECISION NOT NULL,
    realized_pl   DOUBLE PRECISION NOT NULL,
    unrealized_pl DOUBLE PRECISION NOT NULL
);
