import { describe, expect, it } from 'vitest';

import {
  convertAppleBooksExportToBookNotes,
  locateAppleBooksAnnotationsInBook,
  parseAppleBooksAnnotationsExport,
  titlesLikelyReferToSameBook,
} from '@/services/annotation/providers/appleBooks';
import { BookDoc, SectionItem } from '@/libs/document';
import * as CFI from 'foliate-js/epubcfi.js';

const SAMPLE_CFI = 'epubcfi(/6/14[id9310]!/4[book-body]/2/2,/7:44,/9:128)';

const makeExport = () => ({
  format: 'readest-apple-books-annotations',
  version: 1,
  book: {
    assetId: 'asset-1',
    title: "A Study of Tides: Coastal Rhythms",
    author: 'Marta Devereux',
    epubId: 'urn:uuid:book-1',
  },
  annotations: [
    {
      uuid: 'C70DC8A6-E218-48AF-943E-630D1923D112',
      cfi: SAMPLE_CFI,
      selectedText: 'A highlighted passage',
      note: 'A reader note',
      style: 3,
      createdAt: 1_756_000_000_000,
      updatedAt: 1_756_000_001_000,
    },
  ],
});

describe('parseAppleBooksAnnotationsExport', () => {
  it('parses the versioned Apple Books annotations interchange format', () => {
    const parsed = parseAppleBooksAnnotationsExport(JSON.stringify(makeExport()));

    expect(parsed?.book.title).toContain("A Study of Tides");
    expect(parsed?.annotations).toHaveLength(1);
    expect(parsed?.annotations[0]?.cfi).toBe(SAMPLE_CFI);
  });

  it('rejects unrelated JSON and malformed annotations', () => {
    expect(parseAppleBooksAnnotationsExport('{"format":"other","version":1}')).toBeNull();

    const malformed = makeExport();
    malformed.annotations[0]!.cfi = 'not-a-cfi';
    expect(parseAppleBooksAnnotationsExport(JSON.stringify(malformed))).toBeNull();
  });
});

describe('convertAppleBooksExportToBookNotes', () => {
  it('preserves CFI, text, note, timestamps, and stable source identity', () => {
    const parsed = parseAppleBooksAnnotationsExport(JSON.stringify(makeExport()))!;
    const [note] = convertAppleBooksExportToBookNotes(parsed);

    expect(note).toEqual({
      id: 'apple-books-c70dc8a6-e218-48af-943e-630d1923d112',
      type: 'annotation',
      cfi: SAMPLE_CFI,
      text: 'A highlighted passage',
      style: 'highlight',
      color: 'yellow',
      note: 'A reader note',
      createdAt: 1_756_000_000_000,
      updatedAt: 1_756_000_001_000,
    });
  });

  it.each([
    [0, 'underline', 'red'],
    [1, 'highlight', 'green'],
    [2, 'highlight', 'blue'],
    [3, 'highlight', 'yellow'],
    [4, 'highlight', 'red'],
    [5, 'highlight', 'violet'],
  ] as const)('maps Apple Books style %i to Readest', (style, expectedStyle, color) => {
    const data = makeExport();
    data.annotations[0]!.style = style;
    const parsed = parseAppleBooksAnnotationsExport(JSON.stringify(data))!;

    expect(convertAppleBooksExportToBookNotes(parsed)[0]).toMatchObject({
      style: expectedStyle,
      color,
    });
  });
});

describe('titlesLikelyReferToSameBook', () => {
  it('accepts punctuation and subtitle differences', () => {
    expect(
      titlesLikelyReferToSameBook(
        "A Study of Tides",
        "A Study of Tides: Coastal Rhythms",
      ),
    ).toBe(true);
  });

  it('rejects a different book', () => {
    expect(titlesLikelyReferToSameBook('The Glass Bridge', 'Northern Almanac')).toBe(false);
  });
});

const makeSection = (index: number, html: string): SectionItem => ({
  id: `chapter-${index}`,
  cfi: CFI.fake.fromIndex(index).replace(')', `[chapter-${index}]!)`),
  size: html.length,
  linear: 'yes',
  createDocument: async () => new DOMParser().parseFromString(html, 'text/html'),
});

const makeBookDoc = (sections: SectionItem[]): BookDoc =>
  ({
    metadata: { title: 'Test Book', author: 'Test Author', language: 'en' },
    rendition: {},
    dir: 'ltr',
    sections,
    splitTOCHref: () => [],
    getCover: async () => null,
  }) as BookDoc;

describe('locateAppleBooksAnnotationsInBook', () => {
  it('verifies and canonicalizes an Apple Books CFI against the target EPUB', async () => {
    const section = makeSection(
      0,
      '<html><body id="book-body"><p>Before A highlighted passage After</p></body></html>',
    );
    const doc = await section.createDocument();
    const text = doc.querySelector('p')!.firstChild!;
    const range = doc.createRange();
    range.setStart(text, 7);
    range.setEnd(text, 28);
    const appleCfi = CFI.joinIndir(section.cfi, CFI.fromRange(range));
    const data = makeExport();
    data.annotations[0]!.cfi = appleCfi;

    const result = await locateAppleBooksAnnotationsInBook(
      parseAppleBooksAnnotationsExport(JSON.stringify(data))!,
      makeBookDoc([section]),
    );

    expect(result.unmatched).toBe(0);
    expect(result.notes).toHaveLength(1);
    expect(result.notes[0]?.text).toBe('A highlighted passage');
    expect(result.notes[0]?.cfi).toMatch(/^epubcfi\(\/6\/2/);
  });

  it('falls back to selected-text matching when the source CFI no longer resolves', async () => {
    const data = makeExport();
    data.annotations[0]!.cfi = 'epubcfi(/6/2[old]!/4/999:0)';
    const section = makeSection(
      0,
      '<html><body><p>A highlighted <em>passage</em> survives markup changes.</p></body></html>',
    );

    const result = await locateAppleBooksAnnotationsInBook(
      parseAppleBooksAnnotationsExport(JSON.stringify(data))!,
      makeBookDoc([section]),
    );

    expect(result.unmatched).toBe(0);
    expect(result.notes).toHaveLength(1);
    expect(result.notes[0]?.cfi).not.toBe(data.annotations[0]!.cfi);
  });

  it('reports annotations whose CFI and selected text do not occur in the target EPUB', async () => {
    const data = makeExport();
    data.annotations[0]!.cfi = 'epubcfi(/6/2[old]!/4/999:0)';

    const result = await locateAppleBooksAnnotationsInBook(
      parseAppleBooksAnnotationsExport(JSON.stringify(data))!,
      makeBookDoc([makeSection(0, '<html><body><p>Different text</p></body></html>')]),
    );

    expect(result.notes).toEqual([]);
    expect(result.unmatched).toBe(1);
    expect(result.total).toBe(1);
  });
});
