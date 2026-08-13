import * as CFI from 'foliate-js/epubcfi.js';
import { BookDoc } from '@/libs/document';
import { BookNote, HighlightColor, HighlightStyle } from '@/types/book';
import { getIndexFromCfi } from '@/utils/cfi';

const APPLE_BOOKS_EXPORT_FORMAT = 'readest-apple-books-annotations';
const APPLE_BOOKS_EXPORT_VERSION = 1;
const EPUB_CFI_PATTERN = /^epubcfi\(.+\)$/;

/** One Apple Books highlight or note in the portable Readest interchange file. */
export interface AppleBooksExportAnnotation {
  uuid: string;
  cfi: string;
  selectedText: string;
  note: string;
  style: number;
  createdAt: number;
  updatedAt: number;
}

/** Book identity recorded alongside Apple Books annotations. */
export interface AppleBooksExportBook {
  assetId: string;
  title: string;
  author: string;
  epubId?: string;
}

/** Versioned file emitted by the companion Apple Books exporter. */
export interface AppleBooksAnnotationsExport {
  format: typeof APPLE_BOOKS_EXPORT_FORMAT;
  version: typeof APPLE_BOOKS_EXPORT_VERSION;
  /** Unix epoch milliseconds used as the Readest sync-visible migration time. */
  exportedAt: number;
  book: AppleBooksExportBook;
  annotations: AppleBooksExportAnnotation[];
}

