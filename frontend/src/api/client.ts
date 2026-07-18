/**
 * api/client.ts
 * Центральный HTTP-клиент приложения на базе Axios.
 *
 * - Автоматически подставляет JWT-токен из localStorage в каждый запрос.
 * - При 401/403 пытается обновить токен (refresh) и повторить запрос.
 * - Публичные маршруты (регистрация, обратная связь) отправляются без токена.
 */

import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';
import {
  clearAuthStorage,
  getAccessToken,
  getRefreshToken,
  setAuthTokens,
} from '@/lib/auth/profileStorage';
import { apiPath } from '@/api/endpoints';
import { emitServiceDisabled } from '@/lib/serviceUnavailableBus';

// ---------------------------------------------------------------------------
// Конфигурация
// ---------------------------------------------------------------------------

/**
 * Базовый URL API.
 * - Dev: Vite-прокси перенаправляет /api → http://127.0.0.1:8000
 * - Prod: Nginx проксирует /api → backend-контейнер
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/';

/** Маршруты, которые не требуют авторизации (POST-запросы). */
const PUBLIC_POST_ROUTES = [
  apiPath('cms', 'contact-requests/'),
  apiPath('users', 'register/'),
];

/** Маршруты, к которым не применяется автообновление токена. */
const AUTH_ENDPOINTS = [
  apiPath('users', 'token/'),
  apiPath('users', 'register/'),
];

const client = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'ngrok-skip-browser-warning': 'true',
  },
});

