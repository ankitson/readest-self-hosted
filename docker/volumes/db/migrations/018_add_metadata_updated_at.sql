-- Migration 018: Add `metadata_updated_at` to books
--
-- Field-level last-writer-wins for title, author, tags, and metadata. The
-- books row's updated_at is dominated by page-turn progress, so whole-row LWW
-- lets a reading device push stale metadata back over an edit.

ALTER TABLE public.books
  ADD COLUMN IF NOT EXISTS metadata_updated_at timestamp with time zone NULL;
