import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

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

describe('metadata clock stamping (group moves)', () => {
  it('resolves a tie to the local value, so any group mutation must stamp the clock', () => {
    // This is why every groupId/groupName/tags write has to move
    // metadataUpdatedAt: a mutation that bumps only updatedAt leaves the two
    // metadata clocks equal, the tie resolves to local, and each device keeps
    // pushing its own answer back at the other forever.
    const moved = book({ groupName: 'Philosophy', updatedAt: 300, metadataUpdatedAt: 100 });
    const peer = book({ groupName: undefined, updatedAt: 100, metadataUpdatedAt: 100 });

    expect(pickFresherMetadata(peer, moved).groupName).toBeUndefined();
    expect(pickFresherMetadata(moved, peer).groupName).toBe('Philosophy');
  });

  it('lets a stamped group move win against a stale peer', () => {
    const moved = book({ groupName: 'Philosophy', updatedAt: 300, metadataUpdatedAt: 400 });
    const peer = book({ groupName: undefined, updatedAt: 100, metadataUpdatedAt: 100 });

    expect(pickFresherMetadata(peer, moved).groupName).toBe('Philosophy');
    expect(pickFresherMetadata(moved, peer).groupName).toBe('Philosophy');
  });
});

describe('group mutation sites stamp the metadata clock', () => {
  // Source-level guard: the merge above cannot see whether the UI stamped the
  // clock, and a missed site stays silent until two devices disagree.
  const read = (file: string) => readFileSync(resolve(process.cwd(), 'src', file), 'utf-8');

  it('GroupingModal pairs every row-clock bump with a metadata-clock bump', () => {
    const source = read('app/library/components/GroupingModal.tsx');
    const rowBumps = source.match(/book\.updatedAt = Date\.now\(\)/g) ?? [];
    const metaBumps = source.match(/book\.metadataUpdatedAt = Date\.now\(\)/g) ?? [];
    expect(rowBumps.length).toBeGreaterThan(0);
    expect(metaBumps.length).toBe(rowBumps.length);
  });

  it('ingestService stamps the metadata clock when it regroups or tags a book', () => {
    const source = read('services/ingestService.ts');
    expect(source).toMatch(
      /book\.groupName = opts\.groupName;\s*\n(\s*\/\/.*\n)*\s*book\.metadataUpdatedAt = Date\.now\(\);/,
    );
    expect(source).toMatch(
      /book\.tags = \[\.\.\.tags, tag\];[\s\S]{0,200}?book\.metadataUpdatedAt = Date\.now\(\);/,
    );
  });
});
