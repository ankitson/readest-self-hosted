import { describe, expect, it } from 'vitest';

import { formatAuthors } from '@/utils/book';

describe('formatAuthors list style', () => {
  it('joins authors with commas, not a conjunction', () => {
    expect(formatAuthors(['Ada Lovelace', 'Grace Hopper', 'Alan Turing'], 'en')).toBe(
      'Ada Lovelace, Grace Hopper, Alan Turing',
    );
    expect(formatAuthors(['Ada Lovelace', 'Grace Hopper'], 'en')).toBe(
      'Ada Lovelace, Grace Hopper',
    );
  });

  it('sorts each author individually — the reason authors must be stored as an array', () => {
    // A pre-joined string is split on spaces by formatAuthorName, so the last
    // WORD of the whole string is hoisted: "Weinersmith, Kelly Weinersmith, Zach".
    expect(formatAuthors(['Kelly Weinersmith', 'Zach Weinersmith'], 'en', true)).toBe(
      'Weinersmith, Kelly, Weinersmith, Zach',
    );
    expect(formatAuthors('Kelly Weinersmith, Zach Weinersmith', 'en', true)).toBe(
      'Weinersmith, Kelly Weinersmith, Zach',
    );
  });

  it('leaves a single author untouched', () => {
    expect(formatAuthors('David Cain', 'en')).toBe('David Cain');
    expect(formatAuthors(['David Cain'], 'en')).toBe('David Cain');
  });
});
