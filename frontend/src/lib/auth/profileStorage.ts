import type { UserProfile } from '@/types/userProfile';

export const ACCESS_TOKEN_KEY = 'access';
export const REFRESH_TOKEN_KEY = 'refresh';
export const CACHED_PROFILE_KEY = 'cached_profile';
const DEFAULT_AUTH_COOKIE_TTL_DAYS = 30;
const AUTH_COOKIE_TTL_DAYS = Number(import.meta.env.VITE_AUTH_COOKIE_TTL_DAYS ?? DEFAULT_AUTH_COOKIE_TTL_DAYS);

export const profileQueryKey = ['profile'] as const;

const isBrowser = (): boolean =>
  typeof window !== 'undefined' && typeof document !== 'undefined';

const resolveCookieTtlDays = (): number => {
  if (!Number.isFinite(AUTH_COOKIE_TTL_DAYS) || AUTH_COOKIE_TTL_DAYS <= 0) {
    return DEFAULT_AUTH_COOKIE_TTL_DAYS;
  }
  return AUTH_COOKIE_TTL_DAYS;
};

const readLocalStorage = (key: string): string | null => {
  if (!isBrowser()) {
    return null;
  }

  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

const writeLocalStorage = (key: string, value: string): void => {
  if (!isBrowser()) {
    return;
  }

  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore storage quota / privacy mode errors
  }
};

const removeLocalStorage = (key: string): void => {
  if (!isBrowser()) {
    return;
  }

  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore storage quota / privacy mode errors
  }
};

const readCookie = (name: string): string | null => {
  if (!isBrowser()) {
    return null;
  }

  const encodedName = `${encodeURIComponent(name)}=`;
  const chunks = document.cookie ? document.cookie.split('; ') : [];
  for (const chunk of chunks) {
    if (chunk.startsWith(encodedName)) {
      return decodeURIComponent(chunk.slice(encodedName.length));
    }
  }
  return null;
};

const writeCookie = (name: string, value: string): void => {
  if (!isBrowser()) {
    return;
  }

  const expiresAt = new Date(
    Date.now() + resolveCookieTtlDays() * 24 * 60 * 60 * 1000,
  ).toUTCString();
  const secureAttr = window.location.protocol === 'https:' ? '; Secure' : '';

  document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Expires=${expiresAt}; Path=/; SameSite=Lax${secureAttr}`;
};

const removeCookie = (name: string): void => {
  if (!isBrowser()) {
    return;
  }

  const secureAttr = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${encodeURIComponent(name)}=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/; SameSite=Lax${secureAttr}`;
};

export const setAccessToken = (token: string): void => {
  if (!token) {
    return;
  }
  writeLocalStorage(ACCESS_TOKEN_KEY, token);
  writeCookie(ACCESS_TOKEN_KEY, token);
};

export const setRefreshToken = (token: string): void => {
  if (!token) {
    return;
  }
  writeLocalStorage(REFRESH_TOKEN_KEY, token);
  writeCookie(REFRESH_TOKEN_KEY, token);
};

export const setAuthTokens = (tokens: {
  access?: string;
  refresh?: string;
}): void => {
  if (tokens.access) {
    setAccessToken(tokens.access);
  }
  if (tokens.refresh) {
    setRefreshToken(tokens.refresh);
  }
};

export const getAccessToken = (): string | null => {
  if (!isBrowser()) {
    return null;
  }

  const cookieToken = readCookie(ACCESS_TOKEN_KEY);
  if (cookieToken) {
    return cookieToken;
  }

  const localToken = readLocalStorage(ACCESS_TOKEN_KEY);
  if (localToken) {
    writeCookie(ACCESS_TOKEN_KEY, localToken);
  }
  return localToken;
};

export const getRefreshToken = (): string | null => {
  if (!isBrowser()) {
    return null;
  }

  const cookieToken = readCookie(REFRESH_TOKEN_KEY);
  if (cookieToken) {
    return cookieToken;
  }

  const localToken = readLocalStorage(REFRESH_TOKEN_KEY);
  if (localToken) {
    writeCookie(REFRESH_TOKEN_KEY, localToken);
  }
  return localToken;
};

export const readCachedProfile = (): UserProfile | null => {
  if (!isBrowser()) {
    return null;
  }

  const cached = readLocalStorage(CACHED_PROFILE_KEY);
  if (!cached) {
    return null;
  }

  try {
    return JSON.parse(cached) as UserProfile;
  } catch {
    removeLocalStorage(CACHED_PROFILE_KEY);
    return null;
  }
};

export const writeCachedProfile = (profile: UserProfile): void => {
  if (!isBrowser()) {
    return;
  }
  writeLocalStorage(CACHED_PROFILE_KEY, JSON.stringify(profile));
};

export const clearAuthStorage = (): void => {
  if (!isBrowser()) {
    return;
  }

  // Fire-and-forget audit event BEFORE dropping the token, so the request
  // still carries the Authorization header and Loki can attribute the logout.
  try {
    // Dynamic import to avoid circular dependency at module init.
    void import('@/lib/telemetry').then(({ logUserAction }) => {
      logUserAction({ action: 'logout' });
    });
  } catch {
    // ignore — telemetry must never break logout.
  }

  removeLocalStorage(ACCESS_TOKEN_KEY);
  removeLocalStorage(REFRESH_TOKEN_KEY);
  removeLocalStorage(CACHED_PROFILE_KEY);

  removeCookie(ACCESS_TOKEN_KEY);
  removeCookie(REFRESH_TOKEN_KEY);
};
