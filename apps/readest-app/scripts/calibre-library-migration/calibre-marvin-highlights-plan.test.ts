import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { describe, expect, it } from 'vitest';

import { DocumentLoader, type BookDoc } from '@/libs/document';
import {
  locateAppleBooksAnnotationsInBook,
  type AppleBooksAnnotationsExport,
} from '@/services/annotation/providers/appleBooks';
import type { BookNote } from '@/types/book';
import { partialMD5 } from '@/utils/md5';

// Staged by export_calibre_marvin_highlights.py.
type MarvinEntry = {
  id: string;
  quote: string;
  firstParagraph: string;
  continuation: string[];
  note: string;
  page: number | null;
};

type MarvinStageBook = {
  calibreId: number;
  title: string;
  author: string;
  bookHash: string;
  metaHash: string | null;
  format: string;
  stagedFilename: string;
  existingNoteTexts: string[];
  entries: MarvinEntry[];
};

type MarvinStage = {
  format: 'readest-calibre-marvin-highlights';
  version: 1;
  exportedAt: number;
  userId: string;
  books: MarvinStageBook[];
};

type MarvinPlanBook = {
  calibreId: number;
  title: string;
  bookHash: string;
  metaHash: string | null;
  notes: BookNote[];
  duplicates: { id: string; quote: string }[];
  unmatched: { id: string; quote: string }[];
  firstParagraphOnly: string[];
};

// Marvin keeps no CFI. A syntactically valid placeholder whose range can never
// equal the quote sends the Apple locator straight to its whole-book
// selected-text search, which fails closed when the text is not found.
const PLACEHOLDER_CFI = 'epubcfi(/6/2!/4/2)';

const requiredEnvironmentPath = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Calibre Marvin highlight plan missing ${name}`);
  return value;
};

/** Fold quotes so typography and whitespace differences between exports compare equal. */
export const normalizeQuote = (text: string): string =>
  text
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[‘’“”"'`]/gu, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();

/** A Marvin quote duplicates an existing Readest highlight when either text contains the other. */
export const isDuplicateQuote = (quote: string, existing: string[]): boolean => {
  const target = normalizeQuote(quote);
  if (!target) return false;
  return existing.some((text) => {
    const other = normalizeQuote(text);
    return other.length > 0 && (other.includes(target) || target.includes(other));
  });
};

const locateQuotes = async (
  stage: MarvinStage,
  book: MarvinStageBook,
  bookDoc: BookDoc,
  quotes: { id: string; text: string; note: string }[],
): Promise<BookNote[]> => {
  const data: AppleBooksAnnotationsExport = {
    format: 'readest-apple-books-annotations',
    version: 1,
    exportedAt: stage.exportedAt,
    book: { assetId: String(book.calibreId), title: book.title, author: book.author },
    annotations: quotes.map((quote) => ({
      uuid: quote.id,
      cfi: PLACEHOLDER_CFI,
      selectedText: quote.text,
      note: quote.note,
      style: 3, // Apple's yellow highlight, Readest's default appearance
      createdAt: stage.exportedAt,
      updatedAt: stage.exportedAt,
    })),
  };
  const located = await locateAppleBooksAnnotationsInBook(data, bookDoc);
  return located.notes.map((note) => ({
    ...note,
    id: note.id.replace(/^apple-books-/u, 'calibre-marvin-'),
  }));
};

