/* ─── Файловая подсистема ТЗ §21 (apps.files) ─────────────────────────────
 * Документы любого объекта-владельца (заявка, договор, …): версии,
 * «Заменён», типы и лимиты из справочника «Типы файлов». Правила — на
 * сервере: интерфейс следует флагам папки (`can_modify`, `can_add`,
 * `delete_is_physical`) и у себя статусов владельца не повторяет. */

/** Одна версия документа. Номер версии присваивается один раз и не меняется
 *  (ТЗ: «нельзя изменять; только новая версия»). Готовой ссылки на файл здесь
 *  нет намеренно: скачивание журналируется (ТЗ §25.2), поэтому ссылка
 *  выдаётся на каждое скачивание отдельно — `filesApi.link`. */
export interface FileVersion {
  id: number;
  document_id: string;
  file_type: string;
  version_no: number;
  /** «Заменён»: есть более новая версия (`replaced_by_id`). */
  is_replaced: boolean;
  replaced_by_id: number | null;
  name: string;
  mime: string;
  size: number;
  sha256: string;
  storage_key: string;
  uploaded_by_id: number;
  uploaded_by_name: string;
  uploaded_by_department_id: number | null;
  uploaded_by_department_name: string;
  uploaded_at: string;
  deleted_at: string | null;
}

export interface FileDocument {
  document_id: string;
  file_type: string;
  file_type_name: string;
  /** Удалён после отправки владельца: строка осталась ради истории. */
  deleted_at: string | null;
  current: FileVersion;
  /** От новой версии к старой; `versions[0]` — действующая. */
  versions: FileVersion[];
}

export type FileCardinality = 'multi' | 'single';

/** Тип файла у владельца: справочник + правила владельца + можно ли сейчас. */
export interface FileTypeInfo {
  code: string;
  name: string;
  /** Расширения с точкой: ['.pdf', '.docx', …]. */
  formats: string[];
  max_mb: number;
  cardinality: FileCardinality;
  required: boolean;
  quota_group: string | null;
  can_add: boolean;
  /** Почему нельзя добавить (предел, «уже приложен», статус владельца). */
  reason: string | null;
}

export interface FileQuota {
  group: string;
  max: number;
  used: number;
}

/** Ключ владельца: целый id старых доменов или UUID документа модуля БЗО. */
export type OwnerId = number | string;

/** Папка владельца — ответ `GET files/v1/<owner_type>/<owner_id>/files/`. */
export interface FileFolder {
  owner_type: string;
  /** Строка: сервер отдаёт каноническую строку ключа (`"5"` или UUID). */
  owner_id: string;
  storage_prefix: string;
  can_modify: boolean;
  /** Почему менять нельзя из-за состояния владельца («только в черновике…»)
   *  — подсказка автору. Отказ по правам не объясняется (`null`): читателю
   *  нечего исправлять. */
  modify_reason: string | null;
  delete_is_physical: boolean;
  types: FileTypeInfo[];
  quotas: FileQuota[];
  /** Удалённые (после отправки) идут последними. */
  documents: FileDocument[];
}

/** Строка справочника «Типы файлов» — `GET files/v1/types/`. */
export interface FileTypeRow {
  code: string;
  owner_type: string;
  name: string;
  formats: string[];
  max_mb: number;
  sort_order: number;
  cardinality: FileCardinality | null;
  required: boolean | null;
  quota_group: string | null;
}

export interface FileLink {
  url: string;
  expires_at: string;
}
