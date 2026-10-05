/* Хуки файловой подсистемы ТЗ §21 (apps.files) — папка владельца, справочник
 * типов и правки документов. */
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { filesApi, newIdempotencyKey } from '@/api/files';
import type { OwnerId } from '@/types/files';

/** Ключ папки владельца. Владелец (например, заявка) инвалидирует его после
 *  своих переходов — отправки, возврата: от них зависит `can_modify`.
 *  Ключ владельца — строкой: `5` и `"5"` должны попадать в один кэш. */
export const filesKey = (ownerType: string, ownerId: OwnerId) =>
  ['files', ownerType, String(ownerId)] as const;

/** Общий ключ правок документов одного владельца: по нему страница узнаёт,
 *  что загрузка ещё идёт (`useFilesBusy`). */
const filesMutationKey = (ownerType: string, ownerId: OwnerId) =>
  ['files', 'mutation', ownerType, String(ownerId)] as const;

/* ─── Ключ повтора (ТЗ §23, §26.2) ─────────────────────────────────────────
 * Ключ живёт, пока не ясно, дошёл ли запрос. После обрыва сети или 5xx тот же
 * файл в то же место уходит с ТЕМ ЖЕ ключом: если первый запрос всё-таки был
 * исполнен, сервер вернёт его запись, а не приложит файл второй раз. Ответ по
 * существу (2xx или 4xx) закрывает действие — следующая попытка уже новое
 * действие и получает новый ключ. */
const retryKeys = new Map<string, string>();

function withRetryKey<T>(fingerprint: string, send: (key: string) => Promise<T>): Promise<T> {
  let key = retryKeys.get(fingerprint);
  if (key === undefined) {
    key = newIdempotencyKey();
    retryKeys.set(fingerprint, key);
  }
  return send(key).then(
    (result) => {
      retryKeys.delete(fingerprint);
      return result;
    },
    (error: unknown) => {
      const status = (error as { response?: { status?: number } } | null)?.response?.status;
      if (status !== undefined && status < 500) retryKeys.delete(fingerprint);
      throw error;
    },
  );
}

const fileFingerprint = (file: File) => `${file.name}|${file.size}|${file.lastModified}`;

/** Новый документ (версия 1). Функция, а не только хук: страница создания
 *  заявки грузит файл в только что созданный черновик, и повтор той же
 *  загрузки уже в панели черновика должен уйти с тем же ключом. */
export function uploadDocument(ownerType: string, ownerId: OwnerId, file: File, fileType: string) {
  return withRetryKey(
    `${ownerType}|${ownerId}|new|${fileType}|${fileFingerprint(file)}`,
    (key) => filesApi.upload(ownerType, ownerId, file, fileType, key),
  );
}

/** Новая версия поверх `baseFileId`. `baseFileId` в отпечаток НЕ входит
 *  намеренно: если первый запрос дошёл, папка перечитается, и повтор уйдёт
 *  поверх уже новой действующей версии — с новым ключом он приложил бы тот же
 *  файл ещё раз, а с прежним сервер узнает повтор и вернёт первую запись. */
export function uploadDocumentVersion(
  ownerType: string, ownerId: OwnerId, documentId: string, file: File, baseFileId: number,
) {
  return withRetryKey(
    `${ownerType}|${ownerId}|${documentId}|${fileFingerprint(file)}`,
    (key) => filesApi.uploadVersion(ownerType, ownerId, documentId, file, baseFileId, key),
  );
}

/** Папка владельца. Ссылок на файлы в ней нет (их выдаёт `filesApi.link` на
 *  каждое скачивание), так что устаревать в ней нечему, кроме чужих правок:
 *  их подхватывает перечитка при возврате на вкладку, а переходы владельца
 *  (отправка, возврат) инвалидируют папку сами. */
export function useFileFolder(ownerType: string, ownerId: OwnerId | null | undefined) {
  return useQuery({
    queryKey: ownerId != null ? filesKey(ownerType, ownerId) : ['files', ownerType, 'none'],
    queryFn: () => filesApi.list(ownerType, ownerId as OwnerId),
    enabled: ownerId != null,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** Справочник «Типы файлов» владельца — там, где самого владельца ещё нет. */
export function useFileTypes(ownerType: string) {
  return useQuery({
    queryKey: ['files', 'types', ownerType],
    queryFn: () => filesApi.types.list(ownerType),
    staleTime: 10 * 60_000,
  });
}

export function useFilesBusy(ownerType: string, ownerId: OwnerId): boolean {
  return useIsMutating({ mutationKey: filesMutationKey(ownerType, ownerId) }) > 0;
}

function useInvalidateFolder(ownerType: string, ownerId: OwnerId) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: filesKey(ownerType, ownerId) });
}

export function useUploadFile(ownerType: string, ownerId: OwnerId) {
  const invalidate = useInvalidateFolder(ownerType, ownerId);
  return useMutation({
    mutationKey: filesMutationKey(ownerType, ownerId),
    mutationFn: ({ file, fileType }: { file: File; fileType: string }) =>
      uploadDocument(ownerType, ownerId, file, fileType),
    onSettled: invalidate,
  });
}

export function useUploadFileVersion(ownerType: string, ownerId: OwnerId) {
  const invalidate = useInvalidateFolder(ownerType, ownerId);
  return useMutation({
    mutationKey: filesMutationKey(ownerType, ownerId),
    mutationFn: ({ documentId, file, baseFileId }:
      { documentId: string; file: File; baseFileId: number }) =>
      uploadDocumentVersion(ownerType, ownerId, documentId, file, baseFileId),
    // И после отказа: на 409 E-CON-01 папку надо перечитать — в ней уже
    // чужая версия, поверх которой и стоит грузить.
    onSettled: invalidate,
  });
}

export function useRemoveFile(ownerType: string, ownerId: OwnerId) {
  const invalidate = useInvalidateFolder(ownerType, ownerId);
  return useMutation({
    mutationKey: filesMutationKey(ownerType, ownerId),
    mutationFn: (documentId: string) => filesApi.remove(ownerType, ownerId, documentId),
    onSettled: invalidate,
  });
}
