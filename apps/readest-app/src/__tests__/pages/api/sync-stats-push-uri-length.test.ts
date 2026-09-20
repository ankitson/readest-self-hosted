import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';

// A real 464-row stats push failed with HTTP 500 `URI too long`, and had been
// failing on every book close for a month. The existing-row lookup passed the
// whole batch's hashes and timestamps as two PostgREST IN lists; PostgREST
// renders filters into the query string, so the GET URL carried 164 book hashes
// (32 chars each) plus 354 timestamps — about 9KB, past the gateway's limit.
//
// It was silent and self-perpetuating. `statBooks` is upserted before this
// point and commits, so stat_books kept advancing while stat_pages never moved;
// the client's pushStats only advances its push cursor after a chunk succeeds,
// so the same doomed payload was retried forever, and ReadingStatsTracker wraps
// the whole thing in runBestEffort, which swallows the rejection into a warn.
//
// The same two IN lists also formed a hash x start_time cross product that can
// exceed PostgREST's ~1000-row cap, hiding existing rows from the merge so a
// shorter duration could overwrite a longer one.

type Call = { table: string; method: string; args: unknown[] };
const calls: Call[] = [];

const makeBuilder = (table: string) => {
  const builder: Record<string, unknown> = {};
  const rec =
    (method: string) =>
    (...args: unknown[]) => {
      calls.push({ table, method, args });
      return builder;
    };
  for (const m of ['select', 'eq', 'or', 'gt', 'lt', 'in', 'is', 'order', 'range', 'upsert']) {
    builder[m] = rec(m);
  }
  // biome-ignore lint/suspicious/noThenProperty: mock PostgREST builder is intentionally thenable
  (builder as { then: unknown }).then = (resolve: (v: unknown) => void) =>
    resolve({ data: [], error: null });
  return builder;
};

const fromMock = vi.fn((table: string) => makeBuilder(table));

vi.mock('@/utils/supabase', () => ({
  createSupabaseClient: () => ({ from: fromMock }),
}));
vi.mock('@/utils/access', () => ({
  validateUserAndToken: async () => ({ user: { id: 'u1' }, token: 'tok' }),
}));

import { POST } from '@/pages/api/sync';

// Mirrors the shape that failed in production: many books, many timestamps.
const BOOKS = 164;
const PAGES_PER_BOOK = 3;
const statPages = Array.from({ length: BOOKS * PAGES_PER_BOOK }, (_, i) => ({
  book_hash: `${String(i % BOOKS).padStart(2, '0')}`.repeat(16).slice(0, 32),
  page: i,
  start_time: 1786733000 + i,
  duration: 10,
  total_pages: 400,
}));

const req = (body: unknown) =>
  new Request('https://web.readest.com/api/sync', {
    method: 'POST',
    headers: { authorization: 'Bearer tok', 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }) as unknown as NextRequest;

beforeEach(() => {
  calls.length = 0;
  fromMock.mockClear();
});

/** Rough PostgREST query-string cost of the filters applied to one lookup. */
const estimateUriLength = (filters: Call[]): number =>
  filters.reduce((n, c) => {
    const [field, value] = c.args as [string, unknown];
    const rendered = Array.isArray(value) ? value.join(',') : String(value);
    return n + String(field).length + rendered.length + 8;
  }, 0);

describe('POST /api/sync stats push — existing-row lookup stays inside gateway limits', () => {
  it('never sends a multi-kilobyte URI, however many books and timestamps are pushed', async () => {
    const res = await POST(req({ statBooks: [], statPages }));
    expect(res.status).toBe(200);

    // Split the recorded calls into one group per `select` on stat_pages.
    const lookups: Call[][] = [];
    for (const c of calls) {
      if (c.table !== 'stat_pages') continue;
      if (c.method === 'select') lookups.push([]);
      else if (c.method === 'upsert') continue;
      else if (lookups.length) lookups[lookups.length - 1]!.push(c);
    }
    expect(lookups.length).toBeGreaterThan(0);

    for (const filters of lookups) {
      // 2KB leaves generous headroom under the common 8KB gateway ceiling.
      expect(estimateUriLength(filters)).toBeLessThan(2048);
    }
  });

  it('scopes each lookup to one book so the response cannot exceed the row cap', async () => {
    await POST(req({ statBooks: [], statPages }));

    const hashFilters = calls.filter(
      (c) => c.table === 'stat_pages' && c.method === 'eq' && c.args[0] === 'book_hash',
    );
    expect(hashFilters.length).toBeGreaterThan(0);
    // A single hash per lookup: no hash x start_time cross product, so the row
    // count per response is bounded by the timestamp slice, never the product.
    for (const f of hashFilters) expect(Array.isArray(f.args[1])).toBe(false);

    const timeFilters = calls.filter(
      (c) => c.table === 'stat_pages' && c.method === 'in' && c.args[0] === 'start_time',
    );
    for (const f of timeFilters) {
      expect((f.args[1] as number[]).length).toBeLessThanOrEqual(100);
    }
  });
});
