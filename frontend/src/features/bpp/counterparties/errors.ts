/**
 * Разбор конверта ошибок модуля (D-28 `{detail, code, fields}`) для форм
 * контрагента: `fields` раскладывает отказ по полям, а у дубля E-CTR-02 в
 * `fields[0].existing_id` лежит ключ уже заведённого контрагента — форма
 * показывает ссылку на его карточку.
 */
export interface ErrorField {
  field: string;
  message: string;
  existing_id?: string | null;
}

export function errorFields(error: unknown): ErrorField[] {
  const fields = (error as { response?: { data?: { fields?: unknown } } })
    ?.response?.data?.fields;
  if (!Array.isArray(fields)) return [];
  return fields.filter(
    (item): item is ErrorField =>
      !!item && typeof (item as ErrorField).field === 'string'
      && typeof (item as ErrorField).message === 'string',
  );
}

/** Ключ существующего контрагента из отказа E-CTR-02, если сервер его дал. */
export function duplicateId(error: unknown): string | null {
  const found = errorFields(error).find((item) => typeof item.existing_id === 'string');
  return found?.existing_id ?? null;
}
