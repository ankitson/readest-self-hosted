import { describe, expect, it } from 'vitest';

import { pickFresherMetadata } from '@/app/library/utils/libraryUtils';
import type { Book } from '@/types/book';

const book = (overrides: Partial<Book>): Book =>
  ({
    hash: 'hash',
    format: 'EPUB',
    title: 'Title',
    author: 'Author',
    createdAt: 1,
    updatedAt: 1,
    ...overrides,
  }) as Book;

describe('pickFresherMetadata', () => {
  it('chooses a dedicated metadata clock over a newer reading row clock', () => {
    const local = book({ title: 'Stale', updatedAt: 300, metadataUpdatedAt: null });
    const synced = book({ title: 'Correct', updatedAt: 100, metadataUpdatedAt: 200 });

    expect(pickFresherMetadata(local, synced).title).toBe('Correct');
  });

  it('uses updatedAt for legacy rows', () => {
    const local = book({ title: 'Old', updatedAt: 100 });
    const synced = book({ title: 'New', updatedAt: 200 });

    expect(pickFresherMetadata(local, synced).title).toBe('New');
  });
});
