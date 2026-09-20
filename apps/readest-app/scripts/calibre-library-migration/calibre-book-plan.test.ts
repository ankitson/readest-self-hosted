import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { describe, expect, it } from 'vitest';

import { DocumentLoader, type BookMetadata } from '@/libs/document';
import type { ReadingStatus } from '@/types/book';
import { formatAuthors, formatTitle, getMetadataHash, getPrimaryLanguage } from '@/utils/book';
import { normalizeMetadataIsbn } from '@/utils/isbn';
import { md5Fingerprint, partialMD5 } from '@/utils/md5';

type CalibreStageBook = {
  calibreId: number;
  category: 'Book';
  classificationConfidence: string;
  sourcePreferredPath: string;
  archiveBookPath: string;
  format: 'EPUB' | 'PDF';
  fileSize: number;
  fileSha256: string;
  archiveCoverPath: string;
  coverSize: number;
  coverSha256: string;
  calibre: {
    id: number;
    title: string;
    sort: string;
    timestamp: string | null;
    pubdate: string | null;
    series_index: number;
    author_sort: string;
    isbn: string | null;
    lccn: string | null;
    path: string;
    uuid: string;
    has_cover: boolean;
    last_modified: string | null;
    authors: string[];
    identifiers: Record<string, string>;
    tags: string[];
    languages: string[];
    publisher: string | null;
    series: string | null;
    comments: string | null;
    customColumns: {
      readStatus: string | null;
      pageCount: number | null;
      wordCount: number | null;
      genre: string[];
      type: string | null;
      dateRead: string | null;
    };
  };
};

type CalibreStageManifest = {
  format: 'readest-calibre-book-stage';
  version: 1;
  generatedAt: string;
  selection: { category: 'Book'; count: number; categoriesSha256: string };
  source: { metadataDatabaseSha256: string; libraryUuid: string };
  books: CalibreStageBook[];
};

type LiveReadestBook = {
  bookHash: string;
  metaHash: string | null;
  format: string;
  title: string;
  author: string;
  metadata: unknown;
};

type PlannedCalibreBook = {
  calibreId: number;
  disposition: 'create' | 'skip-existing';
  duplicateReason: string | null;
  duplicateBookHash: string | null;
  duplicateTitle: string | null;
  archiveBookPath: string;
  archiveCoverPath: string;
  sourceFileSha256: string;
  sourceCoverSha256: string;
  fileSize: number;
  bookHash: string;
  metaHash: string | null;
  format: 'EPUB' | 'PDF';
  title: string;
  sourceTitle: string;
  author: string;
  tags: string[];
  groupId: string;
  groupName: string;
  metadata: BookMetadata & Record<string, unknown>;
  createdAt: number;
  updatedAt: number;
  uploadedAt: number;
  metadataUpdatedAt: number;
  lastReadAt: number | null;
  readingStatus: ReadingStatus;
  readingStatusUpdatedAt: number;
};

const PLAN_FORMAT = 'readest-calibre-book-plan';
const PLAN_VERSION = 1;
const GROUP_NAME = 'Calibre Staging';

