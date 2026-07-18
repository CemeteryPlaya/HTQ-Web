/**
 * lib/telemetry.ts
 *
 * Клиентская телеметрия для пред-деплойного состояния.
 *
 * - `reportClientError` — шлёт fatal errors в backend (`/api/users/v1/client-errors`).
 *   Вызывается из React ErrorBoundary + глобальных обработчиков window.onerror и
 *   unhandledrejection.
 * - `logUserAction` — шлёт аудит user-action событий (login/logout/create/update/delete)
 *   в backend (`/api/users/v1/client-events`). Уровень — info, используется для
 *   построения графиков в Loki.
 *
 * Обе функции ничего не делают при неуспехе fetch (не ломаем UX). Они используют
 * `keepalive: true`, так что отправляются даже если страница уходит (unload/reload).
 */

const CLIENT_ERRORS_ENDPOINT = '/api/users/v1/client-errors';
const CLIENT_EVENTS_ENDPOINT = '/api/users/v1/client-events';

export interface ClientErrorReport {
  message: string;
  stack?: string;
  componentStack?: string;
  url?: string;
  userAgent?: string;
  userId?: number;
  timestamp?: string;
}

export interface UserAction {
  action: string; // "login_success", "logout", "employee_create", "task_transition", ...
  resource?: string;
  resourceId?: string | number;
  meta?: Record<string, unknown>;
}

function safeAuthHeader(): Record<string, string> {
  try {
    // Token key matches ACCESS_TOKEN_KEY in lib/auth/profileStorage.ts
    const token = localStorage.getItem('access');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function post(endpoint: string, payload: Record<string, unknown>): Promise<void> {
  try {
    await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...safeAuthHeader(),
      },
      body: JSON.stringify(payload),
      credentials: 'include',
      keepalive: true,
    });
  } catch {
    // Не ломаем UX если backend недоступен.
  }
}

export function reportClientError(err: ClientErrorReport): void {
  void post(CLIENT_ERRORS_ENDPOINT, {
    ...err,
    url: err.url ?? window.location.href,
    userAgent: err.userAgent ?? navigator.userAgent,
    timestamp: err.timestamp ?? new Date().toISOString(),
  });
}

export function logUserAction(evt: UserAction): void {
  void post(CLIENT_EVENTS_ENDPOINT, {
    ...evt,
    url: window.location.href,
    userAgent: navigator.userAgent,
    timestamp: new Date().toISOString(),
  });
}

/**
 * Хук глобальных обработчиков. Вызвать один раз в main.tsx при старте приложения.
 */
export function installGlobalErrorHandlers(): void {
  if (typeof window === 'undefined') return;

  window.addEventListener('error', (e: ErrorEvent) => {
    // Не логируем ошибки загрузки статики (404 на favicon и т.п.): у них error === null
    if (!e.error && !e.message) return;
    reportClientError({
      message: e.message || String(e.error),
      stack: e.error?.stack,
      url: window.location.href,
    });
  });

  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    const reason = e.reason;
    reportClientError({
      message:
        typeof reason === 'string'
          ? reason
          : reason?.message ?? String(reason ?? 'unhandledrejection'),
      stack: reason?.stack,
      url: window.location.href,
    });
  });
}
