import { useCallback, useState } from 'react';

import { useEnv } from '@/context/EnvContext';
import { useTranslation } from '@/hooks/useTranslation';
import { useFileSelector } from '@/hooks/useFileSelector';
import {
  locateAppleBooksAnnotationsInBook,
  parseAppleBooksAnnotationsExport,
  titlesLikelyReferToSameBook,
} from '@/services/annotation/providers/appleBooks';
import { mergeImportedBookNotes } from '@/services/annotation/providers/mrexpt';
import { useBookDataStore } from '@/store/bookDataStore';
import { useReaderStore } from '@/store/readerStore';
import { useSettingsStore } from '@/store/settingsStore';
import { eventDispatcher } from '@/utils/event';

/** Select, validate, locate, and persist one Apple Books annotation export for the open book. */
export const useAppleBooksAnnotationImport = (bookKey: string) => {
  const _ = useTranslation();
  const { envConfig, appService } = useEnv();
  const settings = useSettingsStore((state) => state.settings);
  const getBookData = useBookDataStore((state) => state.getBookData);
  const getConfig = useBookDataStore((state) => state.getConfig);
  const saveConfig = useBookDataStore((state) => state.saveConfig);
  const updateBooknotes = useBookDataStore((state) => state.updateBooknotes);
  const getViewsById = useReaderStore((state) => state.getViewsById);
  const { selectFiles } = useFileSelector(appService, _);
  const [isImportingAppleBooks, setIsImportingAppleBooks] = useState(false);

  const importAppleBooksAnnotations = useCallback(async () => {
    const bookData = getBookData(bookKey);
    const { bookDoc, book } = bookData ?? {};
    if (!bookDoc || !book) {
      eventDispatcher.dispatch('toast', {
        type: 'warning',
        message: _('Book is not ready yet, please try again.'),
        timeout: 2000,
      });
      return;
    }

    const result = await selectFiles({
      type: 'generic',
      accept: '.json,application/json',
      extensions: ['json'],
      multiple: false,
      dialogTitle: _('Select Apple Books Export File'),
    });
    if (result.error || result.files.length === 0) return;
    const selectedFile = result.files[0]!;

    let content = '';
    try {
      if (selectedFile.file) {
        content = await selectedFile.file.text();
      } else if (selectedFile.path) {
        content = (await appService?.readFile(selectedFile.path, 'None', 'text')) as string;
      }
    } catch (error) {
      console.warn('Apple Books annotation import could not read the selected file:', error);
    }

    const appleBooksExport = content ? parseAppleBooksAnnotationsExport(content) : null;
    if (!appleBooksExport) {
      eventDispatcher.dispatch('toast', {
        type: 'warning',
        message: _('This is not a valid Apple Books annotations export file.'),
        timeout: 3000,
      });
      return;
    }
    if (!titlesLikelyReferToSameBook(appleBooksExport.book.title, book.title)) {
      eventDispatcher.dispatch('toast', {
        type: 'warning',
        message: _('This Apple Books export is for a different book.'),
        timeout: 3000,
      });
      return;
    }

    setIsImportingAppleBooks(true);
    try {
      const conversion = await locateAppleBooksAnnotationsInBook(appleBooksExport, bookDoc);
      if (conversion.notes.length === 0) {
        eventDispatcher.dispatch('toast', {
          type: 'info',
          message: _('No annotations could be located in this book.'),
          timeout: 2500,
        });
        return;
      }

      const config = getConfig(bookKey)!;
      const { merged, applied, added, updated } = mergeImportedBookNotes(
        config.booknotes ?? [],
        conversion.notes,
      );
      const updatedConfig = updateBooknotes(bookKey, merged);
      if (updatedConfig) saveConfig(envConfig, bookKey, updatedConfig, settings);

      const views = getViewsById(bookKey.split('-')[0]!);
      for (const note of applied) {
        try {
          views.forEach((targetView) => targetView?.addAnnotation(note));
        } catch (error) {
          console.warn('Apple Books annotation import could not draw an annotation:', {
            note,
            error,
          });
        }
      }

      const imported = added + updated;
      let message =
        imported > 0
          ? _('Imported {{count}} annotations', { count: imported })
          : _('No new annotations to import');
      if (conversion.unmatched > 0) {
        message = _('Imported {{count}} annotations; {{unmatched}} could not be located', {
          count: imported,
          unmatched: conversion.unmatched,
        });
      }
      eventDispatcher.dispatch('toast', { type: 'info', message, timeout: 3500 });
    } catch (error) {
      console.warn('Apple Books annotation import failed:', error);
      eventDispatcher.dispatch('toast', {
        type: 'warning',
        message: _('Failed to import annotations.'),
        timeout: 3000,
      });
    } finally {
      setIsImportingAppleBooks(false);
    }
  }, [
    _,
    appService,
    bookKey,
    envConfig,
    getBookData,
    getConfig,
    getViewsById,
    saveConfig,
    selectFiles,
    settings,
    updateBooknotes,
  ]);

  return { importAppleBooksAnnotations, isImportingAppleBooks };
};
