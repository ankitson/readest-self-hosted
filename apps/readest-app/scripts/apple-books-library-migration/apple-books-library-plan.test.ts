import { readFileSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { describe, expect, it } from 'vitest';
import * as CFI from 'foliate-js/epubcfi.js';

import { DocumentLoader, type BookDoc, type BookMetadata } from '@/libs/document';
import {
  locateAppleBooksAnnotationsInBook,
  parseAppleBooksAnnotationsExport,
} from '@/services/annotation/providers/appleBooks';
import type { BookNote, ReadingStatus } from '@/types/book';
import { formatAuthors, formatTitle, getMetadataHash, getPrimaryLanguage } from '@/utils/book';
import { getIndexFromCfi } from '@/utils/cfi';
import { partialMD5 } from '@/utils/md5';
import { normalizeMetadataIsbn } from '@/utils/isbn';

type AppleReadingLocation = {
  uuid: string;
  location: string | null;
  absolutePhysicalLocation: number | null;
  rangeStart: number | null;
  rangeEnd: number | null;
  createdAt: number | null;
  updatedAt: number | null;
};

type AppleLibraryItem = {
  assetId: string;
  assetGuid: string | null;
  storeId: string | null;
  title: string;
  author: string;
  language: string | null;
  genre: string | null;
  genres: string | null;
  description: string | null;
  comments: string | null;
  year: string | null;
  epubId: string | null;
  seriesId: string | null;
  seriesName: string | null;
  seriesSequence: number | null;
  seriesDisplayName: string | null;
  dataSource: string;
  canRedownload: boolean;
  readingState: {
    progress: number | null;
    highWatermarkProgress: number | null;
    isFinished: boolean;
    isNotFinished: boolean;
    createdAt: number | null;
    updatedAt: number | null;
    lastOpenedAt: number | null;
    lastEngagedAt: number | null;
    finishedAt: number | null;
    purchasedAt: number | null;
    location: AppleReadingLocation | null;
  };
  bookmarks: AppleReadingLocation[];
  file: {
    local: boolean;
    format: string | null;
    declaredSize: number | null;
    stagedFilename: string | null;
    stageError: string | null;
  };
};

type AppleLibraryManifest = {
  format: 'readest-apple-books-library';
  version: 1;
  exportedAt: number;
  items: AppleLibraryItem[];
};

type AppleMigrationBookPlan = {
  assetId: string;
  stagedFilename: string;
  bookHash: string;
  metaHash: string | null;
  format: string;
  title: string;
  sourceTitle: string;
  author: string;
  metadata: BookMetadata & Record<string, unknown>;
  fileSize: number;
  coverRelativePath: string | null;
  coverHash: string | null;
  createdAt: number;
  updatedAt: number;
  uploadedAt: number;
  progress: [number, number] | null;
  readingStatus: ReadingStatus;
  readingStatusUpdatedAt: number;
  metadataUpdatedAt: number;
  config: {
    location: string | null;
    progress: [number, number] | null;
    updatedAt: number;
  };
  notes: BookNote[];
  annotationsTotal: number;
  annotationsUnmatched: number;
  bookmarksTotal: number;
  bookmarksUnmatched: number;
};

type AppleMigrationFailure = {
  assetId: string;
  stagedFilename: string | null;
  title: string;
  reason: string;
};

const requiredEnvironmentPath = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Apple Books library migration missing ${name}`);
  return value;
};

const safeTimestamp = (value: number | null | undefined, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback;

/** Map Apple Books reading state to Readest's explicit shelf status. */
export const mapAppleReadingStatus = (item: AppleLibraryItem): ReadingStatus => {
  if (item.readingState.isFinished || item.readingState.finishedAt) return 'finished';
  if (item.readingState.isNotFinished) return 'abandoned';
  if ((item.readingState.progress ?? 0) > 0 || item.readingState.lastEngagedAt) return 'reading';
  return 'unread';
};

/** Preserve Apple Books' layout-independent percentage as a 10,000-step Readest fraction. */
export const mapAppleReadingProgress = (
  item: AppleLibraryItem,
  status: ReadingStatus,
): [number, number] | null => {
  if (status === 'finished') return [10_000, 10_000];
  const fraction = Math.max(
    item.readingState.progress ?? 0,
    item.readingState.highWatermarkProgress ?? 0,
  );
  return fraction > 0 ? [Math.max(1, Math.round(fraction * 10_000)), 10_000] : null;
};

const resolveAppleCfi = async (book: BookDoc, cfi: string | null): Promise<string | null> => {
  if (!cfi?.startsWith('epubcfi(')) return null;
  const index = getIndexFromCfi(cfi);
  if (index === null || index < 0 || index >= book.sections.length) return null;
  try {
    const doc = await book.sections[index]!.createDocument();
    const parsed = CFI.parse(cfi);
    const range = CFI.toRange(doc, parsed);
    if (!(range instanceof Range)) return null;
    return CFI.joinIndir(book.sections[index]!.cfi, CFI.fromRange(range));
  } catch {
    return null;
  }
};

/** Resolve Apple's exact type-3 location, falling back to its physical spine/page index. */
export const resolveAppleReadingLocation = async (
  book: BookDoc,
  item: AppleLibraryItem,
): Promise<string | null> => {
  const exact = await resolveAppleCfi(book, item.readingState.location?.location ?? null);
  if (exact) return exact;
  const physicalIndex = item.readingState.location?.rangeStart;
  if (typeof physicalIndex === 'number' && book.sections.length > 0) {
    const index = Math.min(book.sections.length - 1, Math.max(0, Math.floor(physicalIndex)));
    return book.sections[index]?.cfi ?? null;
  }
  const fraction = Math.max(
    item.readingState.progress ?? 0,
    item.readingState.highWatermarkProgress ?? 0,
  );
  if (fraction > 0 && book.sections.length > 0) {
    const index = Math.min(book.sections.length - 1, Math.floor(fraction * book.sections.length));
    return book.sections[index]?.cfi ?? null;
  }
  return null;
};

const locateAppleBookmarks = async (
  book: BookDoc,
  item: AppleLibraryItem,
  exportedAt: number,
): Promise<{ notes: BookNote[]; unmatched: number }> => {
  const notes: BookNote[] = [];
  let unmatched = 0;
  for (const bookmark of item.bookmarks) {
    let cfi = await resolveAppleCfi(book, bookmark.location);
    if (!cfi) {
      const cfiIndex = bookmark.location ? getIndexFromCfi(bookmark.location) : null;
      const physicalIndex = bookmark.rangeStart;
      const candidateIndex = cfiIndex ?? physicalIndex;
      if (typeof candidateIndex === 'number' && book.sections.length > 0) {
        const index = Math.min(book.sections.length - 1, Math.max(0, Math.floor(candidateIndex)));
        cfi = book.sections[index]?.cfi ?? null;
      }
    }
    if (!cfi || !bookmark.uuid) {
      unmatched += 1;
      continue;
    }
    notes.push({
      id: `apple-books-bookmark-${bookmark.uuid.toLowerCase()}`,
      type: 'bookmark',
      cfi,
      note: '',
      createdAt: safeTimestamp(bookmark.createdAt, exportedAt),
      updatedAt: exportedAt,
    });
  }
  return { notes, unmatched };
};

const loadAnnotationExports = (directory: string): Map<string, string> => {
  const files = new Map<string, string>();
  for (const name of readdirSync(directory)) {
    if (!name.endsWith('.json')) continue;
    const content = readFileSync(join(directory, name), 'utf8');
    const parsed = parseAppleBooksAnnotationsExport(content);
    if (parsed) files.set(parsed.book.assetId, content);
  }
  return files;
};

const attachAppleMetadata = (
  metadata: BookMetadata,
  item: AppleLibraryItem,
  lastReadAt: number,
): BookMetadata & Record<string, unknown> => {
  const enriched = metadata as BookMetadata & Record<string, unknown>;
  if (!enriched.description && item.description) enriched.description = item.description;
  if (!enriched.series && item.seriesName) enriched.series = item.seriesName;
  if (enriched.seriesIndex === undefined && item.seriesSequence !== null) {
    enriched.seriesIndex = item.seriesSequence;
  }
  enriched['appleBooks'] = {
    assetId: item.assetId,
    assetGuid: item.assetGuid,
    storeId: item.storeId,
    epubId: item.epubId,
    genre: item.genre,
    genres: item.genres,
    year: item.year,
    seriesId: item.seriesId,
    seriesDisplayName: item.seriesDisplayName,
    lastReadAt,
    purchasedAt: item.readingState.purchasedAt,
    finishedAt: item.readingState.finishedAt,
    sourceProgress: item.readingState.progress,
    sourceHighWatermarkProgress: item.readingState.highWatermarkProgress,
  };
  return enriched;
};

describe.runIf(Boolean(process.env['APPLE_BOOKS_MIGRATION_MANIFEST']))(
  'Apple Books full-library migration plan',
  () => {
    it(
      'parses every staged book through Readest and emits an idempotent migration plan',
      async () => {
        const manifestPath = requiredEnvironmentPath('APPLE_BOOKS_MIGRATION_MANIFEST');
        const stageDirectory = requiredEnvironmentPath('APPLE_BOOKS_MIGRATION_STAGE_DIR');
        const annotationDirectory = requiredEnvironmentPath(
          'APPLE_BOOKS_MIGRATION_ANNOTATIONS_DIR',
        );
        const outputDirectory = requiredEnvironmentPath('APPLE_BOOKS_MIGRATION_OUTPUT_DIR');
        const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as AppleLibraryManifest;
        expect(manifest.format).toBe('readest-apple-books-library');
        expect(manifest.version).toBe(1);
        mkdirSync(outputDirectory, { recursive: true });
        const coverDirectory = join(outputDirectory, 'covers');
        mkdirSync(coverDirectory, { recursive: true });
        const annotationExports = loadAnnotationExports(annotationDirectory);
        const books: AppleMigrationBookPlan[] = [];
        const failures: AppleMigrationFailure[] = [];

        if (manifest.items.some((item) => item.file.format === 'PDF' && item.file.local)) {
          await import('foliate-js/pdf.js');
          const pdfjs = (globalThis as Record<string, unknown>)['pdfjsLib'] as {
            GlobalWorkerOptions: { workerSrc: string };
          };
          pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(
            join(process.cwd(), 'public/vendor/pdfjs/pdf.worker.min.mjs'),
          ).href;
        }

        for (const item of manifest.items) {
          if (!item.file.local || !item.file.stagedFilename) continue;
          const stagedPath = join(stageDirectory, item.file.stagedFilename);
          try {
            const bytes = readFileSync(stagedPath);
            const file = new File([bytes], item.file.stagedFilename, {
              type: item.file.format === 'PDF' ? 'application/pdf' : 'application/epub+zip',
            });
            const { book, format } = await new DocumentLoader(file).open();
            normalizeMetadataIsbn(book.metadata);
            const bookHash = await partialMD5(file);
            const primaryLanguage = getPrimaryLanguage(book.metadata.language);
            const sourceTitle =
              formatTitle(book.metadata.title) || item.title || basename(stagedPath);
            const author = formatAuthors(book.metadata.author, primaryLanguage) || item.author;
            const status = mapAppleReadingStatus(item);
            const progress = mapAppleReadingProgress(item, status);
            const locationUpdatedAt = item.readingState.location?.updatedAt ?? 0;
            const lastReadAt = Math.max(
              locationUpdatedAt,
              item.readingState.lastEngagedAt ?? 0,
              item.readingState.lastOpenedAt ?? 0,
              item.readingState.finishedAt ?? 0,
            );
            const createdAt = safeTimestamp(
              item.readingState.purchasedAt ?? item.readingState.createdAt,
              manifest.exportedAt,
            );
            const updatedAt = safeTimestamp(lastReadAt, createdAt);
            const metadata = attachAppleMetadata(book.metadata, item, updatedAt);
            const metaHash = getMetadataHash(metadata) ?? null;
            const location = await resolveAppleReadingLocation(book, item);
            const bookmarks = await locateAppleBookmarks(book, item, manifest.exportedAt);
            const annotationContent = annotationExports.get(item.assetId);
            let annotations: BookNote[] = [];
            let annotationsTotal = 0;
            let annotationsUnmatched = 0;
            if (annotationContent) {
              const annotationExport = parseAppleBooksAnnotationsExport(annotationContent)!;
              const located = await locateAppleBooksAnnotationsInBook(annotationExport, book);
              annotations = located.notes.map((note) => ({
                ...note,
                updatedAt: manifest.exportedAt,
              }));
              annotationsTotal = located.total;
              annotationsUnmatched = located.unmatched;
            }

            let coverRelativePath: string | null = null;
            let coverHash: string | null = null;
            try {
              const cover = await book.getCover();
              if (cover) {
                const coverBuffer = await cover.arrayBuffer();
                coverRelativePath = `${bookHash}.png`;
                writeFileSync(join(coverDirectory, coverRelativePath), new Uint8Array(coverBuffer));
                coverHash = await partialMD5(
                  new File([coverBuffer], 'cover.png', { type: cover.type || 'image/png' }),
                );
              }
            } catch {
              // PDF cover rendering needs a native canvas that the migration's
              // jsdom runner intentionally does not install. The PDF itself and
              // its metadata/progress remain fully migratable without a cover.
            }

            books.push({
              assetId: item.assetId,
              stagedFilename: item.file.stagedFilename,
              bookHash,
              metaHash,
              format,
              title: sourceTitle,
              sourceTitle,
              author,
              metadata,
              fileSize: file.size,
              coverRelativePath,
              coverHash,
              createdAt,
              updatedAt,
              uploadedAt: manifest.exportedAt,
              progress,
              readingStatus: status,
              readingStatusUpdatedAt: safeTimestamp(
                item.readingState.finishedAt ?? lastReadAt,
                manifest.exportedAt,
              ),
              metadataUpdatedAt: manifest.exportedAt,
              config: {
                location,
                progress,
                updatedAt: safeTimestamp(locationUpdatedAt || lastReadAt, manifest.exportedAt),
              },
              notes: [...annotations, ...bookmarks.notes],
              annotationsTotal,
              annotationsUnmatched,
              bookmarksTotal: item.bookmarks.length,
              bookmarksUnmatched: bookmarks.unmatched,
            });
          } catch (error) {
            failures.push({
              assetId: item.assetId,
              stagedFilename: item.file.stagedFilename,
              title: item.title,
              reason: error instanceof Error ? error.message : String(error),
            });
          }
        }

        const plan = {
          format: 'readest-apple-books-library-plan',
          version: 1,
          exportedAt: manifest.exportedAt,
          generatedAt: Date.now(),
          sourceManifest: manifestPath,
          stageDirectory,
          summary: {
            manifestItems: manifest.items.length,
            localItems: manifest.items.filter((item) => item.file.local).length,
            cloudOnlyItems: manifest.items.filter((item) => !item.file.local).length,
            parsedBooks: books.length,
            parseFailures: failures.length,
            annotationsTotal: books.reduce((sum, book) => sum + book.annotationsTotal, 0),
            annotationsUnmatched: books.reduce((sum, book) => sum + book.annotationsUnmatched, 0),
            bookmarksTotal: books.reduce((sum, book) => sum + book.bookmarksTotal, 0),
            bookmarksUnmatched: books.reduce((sum, book) => sum + book.bookmarksUnmatched, 0),
          },
          failures,
          books,
        };
        writeFileSync(join(outputDirectory, 'migration-plan.json'), `${JSON.stringify(plan)}\n`);
        console.log(`APPLE_BOOKS_LIBRARY_PLAN ${JSON.stringify(plan.summary)}`);
        expect(books.length + failures.length).toBe(plan.summary.localItems);
      },
      30 * 60 * 1000,
    );
  },
);
