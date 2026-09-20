-- Migration 901: Add a real reading-recency clock.  [FORK-LOCAL]
--
-- Numbered in the 9xx range on purpose. Fork-local migrations must never take
-- a number upstream might also use: this file was 019 and collided head-on
-- with upstream's own 019_stat_pages_upsert_rpc.sql at the 0.12.8 merge. The
-- applier keys its ledger on the full filename so both could coexist, but the
-- number then tells you nothing about order. 900 is the local plan-claim hook;
-- keep every future fork-local migration at 9xx.
--
-- Safe to re-apply: the column add is IF NOT EXISTS and the backfill only
-- touches rows where last_read_at IS NULL.
--
-- updated_at is a general row/version clock and is advanced by operations
-- unrelated to reading. last_read_at drives the Date Read sort independently.

ALTER TABLE public.books
  ADD COLUMN IF NOT EXISTS last_read_at timestamp with time zone NULL;

WITH decoded AS (
  SELECT
    user_id,
    book_hash,
    CASE
      WHEN metadata IS NULL THEN NULL::jsonb
      WHEN json_typeof(metadata) = 'string' THEN (metadata #>> '{}')::jsonb
      ELSE metadata::jsonb
    END AS value
  FROM public.books
)
UPDATE public.books AS books
SET last_read_at = COALESCE(
  to_timestamp(NULLIF(decoded.value #>> '{appleBooks,lastReadAt}', '')::double precision / 1000.0),
  books.updated_at,
  books.created_at,
  now()
)
FROM decoded
WHERE books.user_id = decoded.user_id
  AND books.book_hash = decoded.book_hash
  AND books.last_read_at IS NULL;
