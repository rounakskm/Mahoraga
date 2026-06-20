-- Hindsight vchord backend init (mirrors the vendored vchord variant's
-- vectorchord-init job). Runs once against a fresh hindsight DB.
-- vchord = vector index; vchord_bm25 + pg_tokenizer + the llmlingua2 tokenizer
-- = BM25 text search. Hindsight's retain/store path REQUIRES the llmlingua2
-- tokenizer (store fails with "Tokenizer not found: llmlingua2" otherwise).
CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_tokenizer CASCADE;
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;

-- create_tokenizer has no IF NOT EXISTS; wrap so re-runs are idempotent.
DO $tok$
BEGIN
  PERFORM create_tokenizer('llmlingua2', $$ model = "llmlingua2" $$);
EXCEPTION WHEN others THEN
  RAISE NOTICE 'llmlingua2 tokenizer already exists or skipped: %', SQLERRM;
END
$tok$;
