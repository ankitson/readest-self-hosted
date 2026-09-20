import { getAPIBaseUrl } from '@/services/environment';
import { getUserID } from '@/utils/access';
import { fetchWithAuth } from '@/utils/fetch';

// Lazy, not module-level constants: this fork resolves the API base at runtime
// from the server switcher, so evaluating it at import time would bake in
// whichever server happened to be configured when the module first loaded.
const getUserDeleteApiEndpoint = () => `${getAPIBaseUrl()}/user/delete`;
const getUserLibraryApiEndpoint = () => `${getAPIBaseUrl()}/user/library`;

export const deleteUser = async () => {
  try {
    const userId = await getUserID();
    if (!userId) {
      throw new Error('Not authenticated');
    }

    await fetchWithAuth(getUserDeleteApiEndpoint(), {
      method: 'DELETE',
    });
  } catch (error) {
    console.error('User deletion failed:', error);
    throw new Error('User deletion failed');
  }
};

export const deleteCloudLibrary = async () => {
  try {
    const userId = await getUserID();
    if (!userId) {
      throw new Error('Not authenticated');
    }

    await fetchWithAuth(getUserLibraryApiEndpoint(), {
      method: 'DELETE',
    });
  } catch (error) {
    console.error('Cloud library deletion failed:', error);
    throw new Error('Cloud library deletion failed');
  }
};
