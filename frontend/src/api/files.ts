/**
 * Файловая подсистема ТЗ §21 — `UploadFile` / `DownloadFile` (apps.files).
 *
 * Документы любого объекта-владельца по ключу `ownerType` (`approvals.request`,
 * позже `contracts.agreement`) и id его строки. Загрузка — multipart без
 * ручного Content-Type: boundary проставит браузер (как
 * `signoffApi.attachDocument`). Каждое действие пользователя несёт свой
 * `Idempotency-Key`: повтор того же запроса (обрыв сети, двойной клик) сервер
 * отдаёт первым результатом, а не второй записью. Ошибки — в конверте D-28
 * (`{detail, code, fields, details}`), их разбирает `lib/apiError`.
 */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type { FileFolder, FileLink, FileTypeRow, FileVersion, OwnerId } from '@/types/files';

const BASE = `${API_ENDPOINTS.files}/`;

const ownerPath = (ownerType: string, ownerId: OwnerId) =>
  `${BASE}${ownerType}/${ownerId}/files/`;

/** Ключ повтора на одно действие пользователя (UUID v4).
 *
 *  `crypto.randomUUID` есть только в защищённом контексте (HTTPS, localhost),
 *  а платформу открывают и по голому IP — там его нет. `getRandomValues`
 *  доступен везде, из него UUID собирается по RFC 4122. */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const filesApi = {
  async list(ownerType: string, ownerId: OwnerId): Promise<FileFolder> {
    const { data } = await api.get(ownerPath(ownerType, ownerId));
    return data;
  },

  /** Новый документ — его версия 1. */
  async upload(
    ownerType: string, ownerId: OwnerId, file: File, fileType: string,
    idempotencyKey: string = newIdempotencyKey(),
  ): Promise<FileVersion> {
    const form = new FormData();
    form.append('file', file);
    form.append('file_type', fileType);
    const { data } = await api.post(ownerPath(ownerType, ownerId), form, {
      headers: { 'Idempotency-Key': idempotencyKey },
    });
    return data;
  },

  /** Новая версия поверх `baseFileId` — действующей версии, которую видел
   *  пользователь. Если её уже заменили, сервер ответит 409 E-CON-01. */
  async uploadVersion(
    ownerType: string, ownerId: OwnerId, documentId: string, file: File,
    baseFileId: number, idempotencyKey: string = newIdempotencyKey(),
  ): Promise<FileVersion> {
    const form = new FormData();
    form.append('file', file);
    form.append('base_file_id', String(baseFileId));
    const { data } = await api.post(
      `${ownerPath(ownerType, ownerId)}${documentId}/versions/`, form,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    );
    return data;
  },

  async remove(ownerType: string, ownerId: OwnerId, documentId: string): Promise<void> {
    await api.delete(`${ownerPath(ownerType, ownerId)}${documentId}/`);
  },

  /** `DownloadFile`: свежая временная ссылка на версию. */
  async link(
    ownerType: string, ownerId: OwnerId, documentId: string, fileId: number,
  ): Promise<FileLink> {
    const { data } = await api.get(
      `${ownerPath(ownerType, ownerId)}${documentId}/versions/${fileId}/link`,
    );
    return data;
  },

  types: {
    /** Справочник «Типы файлов» — нужен там, где владельца ещё нет
     *  (страница создания заявки). */
    async list(ownerType?: string): Promise<FileTypeRow[]> {
      const { data } = await api.get(`${BASE}types/`, {
        params: ownerType ? { owner_type: ownerType } : undefined,
      });
      return data;
    },
    /** Администратор меняет только размер (ТЗ: «Нет / размеры / нет»). */
    async update(code: string, maxMb: number): Promise<FileTypeRow> {
      const { data } = await api.patch(`${BASE}types/${code}/`, { max_mb: maxMb });
      return data;
    },
  },
};