describe.runIf(Boolean(process.env['CALIBRE_MARVIN_STAGE_DIR']))(
  'Calibre Marvin highlight import plan',
  () => {
    it('locates every Marvin quote in its Readest edition and emits an idempotent plan', async () => {
      const stageDirectory = requiredEnvironmentPath('CALIBRE_MARVIN_STAGE_DIR');
      const stage = JSON.parse(
        readFileSync(join(stageDirectory, 'marvin-highlights.json'), 'utf8'),
      ) as MarvinStage;
      expect(stage.format).toBe('readest-calibre-marvin-highlights');
      expect(stage.version).toBe(1);

      if (stage.books.some((book) => book.format === 'PDF')) {
        await import('@pdfjs/pdf.min.mjs');
        const pdfjs = (globalThis as Record<string, unknown>)['pdfjsLib'] as {
          GlobalWorkerOptions: { workerSrc: string };
        };
        pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(
          join(process.cwd(), 'public/vendor/pdfjs/pdf.worker.min.mjs'),
        ).href;
      }

      const books: MarvinPlanBook[] = [];
      for (const book of stage.books) {
        const bytes = readFileSync(join(stageDirectory, 'books', book.stagedFilename));
        const file = new File([bytes], book.stagedFilename, {
          type: book.format === 'PDF' ? 'application/pdf' : 'application/epub+zip',
        });
        expect(await partialMD5(file)).toBe(book.bookHash);
        const { book: bookDoc } = await new DocumentLoader(file).open();

        const duplicates = book.entries.filter((entry) =>
          isDuplicateQuote(entry.quote, book.existingNoteTexts),
        );
        const candidates = book.entries.filter((entry) => !duplicates.includes(entry));

        // Pass 1: the whole quote, including any continuation paragraphs.
        const notes = await locateQuotes(
          stage,
          book,
          bookDoc,
          candidates.map((entry) => ({ id: entry.id, text: entry.quote, note: entry.note })),
        );
        // Pass 2: quoted <ol> items carry Marvin's "1. " markers, which the
        // book's DOM text lacks (CSS numbers the list). Retry without them.
        const unplaced = (entry: MarvinEntry) =>
          !notes.some((note) => note.id === `calibre-marvin-${entry.id}`);
        const listItem = /^\d+\.\s+/u;
        const lists = candidates.filter(
          (entry) => unplaced(entry) && entry.continuation.some((line) => listItem.test(line)),
        );
        notes.push(
          ...(await locateQuotes(
            stage,
            book,
            bookDoc,
            lists.map((entry) => ({
              id: entry.id,
              text: [
                entry.firstParagraph,
                ...entry.continuation.map((line) => line.replace(listItem, '')),
              ].join(' '),
              note: entry.note,
            })),
          )),
        );
        // Pass 3: Marvin sometimes ran the reader's own words on after a quote.
        // Retry those with only the `>` paragraph, keeping the rest as the note.
        const located = new Set(notes.map((note) => note.id));
        const retry = candidates.filter(
          (entry) => entry.continuation.length > 0 && !located.has(`calibre-marvin-${entry.id}`),
        );
        const retried = await locateQuotes(
          stage,
          book,
          bookDoc,
          retry.map((entry) => ({
            id: entry.id,
            text: entry.firstParagraph,
            note: [entry.continuation.join('\n\n'), entry.note].filter(Boolean).join('\n\n'),
          })),
        );
        notes.push(...retried);
        const placed = new Set(notes.map((note) => note.id));

        books.push({
          calibreId: book.calibreId,
          title: book.title,
          bookHash: book.bookHash,
          metaHash: book.metaHash,
          notes,
          duplicates: duplicates.map((entry) => ({ id: entry.id, quote: entry.quote })),
          unmatched: candidates
            .filter((entry) => !placed.has(`calibre-marvin-${entry.id}`))
            .map((entry) => ({ id: entry.id, quote: entry.quote })),
          firstParagraphOnly: retried.map((note) => note.id),
        });
      }

      const plan = {
        format: 'readest-calibre-marvin-highlights-plan',
        version: 1,
        exportedAt: stage.exportedAt,
        userId: stage.userId,
        books,
      };
      const outputDirectory = join(stageDirectory, 'plan');
      mkdirSync(outputDirectory, { recursive: true });
      writeFileSync(
        join(outputDirectory, 'marvin-highlights-plan.json'),
        JSON.stringify(plan, null, 1),
      );

      const summary = books.map((book) => ({
        title: book.title.slice(0, 40),
        located: book.notes.length,
        firstParagraphOnly: book.firstParagraphOnly.length,
        duplicates: book.duplicates.length,
        unmatched: book.unmatched.length,
      }));
      console.table(summary);
      for (const book of books) {
        for (const note of book.notes) {
          expect(note.cfi.startsWith('epubcfi(')).toBe(true);
          expect(note.id.startsWith('calibre-marvin-')).toBe(true);
        }
      }
    }, 600_000);
  },
);
