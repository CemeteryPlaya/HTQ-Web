/**
 * Клиент портала поставщика (`/api/tender/v1/supplier/<token>/…`, план
 * этапа 3 §1).
 *
 * Поставщик анонимен: доступ — по токену ссылки и cookie устройства
 * (`HttpOnly`, путь `/api/tender/v1/supplier/`). Поэтому НЕ общий axios
 * `api/client.ts`: его интерсептор подставил бы JWT сотрудника, открывшего
 * ссылку в том же браузере, и уводил бы на /login при 401. Здесь — голый
 * `fetch`: `credentials: 'include'` (cookie устройства), JSON-тело, без
 * `Authorization`. Отказ — `PortalError` с кодом конверта
 * `{detail, code, fields, details}` и секундами `Retry-After` (429).
 */
import type {
  OfferInput, PortalCard, PortalFile, PortalOffer, PortalTender,
} from './types';

export class PortalError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string | null;
  readonly fields: { field: string; message: string }[];
  readonly details: Record<string, unknown> | null;
  /** Секунды из `Retry-After` (429), иначе `null`. */
  readonly retryAfter: number | null;

  constructor(init: {
    status: number; code?: string | null; detail?: string | null;
    fields?: { field: string; message: string }[]; details?: Record<string, unknown> | null;
    retryAfter?: number | null;
  }) {
    super(init.detail ?? `HTTP ${init.status}`);
    this.name = 'PortalError';
    this.status = init.status;
    this.code = init.code ?? null;
    this.detail = init.detail ?? null;
    this.fields = init.fields ?? [];
    this.details = init.details ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }
}

export function portalBase(token: string): string {
  const raw = (import.meta.env.VITE_API_BASE_URL ?? '/api').toString();
  return `${raw.replace(/\/+$/, '')}/tender/v1/supplier/${encodeURIComponent(token)}`;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  json?: unknown;
  form?: FormData;
}

function parse(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

async function request<T>(token: string, path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.json);
  } else if (options.form) {
    // Content-Type с границей multipart ставит браузер сам.
    body = options.form;
  }

  let response: Awaited<ReturnType<typeof fetch>>;
  try {
    response = await fetch(`${portalBase(token)}${path}`, {
      method, headers, body, credentials: 'include',
    });
  } catch {
    throw new PortalError({ status: 0 });
  }

  const data = parse(await response.text().catch(() => ''));
  if (response.ok) return (data ?? null) as T;

  const envelope = (data && typeof data === 'object' ? data : {}) as {
    detail?: unknown; code?: unknown; fields?: unknown; details?: unknown;
  };
  const details = envelope.details && typeof envelope.details === 'object'
    ? envelope.details as Record<string, unknown> : null;
  // Заголовок, иначе `details.retry_after` конверта (заголовок может срезать
  // прокси); у 429 самого nginx нет ни того, ни другого.
  const seconds = (value: unknown) => {
    const parsed = Number(value);
    return value !== null && value !== '' && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  };
  throw new PortalError({
    status: response.status,
    code: typeof envelope.code === 'string' ? envelope.code : null,
    detail: typeof envelope.detail === 'string' ? envelope.detail : null,
    fields: Array.isArray(envelope.fields) ? envelope.fields as { field: string; message: string }[] : [],
    details,
    retryAfter: seconds(response.headers.get('Retry-After')) ?? seconds(details?.retry_after),
  });
}

export const portalApi = {
  card: (token: string) => request<PortalCard>(token, ''),
  bind: (token: string) => request<unknown>(token, '/bind', { method: 'POST', json: {} }),
  tender: (token: string) => request<PortalTender>(token, '/tender'),
  /** Файл ТЗ — обычная ссылка: сервер отвечает 302 на скачивание, cookie идёт сама. */
  fileHref: (token: string, docId: string) => `${portalBase(token)}/files/${encodeURIComponent(docId)}`,
  offer: (token: string) => request<PortalOffer>(token, '/offer'),
  saveOffer: (token: string, body: OfferInput) =>
    request<PortalOffer>(token, '/offer', { method: 'PUT', json: body }),
  submit: (token: string, body: { version: number; pd_consent?: boolean }) =>
    request<PortalOffer>(token, '/offer/submit', { method: 'POST', json: body }),
  withdraw: (token: string, body: { version: number }) =>
    request<PortalOffer>(token, '/offer/withdraw', { method: 'POST', json: body }),
  decline: (token: string, body: { reason: string }) =>
    request<unknown>(token, '/decline', { method: 'POST', json: body }),
  files: (token: string) => request<PortalFile[]>(token, '/offer/files'),
  uploadFile: (token: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<PortalFile>(token, '/offer/files', { method: 'POST', form });
  },
  removeFile: (token: string, docId: string) =>
    request<null>(token, `/offer/files/${encodeURIComponent(docId)}`, { method: 'DELETE' }),
};

export const portalKeys = {
  all: (token: string) => ['tender-portal', token] as const,
  card: (token: string) => ['tender-portal', token, 'card'] as const,
  tender: (token: string) => ['tender-portal', token, 'tender'] as const,
  offer: (token: string) => ['tender-portal', token, 'offer'] as const,
  files: (token: string) => ['tender-portal', token, 'files'] as const,
};