/** Return a required migration environment path with a searchable error prefix. */
const requiredCalibreMigrationPath = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Calibre book plan missing environment path ${name}`);
  return value;
};

/** Decode Readest's JSON-string-inside-JSON metadata representation. */
const decodeReadestMetadata = (value: unknown): Record<string, unknown> => {
  let decoded = value;
  while (typeof decoded === 'string') decoded = JSON.parse(decoded) as unknown;
  return decoded && typeof decoded === 'object' ? (decoded as Record<string, unknown>) : {};
};

/** Normalize text for conservative same-work matching without fuzzy guessing. */
const normalizeWorkText = (value: string): string =>
  value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');

/** Flatten supported Readest author shapes into names used for display and matching. */
const metadataAuthorNames = (value: unknown): string[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(metadataAuthorNames).filter(Boolean);
  if (typeof value === 'object') {
    const name = (value as Record<string, unknown>)['name'];
    if (typeof name === 'string') return [name.trim()].filter(Boolean);
    if (name && typeof name === 'object') {
      return Object.values(name as Record<string, unknown>)
        .filter((item): item is string => typeof item === 'string')
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 1);
    }
    return [];
  }
  return String(value)
    .split(/\s*(?:,|;|\s&\s|\sand\s)\s*/i)
    .map((name) => name.trim())
    .filter(Boolean);
};

/** Read author values without treating an inverted-name comma as an author separator. */
const metadataAuthorEntries = (value: unknown): string[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(metadataAuthorEntries).filter(Boolean);
  if (typeof value === 'object') {
    const name = (value as Record<string, unknown>)['name'];
    if (typeof name === 'string') return [name.trim()].filter(Boolean);
    if (name && typeof name === 'object') {
      const first = Object.values(name as Record<string, unknown>).find(
        (item): item is string => typeof item === 'string' && Boolean(item.trim()),
      );
      return first ? [first.trim()] : [];
    }
    return [];
  }
  return [String(value).trim()].filter(Boolean);
};

/** Convert one unambiguous "Family, Given" catalog name to natural display order. */
const naturalizeInvertedAuthor = (value: string): string => {
  const parts = value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length !== 2 || /^(?:jr\.?|sr\.?|m\.?\s*d\.?|ph\.?\s*d\.?)$/i.test(parts[1]!)) {
    return value.trim();
  }
  return `${parts[1]} ${parts[0]}`.trim();
};

/** Repair Calibre's legacy pipe-separated author values without guessing at clean names. */
const normalizedCalibreAuthors = (
  parsed: BookMetadata,
  source: CalibreStageBook['calibre'],
): string[] => {
  const parsedEntries = metadataAuthorEntries(parsed.author)
    .filter((name) => !/unknownauthor|^unknown$/i.test(name))
    .map(naturalizeInvertedAuthor);
  if (source.authors.every((name) => !name.includes('|'))) {
    return source.authors.map(naturalizeInvertedAuthor).filter(Boolean);
  }
  if (source.authors.length > 1) {
    return source.authors.flatMap((name) => {
      const parts = name
        .split('|')
        .map((part) => part.trim())
        .filter(Boolean);
      return parts.length === 2 ? [`${parts[1]} ${parts[0]}`.trim()] : parts;
    });
  }

  const pipeParts = source.authors[0]!.split('|')
    .map((part) => part.trim())
    .filter(Boolean);
  if (
    parsedEntries.length === pipeParts.length &&
    parsedEntries.every((name) => !name.includes('|'))
  ) {
    return parsedEntries;
  }
  if (parsedEntries.length === 1 && parsedEntries[0]!.includes(' ')) {
    const flattened = normalizeWorkText(parsedEntries[0]!);
    if (pipeParts.every((part) => flattened.includes(normalizeWorkText(part))))
      return parsedEntries;
  }
  const suffixes = /^(?:m\.?\s*d\.?|ph\.?\s*d\.?|et\.?\s*al\.?)$/i;
  if (pipeParts.length === 2 && suffixes.test(pipeParts[1]!)) {
    return [`${pipeParts[0]} ${pipeParts[1]}`.trim()];
  }
  return pipeParts;
};

/** Produce the human-facing row value while retaining structured authors in metadata. */
const naturalAuthorDisplay = (authors: string[]): string => {
  if (authors.length <= 1) return authors[0] ?? '';
  if (authors.length === 2) return `${authors[0]} and ${authors[1]}`;
  return `${authors.slice(0, -1).join(', ')}, and ${authors.at(-1)}`;
};

/** Normalize author names and allow any shared credited author to establish identity. */
const normalizedAuthorSet = (value: unknown): Set<string> =>
  new Set(metadataAuthorNames(value).map(normalizeWorkText).filter(Boolean));

/** Extract normalized ISBN/UUID/ASIN/URL identity keys from supported metadata fields. */
const metadataIdentifierSet = (metadata: Record<string, unknown>): Set<string> => {
  const keys = new Set<string>();
  const visit = (value: unknown) => {
    if (!value) return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (typeof value === 'object') {
      const object = value as Record<string, unknown>;
      if (typeof object['value'] === 'string') visit(object['value']);
      return;
    }
    const raw = String(value).trim();
    if (!raw) return;
    const compactIsbn = raw.replace(/^urn:isbn:/i, '').replace(/[^0-9Xx]/g, '');
    if (compactIsbn.length === 10 || compactIsbn.length === 13) {
      keys.add(`isbn:${compactIsbn.toUpperCase()}`);
    }
    const uuidMatch = raw.match(
      /(?:urn:uuid:|calibre:)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i,
    );
    if (uuidMatch) keys.add(`uuid:${uuidMatch[1]!.toLowerCase()}`);
    const asinMatch = raw.match(/(?:urn:asin:|asin:)([A-Z0-9]{10})/i);
    if (asinMatch) keys.add(`asin:${asinMatch[1]!.toUpperCase()}`);
    if (/^https?:\/\//i.test(raw)) keys.add(raw.replace(/\/$/, '').toLowerCase());
  };
  visit(metadata['identifier']);
  visit(metadata['isbn']);
  visit(metadata['altIdentifier']);
  return keys;
};

/** Convert useful Calibre identifiers into canonical Readest URI/URN strings. */
const canonicalCalibreIdentifiers = (source: CalibreStageBook['calibre']): string[] => {
  const result: string[] = [];
  const add = (value: string | null | undefined) => {
    const normalized = value?.trim();
    if (normalized && !result.includes(normalized)) result.push(normalized);
  };
  const compactIsbn = String(source.isbn ?? '')
    .replace(/[^0-9Xx]/g, '')
    .toUpperCase();
  if (compactIsbn.length === 10 || compactIsbn.length === 13) add(`urn:isbn:${compactIsbn}`);
  for (const [scheme, value] of Object.entries(source.identifiers)) {
    if (!value) continue;
    if (scheme === 'isbn') {
      const compact = value.replace(/[^0-9Xx]/g, '').toUpperCase();
      if (compact.length === 10 || compact.length === 13) add(`urn:isbn:${compact}`);
    } else if (['asin', 'amazon', 'mobi-asin', 'oasin'].includes(scheme)) {
      if (/^[A-Z0-9]{10}$/i.test(value)) add(`urn:asin:${value.toUpperCase()}`);
    } else if (scheme === 'uri' && /^(?:https?:\/\/|urn:)/i.test(value)) {
      add(value);
    }
  }
  if (source.uuid) add(`urn:uuid:${source.uuid.toLowerCase()}`);
  return result;
};

/** Parse a Calibre timestamp while rejecting year-1 sentinel publication dates. */
const parseCalibreTimestamp = (value: string | null | undefined): number | null => {
  if (!value || /^0*101-/.test(value)) return null;
  const parsed = Date.parse(value.includes('T') ? value : value.replace(' ', 'T'));
  return Number.isFinite(parsed) ? parsed : null;
};

/** Format a valid Calibre edition date as the most precise ISO date available. */
const calibrePublishedDate = (value: string | null | undefined): string | undefined => {
  const parsed = parseCalibreTimestamp(value);
  if (parsed === null) return undefined;
  return new Date(parsed).toISOString().slice(0, 10);
};

/** Map the reviewed Calibre shelf status without creating reading progress or duration. */
const calibreReadingStatus = (value: string | null): ReadingStatus => {
  if (value === 'read') return 'finished';
  if (value === 'reading') return 'reading';
  if (value === 'abandoned') return 'abandoned';
  return 'unread';
};

/** Merge parsed file metadata with Calibre provenance for staging-area review. */
const mergeCalibreBookMetadata = (
  parsed: BookMetadata,
  stageBook: CalibreStageBook,
  libraryUuid: string,
): BookMetadata & Record<string, unknown> => {
  const metadata = structuredClone(parsed) as BookMetadata & Record<string, unknown>;
  const source = stageBook.calibre;
  const authors = normalizedCalibreAuthors(parsed, source);

  metadata.title =
    source.title.trim() || formatTitle(metadata.title) || basename(stageBook.archiveBookPath);
  if (typeof metadata.title === 'string' && metadata.title.includes(':') && !metadata.subtitle) {
    const [mainTitle, ...subtitleParts] = metadata.title.split(':');
    const subtitle = subtitleParts.join(':').trim();
    if (mainTitle?.trim() && subtitle) {
      metadata.title = mainTitle.trim();
      metadata.subtitle = subtitle;
    }
  }
  metadata.author = authors as unknown as BookMetadata['author'];
  if (!metadata.language && source.languages.length) metadata.language = source.languages;
  if (!metadata.publisher && source.publisher) metadata.publisher = source.publisher;
  if (!metadata.published) metadata.published = calibrePublishedDate(source.pubdate);
  if (!metadata.description && source.comments) metadata.description = source.comments;
  if (source.series) {
    metadata.series = source.series;
    metadata.seriesIndex = source.series_index;
  }
  if (!metadata.subject && source.tags.length) metadata.subject = source.tags;

  const identifiers = canonicalCalibreIdentifiers(source);
  if (identifiers.length) {
    // Calibre identifiers are authoritative here. Some source EPUBs contain a copied,
    // unrelated UUID, so retaining parsed identifiers can falsely merge distinct books.
    metadata.identifier = identifiers[0];
    metadata.altIdentifier = identifiers.slice(1);
  }
  normalizeMetadataIsbn(metadata);

  metadata.calibreColumns = [
    ...(source.customColumns.readStatus
      ? [
          {
            label: 'readstatus',
            name: 'Read Status',
            datatype: 'enumeration',
            value: source.customColumns.readStatus,
          },
        ]
      : []),
    ...(source.customColumns.pageCount !== null
      ? [
          {
            label: 'page_count',
            name: 'Page Count',
            datatype: 'int',
            value: source.customColumns.pageCount,
          },
        ]
      : []),
    ...(source.customColumns.wordCount !== null
      ? [
          {
            label: 'word_count',
            name: 'Word Count',
            datatype: 'int',
            value: source.customColumns.wordCount,
          },
        ]
      : []),
    ...(source.customColumns.genre.length
      ? [
          {
            label: 'genre',
            name: 'Genre',
            datatype: 'text',
            value: source.customColumns.genre,
          },
        ]
      : []),
    ...(source.customColumns.type
      ? [
          {
            label: 'type',
            name: 'Type',
            datatype: 'enumeration',
            value: source.customColumns.type,
          },
        ]
      : []),
  ];
  metadata['calibreSource'] = {
    libraryUuid,
    id: source.id,
    uuid: source.uuid,
    title: source.title,
    authors: source.authors,
    authorSort: source.author_sort,
    identifiers: source.identifiers,
    isbn: source.isbn,
    lccn: source.lccn,
    sourcePath: source.path,
    timestamp: source.timestamp,
    lastModified: source.last_modified,
    dateRead: source.customColumns.dateRead,
    classification: {
      category: stageBook.category,
      confidence: stageBook.classificationConfidence,
    },
  };
  return metadata;
};

/** Find an already-present Readest work using conservative, explainable identity signals. */
const findExistingReadestWork = (
  planned: Omit<
    PlannedCalibreBook,
    'disposition' | 'duplicateReason' | 'duplicateBookHash' | 'duplicateTitle'
  >,
  liveBooks: LiveReadestBook[],
): { book: LiveReadestBook; reason: string } | null => {
  const exactHash = liveBooks.find((book) => book.bookHash === planned.bookHash);
  if (exactHash) return { book: exactHash, reason: 'exact-book-hash' };

  const plannedIdentifiers = metadataIdentifierSet(planned.metadata);
  if (plannedIdentifiers.size) {
    const identifierMatches = liveBooks.filter((book) => {
      const liveIdentifiers = metadataIdentifierSet(decodeReadestMetadata(book.metadata));
      return [...plannedIdentifiers].some((identifier) => liveIdentifiers.has(identifier));
    });
    if (identifierMatches.length === 1) {
      return { book: identifierMatches[0]!, reason: 'identifier-overlap' };
    }
  }

  if (planned.metaHash) {
    const metaMatches = liveBooks.filter((book) => book.metaHash === planned.metaHash);
    if (metaMatches.length === 1) return { book: metaMatches[0]!, reason: 'metadata-hash' };
  }

  const plannedTitle = normalizeWorkText(planned.title).split(' a novel')[0]!.trim();
  const plannedAuthors = normalizedAuthorSet(planned.metadata.author);
  const titleAuthorMatches = liveBooks.filter((book) => {
    const liveTitle = normalizeWorkText(book.title).split(' a novel')[0]!.trim();
    if (liveTitle !== plannedTitle) return false;
    const liveAuthors = normalizedAuthorSet(book.author);
    return [...plannedAuthors].some((author) => liveAuthors.has(author));
  });
  if (titleAuthorMatches.length === 1) {
    return { book: titleAuthorMatches[0]!, reason: 'normalized-title-author' };
  }
  return null;
};

describe.runIf(Boolean(process.env['CALIBRE_BOOK_STAGE_ROOT']))(
  'Calibre Book staging import plan',
  () => {
    it(
      'parses every selected book through Readest and emits a duplicate-safe plan',
      async () => {
        const stageRoot = requiredCalibreMigrationPath('CALIBRE_BOOK_STAGE_ROOT');
        const liveBooksPath = requiredCalibreMigrationPath('CALIBRE_LIVE_BOOKS_JSON');
        const outputDirectory = requiredCalibreMigrationPath('CALIBRE_BOOK_PLAN_OUTPUT');
        const manifest = JSON.parse(
          readFileSync(join(stageRoot, 'manifest.json'), 'utf8'),
        ) as CalibreStageManifest;
        const liveBooks = JSON.parse(readFileSync(liveBooksPath, 'utf8')) as LiveReadestBook[];
        expect(manifest.format).toBe('readest-calibre-book-stage');
        expect(manifest.version).toBe(1);
        expect(manifest.selection.category).toBe('Book');
        expect(manifest.books).toHaveLength(290);
        mkdirSync(outputDirectory, { recursive: true });

        if (manifest.books.some((item) => item.format === 'PDF')) {
          await import('foliate-js/pdf.js');
          const pdfjs = (globalThis as Record<string, unknown>)['pdfjsLib'] as {
            GlobalWorkerOptions: { workerSrc: string };
          };
          pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(
            join(process.cwd(), 'public/vendor/pdfjs/pdf.worker.min.mjs'),
          ).href;
        }

        const plannedAt = Date.now();
        const groupId = md5Fingerprint(GROUP_NAME);
        const books: PlannedCalibreBook[] = [];
        const failures: Array<{ calibreId: number; title: string; reason: string }> = [];
        for (const stageBook of manifest.books) {
          const stagedPath = join(stageRoot, stageBook.archiveBookPath);
          try {
            const bytes = readFileSync(stagedPath);
            expect(bytes.byteLength).toBe(stageBook.fileSize);
            expect(createHash('sha256').update(bytes).digest('hex')).toBe(stageBook.fileSha256);
            const file = new File([bytes], basename(stagedPath), {
              type: stageBook.format === 'PDF' ? 'application/pdf' : 'application/epub+zip',
            });
            const { book, format } = await new DocumentLoader(file).open();
            expect(format).toBe(stageBook.format);
            const metadata = mergeCalibreBookMetadata(
              book.metadata,
              stageBook,
              manifest.source.libraryUuid,
            );
            const title = formatTitle(metadata.title).trim();
            const sourceTitle = formatTitle(book.metadata.title).trim() || title;
            const primaryLanguage = getPrimaryLanguage(metadata.language);
            const authorNames = metadataAuthorEntries(metadata.author);
            const author =
              naturalAuthorDisplay(authorNames) ||
              formatAuthors(metadata.author, primaryLanguage).trim();
            if (!title || !author || /unknownauthor|^unknown$/i.test(author)) {
              throw new Error(
                `Calibre book plan invalid title/author: ${JSON.stringify(title)} / ${JSON.stringify(author)}`,
              );
            }
            const createdAt = parseCalibreTimestamp(stageBook.calibre.timestamp) ?? plannedAt;
            const lastReadAt = parseCalibreTimestamp(stageBook.calibre.customColumns.dateRead);
            const basePlan = {
              calibreId: stageBook.calibreId,
              archiveBookPath: stageBook.archiveBookPath,
              archiveCoverPath: stageBook.archiveCoverPath,
              sourceFileSha256: stageBook.fileSha256,
              sourceCoverSha256: stageBook.coverSha256,
              fileSize: stageBook.fileSize,
              bookHash: await partialMD5(file),
              metaHash: getMetadataHash(metadata) ?? null,
              format: format as 'EPUB' | 'PDF',
              title,
              sourceTitle,
              author,
              tags: stageBook.calibre.tags,
              groupId,
              groupName: GROUP_NAME,
              metadata,
              createdAt,
              updatedAt: createdAt,
              uploadedAt: plannedAt,
              metadataUpdatedAt: plannedAt,
              lastReadAt,
              readingStatus: calibreReadingStatus(stageBook.calibre.customColumns.readStatus),
              readingStatusUpdatedAt: lastReadAt ?? createdAt,
            } satisfies Omit<
              PlannedCalibreBook,
              'disposition' | 'duplicateReason' | 'duplicateBookHash' | 'duplicateTitle'
            >;
            const duplicate = findExistingReadestWork(basePlan, liveBooks);
            books.push({
              ...basePlan,
              disposition: duplicate ? 'skip-existing' : 'create',
              duplicateReason: duplicate?.reason ?? null,
              duplicateBookHash: duplicate?.book.bookHash ?? null,
              duplicateTitle: duplicate?.book.title ?? null,
            });
          } catch (error) {
            failures.push({
              calibreId: stageBook.calibreId,
              title: stageBook.calibre.title,
              reason: error instanceof Error ? error.message : String(error),
            });
          }
          if ((books.length + failures.length) % 25 === 0) {
            console.log(`CALIBRE_BOOK_PLAN_PROGRESS ${books.length + failures.length}/290`);
          }
        }

        const duplicateKeys = new Map<string, number[]>();
        for (const book of books.filter((item) => item.disposition === 'create')) {
          for (const key of [
            `hash:${book.bookHash}`,
            ...[...metadataIdentifierSet(book.metadata)].map((id) => `id:${id}`),
          ]) {
            const ids = duplicateKeys.get(key) ?? [];
            ids.push(book.calibreId);
            duplicateKeys.set(key, ids);
          }
        }
        const internalCollisions = [...duplicateKeys.entries()]
          .filter(([, ids]) => ids.length > 1)
          .map(([key, calibreIds]) => ({ key, calibreIds }));

        const plan = {
          format: PLAN_FORMAT,
          version: PLAN_VERSION,
          generatedAt: plannedAt,
          sourceManifest: join(stageRoot, 'manifest.json'),
          sourceManifestSha256: createHash('sha256')
            .update(readFileSync(join(stageRoot, 'manifest.json')))
            .digest('hex'),
          liveBooksSnapshot: liveBooksPath,
          liveBooksSnapshotSha256: createHash('sha256')
            .update(readFileSync(liveBooksPath))
            .digest('hex'),
          targetGroup: { id: groupId, name: GROUP_NAME },
          summary: {
            selectedBooks: manifest.books.length,
            parsedBooks: books.length,
            parseFailures: failures.length,
            createBooks: books.filter((book) => book.disposition === 'create').length,
            skippedExistingBooks: books.filter((book) => book.disposition === 'skip-existing')
              .length,
            internalCollisions: internalCollisions.length,
            epubsToCreate: books.filter(
              (book) => book.disposition === 'create' && book.format === 'EPUB',
            ).length,
            pdfsToCreate: books.filter(
              (book) => book.disposition === 'create' && book.format === 'PDF',
            ).length,
            sourceBytesToCreate: books
              .filter((book) => book.disposition === 'create')
              .reduce((sum, book) => sum + book.fileSize, 0),
          },
          failures,
          internalCollisions,
          books,
        };
        writeFileSync(join(outputDirectory, 'calibre-book-plan.json'), `${JSON.stringify(plan)}\n`);
        console.log(`CALIBRE_BOOK_PLAN ${JSON.stringify(plan.summary)}`);
        expect(failures).toEqual([]);
        expect(internalCollisions).toEqual([]);
        expect(books).toHaveLength(290);
      },
      30 * 60 * 1000,
    );
  },
);
