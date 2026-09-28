/**
 * Экспорт реестра в xlsx (ТЗ §19 «экспорт в xlsx текущей выборки, до 50 000
 * строк», D-32, серверная часть — `apps/bpp/services/core/export.py`).
 *
 * Отдельной ручки экспорта на каждый реестр нет: реестр отвечает на свой же
 * адрес с фильтрами текущей выборки и параметром `format=xlsx`
 * (`export.respond` в ручке реестра). Ответ бывает двух видов:
 * - до 10 000 строк — сам файл (`Content-Disposition: attachment`);
 * - больше — JSON `{id, status: "queued", detail}`: файл собирается в фоне,
 *   ссылка придёт уведомлением центра на экран `/bpp/exports/<id>`.
 * Больше 50 000 — 422 `E-EXP-01` с объяснением.
 *
 * JSON без `status: "queued"` и `id` — не «выгрузка поставлена в очередь», а
 * ответ ручки, которая `format=xlsx` не знает и вернула обычный список
 * реестра: такой ответ — ошибка «Реестр не поддерживает выгрузку», а не
 * молчаливая «успешная» очередь без выгрузки.
 *
 * Запрос идёт с `responseType: 'blob'`, поэтому и JSON фоновой ветки, и тело
 * ошибки приходят Blob'ом — здесь они разбираются обратно в объект, иначе
 * `reportApiError` не увидел бы текста сервера.
 */
import i18next from '@/i18n';
import api from '@/api/client';

export const EXPORT_FORMAT_PARAM = 'format';
export const EXPORT_FORMAT = 'xlsx';

export type ExportOutcome =
  | { kind: 'file'; filename: string }
  | { kind: 'queued'; id: string; detail: string };

const isJsonBlob = (data: unknown): data is Blob =>
  typeof Blob !== 'undefined' && data instanceof Blob && /json/i.test(data.type);

async function blobJson(blob: Blob): Promise<unknown> {
  try {
    return JSON.parse(await blob.text());
  } catch {
    return null;
  }
}

/** Имя из `Content-Disposition`: `filename*=utf-8''…` (кириллица) или `filename="…"`. */
export function filenameFromDisposition(header: string | undefined, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*(?:utf-8|UTF-8)''([^;]+)/.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      // Кривое кодирование — берём простое имя ниже.
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(header);
  return plain ? plain[1].trim() : fallback;
}

/** Сколько держать объектный URL после клика: браузер начинает скачивание
 * асинхронно, и отозванный сразу URL в части браузеров (Firefox, старый
 * Safari) обрывает его. */
const REVOKE_DELAY_MS = 1000;

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}

/** Ответ-JSON, который не является постановкой выгрузки в очередь. */
export class ExportNotSupportedError extends Error {
  constructor() {
    super(i18next.t(
      'bpp.registry.exportUnsupported',
      'Реестр не поддерживает выгрузку в xlsx. Сообщите администратору.',
    ));
    this.name = 'ExportNotSupportedError';
  }
}

interface QueuedBody {
  id?: unknown;
  status?: unknown;
  detail?: unknown;
}

export async function exportRegistry(
  endpoint: string,
  selection: Record<string, string>,
  fallbackName: string,
): Promise<ExportOutcome> {
  try {
    const res = await api.get(endpoint, {
      params: { ...selection, [EXPORT_FORMAT_PARAM]: EXPORT_FORMAT },
      responseType: 'blob',
    });
    const data = res.data as unknown;
    if (isJsonBlob(data)) {
      const body = (await blobJson(data)) as QueuedBody | null;
      if (body?.status === 'queued' && body.id) {
        return { kind: 'queued', id: String(body.id), detail: String(body.detail ?? '') };
      }
      throw new ExportNotSupportedError();
    }
    const headers = (res.headers ?? {}) as Record<string, string | undefined>;
    const filename = filenameFromDisposition(
      headers['content-disposition'], `${fallbackName}.xlsx`);
    saveBlob(data as Blob, filename);
    return { kind: 'file', filename };
  } catch (error) {
    const response = (error as { response?: { data?: unknown } })?.response;
    if (response && isJsonBlob(response.data)) {
      response.data = await blobJson(response.data);
    }
    throw error;
  }
}