/** Conversion result after checking source CFIs against the opened EPUB. */
export interface AppleBooksLocationResult {
  notes: BookNote[];
  unmatched: number;
  total: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isFiniteTimestamp = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

const isAppleBooksExportAnnotation = (value: unknown): value is AppleBooksExportAnnotation => {
  if (!isRecord(value)) return false;
  return (
    typeof value['uuid'] === 'string' &&
    value['uuid'].length > 0 &&
    typeof value['cfi'] === 'string' &&
    EPUB_CFI_PATTERN.test(value['cfi']) &&
    typeof value['selectedText'] === 'string' &&
    typeof value['note'] === 'string' &&
    typeof value['style'] === 'number' &&
    Number.isInteger(value['style']) &&
    isFiniteTimestamp(value['createdAt']) &&
    isFiniteTimestamp(value['updatedAt'])
  );
};

const isAppleBooksExportBook = (value: unknown): value is AppleBooksExportBook => {
  if (!isRecord(value)) return false;
  return (
    typeof value['assetId'] === 'string' &&
    typeof value['title'] === 'string' &&
    value['title'].length > 0 &&
    typeof value['author'] === 'string' &&
    (value['epubId'] === undefined || typeof value['epubId'] === 'string')
  );
};

/** Parse a versioned Apple Books annotation export, rejecting partial or unrelated JSON. */
export const parseAppleBooksAnnotationsExport = (
  content: string,
): AppleBooksAnnotationsExport | null => {
  try {
    const value: unknown = JSON.parse(content);
    if (!isRecord(value)) return null;
    if (
      value['format'] !== APPLE_BOOKS_EXPORT_FORMAT ||
      value['version'] !== APPLE_BOOKS_EXPORT_VERSION ||
      !isFiniteTimestamp(value['exportedAt']) ||
      !isAppleBooksExportBook(value['book']) ||
      !Array.isArray(value['annotations']) ||
      !value['annotations'].every(isAppleBooksExportAnnotation)
    ) {
      return null;
    }
    return value as unknown as AppleBooksAnnotationsExport;
  } catch {
    return null;
  }
};

const mapAppleBooksStyle = (style: number): { style: HighlightStyle; color: HighlightColor } => {
  switch (style) {
    case 0:
      return { style: 'underline', color: 'red' };
    case 1:
      return { style: 'highlight', color: 'green' };
    case 2:
      return { style: 'highlight', color: 'blue' };
    case 4:
      return { style: 'highlight', color: 'red' };
    case 5:
      return { style: 'highlight', color: 'violet' };
    case 3:
    default:
      return { style: 'highlight', color: 'yellow' };
  }
};

/** Convert Apple Books annotations without changing their EPUB CFI locations. */
export const convertAppleBooksExportToBookNotes = (
  data: AppleBooksAnnotationsExport,
): BookNote[] => {
  const byId = new Map<string, BookNote>();
  for (const annotation of data.annotations) {
    const appearance = mapAppleBooksStyle(annotation.style);
    const id = `apple-books-${annotation.uuid.toLowerCase()}`;
    byId.set(id, {
      id,
      type: 'annotation',
      cfi: annotation.cfi,
      text: annotation.selectedText,
      style: appearance.style,
      color: appearance.color,
      note: annotation.note,
      createdAt: annotation.createdAt,
      // Readest pulls annotations by updatedAt. Using Apple's historical
      // modification timestamp can place a newly imported note behind an
      // existing device cursor, making it invisible on that device. The file's
      // stable export timestamp propagates the migration and stays idempotent
      // when the same file is imported again.
      updatedAt: data.exportedAt,
    });
  }
  return Array.from(byId.values());
};

const normalizeBookTitle = (title: string): string =>
  title
    .normalize('NFKD')
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();

/** Compare book titles while tolerating punctuation and a missing subtitle. */
export const titlesLikelyReferToSameBook = (first: string, second: string): boolean => {
  const normalizedFirst = normalizeBookTitle(first);
  const normalizedSecond = normalizeBookTitle(second);
  if (!normalizedFirst || !normalizedSecond) return false;
  return (
    normalizedFirst === normalizedSecond ||
    normalizedFirst.startsWith(`${normalizedSecond} `) ||
    normalizedSecond.startsWith(`${normalizedFirst} `)
  );
};

type TextSourcePosition = {
  node: Text;
  offset: number;
};

const normalizeSelectedText = (text: string): string => text.replace(/\s+/gu, ' ').trim();

/** Find selected text across adjacent EPUB text nodes while normalizing whitespace. */
const findSelectedTextRange = (doc: Document, selectedText: string): Range | null => {
  if (!doc.body) return null;
  const target = normalizeSelectedText(selectedText);
  if (!target) return null;

  let normalized = '';
  const positions: TextSourcePosition[] = [];
  let pendingWhitespace: TextSourcePosition | null = null;
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode() as Text | null;
  while (node) {
    const parentName = node.parentElement?.tagName.toLocaleLowerCase();
    if (parentName !== 'script' && parentName !== 'style') {
      for (let offset = 0; offset < node.data.length; offset += 1) {
        const character = node.data[offset]!;
        if (/\s/u.test(character)) {
          if (normalized.length > 0) pendingWhitespace = { node, offset };
          continue;
        }
        if (pendingWhitespace) {
          normalized += ' ';
          positions.push(pendingWhitespace);
          pendingWhitespace = null;
        }
        normalized += character;
        positions.push({ node, offset });
      }
    }
    node = walker.nextNode() as Text | null;
  }

  let start = normalized.indexOf(target);
  if (start < 0) start = normalized.toLocaleLowerCase().indexOf(target.toLocaleLowerCase());
  if (start < 0) return null;

  const startPosition = positions[start];
  const endPosition = positions[start + target.length - 1];
  if (!startPosition || !endPosition) return null;

  const range = doc.createRange();
  range.setStart(startPosition.node, startPosition.offset);
  range.setEnd(endPosition.node, endPosition.offset + 1);
  return range;
};

const resolveSourceCfiRange = (doc: Document, cfi: string): Range | null => {
  try {
    const range = CFI.toRange(doc, CFI.parse(cfi));
    return range instanceof Range ? range : null;
  } catch {
    return null;
  }
};

const canonicalizeRangeCfi = (sectionCfi: string, range: Range): string | null => {
  try {
    return CFI.joinIndir(sectionCfi, CFI.fromRange(range));
  } catch {
    return null;
  }
};

/**
 * Locate Apple Books highlights in the opened EPUB and rebuild canonical Readest CFIs.
 * Exact source CFIs are preferred; selected-text search recovers annotations when markup moved.
 */
export const locateAppleBooksAnnotationsInBook = async (
  data: AppleBooksAnnotationsExport,
  bookDoc: BookDoc,
): Promise<AppleBooksLocationResult> => {
  const sourceNotes = convertAppleBooksExportToBookNotes(data);
  const sections = bookDoc.sections ?? [];
  const documentCache = new Map<number, Document | null>();

  const loadSectionDocument = async (index: number): Promise<Document | null> => {
    if (documentCache.has(index)) return documentCache.get(index) ?? null;
    const section = sections[index];
    if (!section?.createDocument) {
      documentCache.set(index, null);
      return null;
    }
    try {
      const doc = await section.createDocument();
      documentCache.set(index, doc);
      return doc;
    } catch {
      documentCache.set(index, null);
      return null;
    }
  };

  const notes: BookNote[] = [];
  let unmatched = 0;
  for (const sourceNote of sourceNotes) {
    const preferredIndex = getIndexFromCfi(sourceNote.cfi);
    let located: { sectionIndex: number; range: Range } | null = null;

    if (preferredIndex !== null && preferredIndex >= 0 && preferredIndex < sections.length) {
      const doc = await loadSectionDocument(preferredIndex);
      const sourceRange = doc ? resolveSourceCfiRange(doc, sourceNote.cfi) : null;
      if (
        sourceRange &&
        normalizeSelectedText(sourceRange.toString()) ===
          normalizeSelectedText(sourceNote.text ?? '')
      ) {
        located = { sectionIndex: preferredIndex, range: sourceRange };
      }
    }

    if (!located) {
      const searchOrder = sections.map((_section, index) => index);
      if (preferredIndex !== null && searchOrder.includes(preferredIndex)) {
        searchOrder.splice(searchOrder.indexOf(preferredIndex), 1);
        searchOrder.unshift(preferredIndex);
      }
      for (const sectionIndex of searchOrder) {
        const doc = await loadSectionDocument(sectionIndex);
        const range = doc ? findSelectedTextRange(doc, sourceNote.text ?? '') : null;
        if (range) {
          located = { sectionIndex, range };
          break;
        }
      }
    }

    if (!located) {
      unmatched += 1;
      continue;
    }
    const section = sections[located.sectionIndex]!;
    const cfi = canonicalizeRangeCfi(section.cfi, located.range);
    if (!cfi) {
      unmatched += 1;
      continue;
    }
    notes.push({ ...sourceNote, cfi });
  }

  return { notes, unmatched, total: sourceNotes.length };
};
