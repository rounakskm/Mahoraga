-- Logical schemas per integration spec §4.3.
-- Tables added in subsequent phases; this migration creates the namespaces.
CREATE SCHEMA IF NOT EXISTS knowledge;    -- KB Levels 1/2/3 + embeddings
CREATE SCHEMA IF NOT EXISTS trades;       -- Trade journal
CREATE SCHEMA IF NOT EXISTS experiments;  -- Autoresearch loop metadata
CREATE SCHEMA IF NOT EXISTS strategies;   -- Pointers into git registry
CREATE SCHEMA IF NOT EXISTS audit;        -- Append-only event log
