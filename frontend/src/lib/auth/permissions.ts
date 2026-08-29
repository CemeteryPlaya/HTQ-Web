/**
 * Уровни доступа и сравнение по ним.
 *
 * Соответствует §3 спецификации стадии 2 (`docs/plans/2026-08-29-stage2-access-and-roles-spec.md`):
 * уровни строго упорядочены, доступ разрешён, если фактический уровень **не ниже**
 * требуемого. Правило одно и то же на бэкенде и здесь — расхождение в нём означало бы,
 * что интерфейс показывает не то, что реально разрешит сервер.
 */

/** Уровни строго по возрастанию. Порядок в массиве и есть отношение «ниже». */
export const LEVEL_ORDER = ['none', 'read', 'write', 'admin'] as const;

export type AccessLevel = (typeof LEVEL_ORDER)[number];

export type ScopeKind = 'company' | 'department' | 'site';

export interface AccessScope {
  kind: ScopeKind;
  /** `null` при `kind: 'company'`, идентификатор отдела или объекта иначе. */
  id: number | null;
}

export interface PermissionEntry {
  level: AccessLevel;
  scope: AccessScope;
}

/**
 * Карта «модуль → уровень и область».
 *
 * Модули со уровнем `none` в неё **не попадают** — так отдаёт `/access/v1/me`
 * (§4.5). Отсутствие ключа и есть «нет доступа».
 */
export type PermissionMap = Record<string, PermissionEntry>;

const rank = (level: AccessLevel): number => LEVEL_ORDER.indexOf(level);

/** Доступ разрешён, если `effective` не ниже `required`. */
export const meetsLevel = (effective: AccessLevel, required: AccessLevel): boolean =>
  rank(effective) >= rank(required);

/** Уровень модуля в карте; отсутствующий модуль — `none`. */
export const levelFor = (permissions: PermissionMap, module: string): AccessLevel =>
  permissions[module]?.level ?? 'none';

/**
 * Область модуля; `null`, если доступа к модулю нет.
 *
 * Именно `null`, а не «компания»: область без доступа не имеет смысла, а
 * подстановка компании была бы худшим из возможных умолчаний — это самая
 * широкая область из трёх.
 */
export const scopeFor = (permissions: PermissionMap, module: string): AccessScope | null =>
  permissions[module]?.scope ?? null;
