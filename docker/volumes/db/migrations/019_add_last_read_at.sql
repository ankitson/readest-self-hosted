-- Migration 019: Add a real reading-recency clock.
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
