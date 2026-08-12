import { useEffect } from 'react';
import { useEnv } from '@/context/EnvContext';
import { useSettingsStore } from '@/store/settingsStore';
import { checkForAppUpdates, checkAppReleaseNotes } from '@/helpers/updater';
import { UPDATE_CHECK_POLL_SEC } from '@/services/constants';
import { useTranslation } from './useTranslation';

/**
 * Asks whether an update check is due at every opportunity the app gets, rather
 * than trying to schedule the checks themselves. `checkForAppUpdates` decides
 * from a persisted timestamp, so asking is cheap and asking often is harmless.
 *
 * The opportunities, and the gap each one closes:
 *
 *   mount            - app was closed when a check came due
 *   poll             - app has stayed open past the interval
 *   window re-focus  - machine slept, or the window sat in a throttled
 *                      background tab where timers do not fire on time
 *   network restored - a check failed while offline and is still overdue
 *
 * A timer alone covers none of the last three: sleep, suspension and quit all
 * interfere with when it fires, while the persisted stamp survives all of them.
 */
export const useAutoUpdateCheck = () => {
  const _ = useTranslation();
  const { appService } = useEnv();
  const { settings } = useSettingsStore();
  const hasUpdater = appService?.hasUpdater;
  const { autoCheckUpdates, updateChannel } = settings;

  useEffect(() => {
    if (hasUpdater === undefined) return;

    // Builds without an updater (the web app) show release notes instead. That
    // is keyed on the version already shown, so it is a mount-time concern and
    // not something to re-run on every opportunity below.
    if (!hasUpdater) {
      checkAppReleaseNotes();
      return;
    }
    if (!autoCheckUpdates) return;

    let disposed = false;
    const maybeCheckForUpdates = () => {
      if (disposed) return;
      // Fire-and-forget: auto-checks swallow their own failures.
      void checkForAppUpdates(_, true, updateChannel);
    };

    maybeCheckForUpdates();
    const poll = setInterval(maybeCheckForUpdates, UPDATE_CHECK_POLL_SEC * 1000);
    // No dedicated resume-from-sleep event exists in a webview; regaining
    // visibility is the signal that the machine and window are live again.
    const onVisible = () => {
      if (document.visibilityState === 'visible') maybeCheckForUpdates();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', maybeCheckForUpdates);
    window.addEventListener('online', maybeCheckForUpdates);

    return () => {
      disposed = true;
      clearInterval(poll);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', maybeCheckForUpdates);
      window.removeEventListener('online', maybeCheckForUpdates);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUpdater, autoCheckUpdates, updateChannel]);
};
