import { getAccessToken } from '@/lib/auth/profileStorage';

type NetworkInfo = {
  effectiveType?: 'slow-2g' | '2g' | '3g' | '4g';
  saveData?: boolean;
};

const getIdleCallback = () => {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.requestIdleCallback ?? ((callback: () => void) => window.setTimeout(callback, 200));
};

const shouldSkipPrefetch = (): boolean => {
  const connection = (navigator as Navigator & { connection?: NetworkInfo }).connection;
  if (!connection) {
    return false;
  }

  if (connection.saveData) {
    return true;
  }

  return connection.effectiveType === 'slow-2g' || connection.effectiveType === '2g' || connection.effectiveType === '3g';
};

export const registerRoutePrefetch = (): void => {
  if (typeof window === 'undefined') {
    return;
  }

  if (shouldSkipPrefetch()) {
    return;
  }

  const idleCallback = getIdleCallback();
  if (!idleCallback) {
    return;
  }

  window.addEventListener(
    'load',
    () => {
      window.setTimeout(() => {
        idleCallback(() => {
          import('@/pages/Projects');
          import('@/pages/Services');
          import('@/pages/News');
          import('@/pages/Contacts');

          if (getAccessToken()) {
            import('@/components/RequireAuth');
            import('@/components/BottomNav');
            import('@/pages/MyProfile');
          }
        });
      }, 2500);
    },
    { once: true },
  );
};
