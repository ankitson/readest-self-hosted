import { describe, expect, it } from 'vitest';

import { metadataChanged, resolveMetadataMerge } from '@/pages/api/sync';
import type { DBBook } from '@/types/records';

const book = (overrides: Partial<DBBook>): DBBook =>
  ({
    user_id: 'user',
    book_hash: 'hash',
    format: 'EPUB',
    title: 'Title',
    author: 'Author',
    ...overrides,
  }) as DBBook;

describe('metadata field-level merge', () => {
  it('keeps newer server metadata when client reading progress has a newer row clock', () => {
    const client = book({
      title: 'Stale title',
      updated_at: '2026-08-13T12:00:00Z',
      metadata_updated_at: null,
    });
    const server = book({
      title: 'Correct title',
      updated_at: '2024-01-01T00:00:00Z',
      metadata_updated_at: '2026-08-13T11:00:00Z',
    });

    expect(resolveMetadataMerge(client, server).title).toBe('Correct title');
  });

  it('falls back to the legacy row clock when neither side has a metadata clock', () => {
    const client = book({ title: 'Old', updated_at: '2024-01-01T00:00:00Z' });
    const server = book({ title: 'New', updated_at: '2024-02-01T00:00:00Z' });

    expect(resolveMetadataMerge(client, server).title).toBe('New');
  });

  it('detects changed metadata values but ignores timestamp-only changes', () => {
    const server = book({ title: 'Same', metadata_updated_at: '2024-01-01T00:00:00Z' });
    expect(
      metadataChanged(
        { ...resolveMetadataMerge(server, server), metadata_updated_at: '2024-02-01T00:00:00Z' },
        server,
      ),
    ).toBe(false);
    expect(
      metadataChanged({ ...resolveMetadataMerge(server, server), title: 'Changed' }, server),
    ).toBe(true);
  });
});