// ---------------------------------------------------------------------------
// Перехватчик запросов: подстановка JWT-токена
// ---------------------------------------------------------------------------

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const url = config.url ?? '';
  const isPublicPost =
    config.method === 'post' && PUBLIC_POST_ROUTES.some((r) => url.includes(r));

  if (!isPublicPost) {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// ---------------------------------------------------------------------------
// Перехватчик ответов: автообновление токена при 401 / 403 + обработка 500
// ---------------------------------------------------------------------------

/**
 * Глобальный флаг обновления токена.
 * Предотвращает одновременный запуск нескольких refresh-запросов,
 * когда несколько параллельных запросов одновременно получают 401.
 */
let _isRefreshing = false;
let _refreshPromise: Promise<string> | null = null;

/**
 * Выполняет одну попытку обновления токена через /api/users/v1/token/refresh/.
 * Возвращает новый access-токен или выбрасывает ошибку.
 */
async function doTokenRefresh(): Promise<string> {
  const refresh = getRefreshToken();
  if (!refresh) throw new Error('Refresh-токен отсутствует');

  const res = await axios.post(
    API_BASE + apiPath('users', 'token/refresh/'),
    { refresh },
    {
      withCredentials: true,
      headers: { 'ngrok-skip-browser-warning': 'true' },
    },
  );

  const nextAccess: string | undefined = res?.data?.access;
  if (!nextAccess) throw new Error('Refresh response does not contain access token');

  setAuthTokens({ access: nextAccess, refresh: res?.data?.refresh });
  client.defaults.headers.common['Authorization'] = `Bearer ${nextAccess}`;
  return nextAccess;
}

/**
 * Очищает авторизационные данные и выполняет одно перенаправление на /login.
 * Повторные вызовы игнорируются, если редирект уже происходит.
 */
function forceLogout(): void {
  clearAuthStorage();
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
}

/**
 * Извлекает читаемое сообщение об ошибке из тела ответа сервера.
 */
function extractServerErrorMessage(
  data: unknown,
  fallback: string,
): string {
  if (!data) return fallback;
  if (typeof data === 'string') return data || fallback;
  const d = data as Record<string, unknown>;
  const msg = d.detail ?? d.error ?? d.message;
  if (typeof msg === 'string' && msg) return msg;
  return fallback;
}

/**
 * Если ответ — пагинированный envelope, раскрываем его в массив `items`.
 *
 * Поддерживаемые формы:
 *   - FastAPI hr-service: `{items, total, page, pages, limit}` ровно — без
 *     лишних полей. Если эндпоинт добавляет свои метаданные (`unread_total`,
 *     `facets`, и т.п.), это уже extended-envelope, и unwrap его не трогает —
 *     потребитель сам читает нужные поля.
 *   - Django-style legacy: `{results, count, next, previous}`
 *
 * Любая другая форма (одиночный объект, массив, скаляр) проходит без изменений.
 */
const FASTAPI_ENVELOPE_KEYS = new Set(['items', 'total', 'page', 'pages', 'limit']);

function unwrapPaginatedEnvelope(data: unknown): unknown {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  const d = data as Record<string, unknown>;
  // FastAPI envelope — ровно 5 полей, никаких extra
  if (
    Array.isArray(d.items) &&
    typeof d.total === 'number' &&
    typeof d.page === 'number' &&
    typeof d.pages === 'number' &&
    Object.keys(d).every((k) => FASTAPI_ENVELOPE_KEYS.has(k))
  ) {
    return d.items;
  }
  // Django-style envelope (kept as a safety net even after Django removal —
  // any new endpoint that accidentally returns this shape just works).
  if (
    Array.isArray(d.results) &&
    (typeof d.count === 'number' || 'next' in d || 'previous' in d)
  ) {
    return d.results;
  }
  return data;
}


client.interceptors.response.use(
  (response) => {
    if (response?.data !== undefined) {
      response.data = unwrapPaginatedEnvelope(response.data);
    }
    return response;
  },
  async (error: AxiosError) => {
    const config = error.config as AxiosRequestConfig & {
      _retry401?: boolean;
      _retry403?: boolean;
    };
    const url = config?.url ?? '';
    const isAuthEndpoint = AUTH_ENDPOINTS.some((ep) => url.includes(ep));
    const status = error.response?.status;

    // ── 503 с envelope service_disabled: аппка выключена в реестре (Task 0.5/0.7) ──
    // Только уведомляем UI (ServiceUnavailableListener открывает диалог) — без
    // ретраев и без 401/403-логики ниже. Продолжает падать в общую ветку 5xx.
    if (status === 503) {
      const data = error.response?.data as { code?: string; service?: string } | undefined;
      if (data?.code === 'service_disabled') {
        emitServiceDisabled(data.service ?? 'unknown');
      }
    }

    // ── 5xx: сервер упал — не повторяем запрос, возвращаем понятную ошибку ──
    // Важно: это предотвращает каскад 401-циклов после 500 на auth endpoint
    if (status !== undefined && status >= 500) {
      const serverMsg = extractServerErrorMessage(
        error.response?.data,
        `Внутренняя ошибка сервера (${status}). Попробуйте позже.`,
      );
      console.error(`[api] Ошибка ${status} на ${url}:`, serverMsg);
      return Promise.reject(Object.assign(new Error(serverMsg), { status, isServerError: true }));
    }

    // ── 401 на эндпоинте авторизации: неверные учётные данные, не обновляем токен ──
    if (status === 401 && isAuthEndpoint) {
      return Promise.reject(error);
    }

    // ── 401 на обычном эндпоинте: пробуем обновить токен (с блокировкой) ──
    if (status === 401 && !config._retry401) {
      config._retry401 = true;

      // Если обновление уже идёт — ждём его результата
      if (_isRefreshing && _refreshPromise) {
        try {
          const newToken = await _refreshPromise;
          const retryConfig = {
            ...config,
            headers: { ...config.headers, Authorization: `Bearer ${newToken}` },
          };
          return await client(retryConfig);
        } catch {
          return Promise.reject(error);
        }
      }

      // Запускаем единственный refresh-запрос
      _isRefreshing = true;
      _refreshPromise = doTokenRefresh().finally(() => {
        _isRefreshing = false;
        _refreshPromise = null;
      });

      try {
        const newToken = await _refreshPromise;
        const retryConfig = {
          ...config,
          headers: { ...config.headers, Authorization: `Bearer ${newToken}` },
        };
        return await client(retryConfig);
      } catch (refreshError) {
        console.error('[api] Не удалось обновить токен — выполняем выход', refreshError);
        forceLogout();
        return Promise.reject(refreshError);
      }
    }

    // ── 403: возможно устаревшие claims — одна попытка обновления ──
    if (status === 403 && !config._retry403 && !isAuthEndpoint) {
      config._retry403 = true;
      try {
        const newToken = _isRefreshing && _refreshPromise
          ? await _refreshPromise
          : await doTokenRefresh();
        const retryConfig = {
          ...config,
          headers: { ...config.headers, Authorization: `Bearer ${newToken}` },
        };
        return await client(retryConfig);
      } catch {
        console.warn('[api] 403 после обновления токена — реальный запрет доступа', url);
      }
    }

    return Promise.reject(error);
  },
);

// Для обратной совместимости (используется в устаревших компонентах)
(client as any).getClient = () => Promise.resolve(client);

export default client;
