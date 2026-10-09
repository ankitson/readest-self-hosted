'use client';

import { useEffect } from 'react';
import { useEnv } from '@/context/EnvContext';
import { useAppUrlIngress } from '@/hooks/useAppUrlIngress';
import { useOpenWithBooks } from '@/hooks/useOpenWithBooks';
import { useOpenLaunchLinks } from '@/hooks/useOpenLaunchLinks';
import { useHomeScreenWidgets } from '@/hooks/useHomeScreenWidgets';
import { useOpenShareLink } from '@/hooks/useOpenShareLink';
import { useOpenDeviceLink } from '@/hooks/useOpenDeviceLink';
import { useClipUrlIngress } from '@/hooks/useClipUrlIngress';
import { useRestoreLibraryOnRelaunch } from '@/hooks/useRestoreLibraryOnRelaunch';
import { useSettingsStore } from '@/store/settingsStore';
import { useAutoUpdateCheck } from '@/hooks/useAutoUpdateCheck';
import { tauriHandleSetAlwaysOnTop } from '@/utils/window';
import ClipSignInAlert from '@/components/ClipSignInAlert';
import Reader from './components/Reader';

// This is only used for the Tauri app in the app router
export default function Page() {
  const { appService } = useEnv();
  const { settings } = useSettingsStore();

  useAppUrlIngress();
  useOpenWithBooks();
  useOpenLaunchLinks();
  useHomeScreenWidgets();
  useOpenShareLink();
  useOpenDeviceLink();
  useClipUrlIngress();
  useRestoreLibraryOnRelaunch();

  useAutoUpdateCheck();

  useEffect(() => {
    if (appService?.hasWindow && settings.alwaysOnTop) {
      tauriHandleSetAlwaysOnTop(settings.alwaysOnTop);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appService?.hasWindow, settings.alwaysOnTop]);

  return (
    <>
      <Reader />
      <ClipSignInAlert />
    </>
  );
}
