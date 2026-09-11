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


// ── Глубина: признаки и пресеты ─────────────────────────────────────────────

/**
 * Признаки глубины. Независимы: «удаляет» не подразумевает «редактирует» —
 * роль, которая чистит устаревшие записи, ничего не переписывая, осмысленна.
 * Порядок задаёт порядок колонок в матрице прав.
 */
export const DEPTH_FLAGS = ['view', 'create', 'edit', 'delete'] as const;

export type DepthFlag = (typeof DEPTH_FLAGS)[number];

/** Шесть названных уровней из постановки — готовые наборы флагов. */
export const DEPTH_PRESETS = ['none', 'view', 'create', 'edit', 'delete', 'full'] as const;

export type DepthPreset = (typeof DEPTH_PRESETS)[number];

/** Карта «узел → флаги» из ответа `/access/v1/me`. */
export type DepthMap = Record<string, DepthFlag[]>;

/** Путь предков узла от ближайшего к корню: `a.b.c` → `[a.b, a]`. */
export const nodeAncestors = (path: string): string[] => {
  const parts = path.split('.');
  return parts.slice(0, -1).map((_, i) => parts.slice(0, parts.length - 1 - i).join('.'));
};

/**
 * Действующая глубина узла с учётом наследования.
 *
 * Не заданный узел берёт глубину ближайшего предка; ПУСТОЙ набор у предка —
 * это запрет, а не «ищи выше». Правило то же, что на сервере
 * (`apps/access/services/resolve.py::_nearest`) — расхождение означало бы, что
 * интерфейс показывает не то, что разрешит сервер.
 */
export const depthFor = (map: DepthMap, node: string): DepthFlag[] => {
  for (const candidate of [node, ...nodeAncestors(node)]) {
    const flags = map[candidate];
    if (flags !== undefined) return flags;
  }
  return [];
};

/** Есть ли у пользователя конкретный признак на узле. */
export const hasDepth = (map: DepthMap, node: string, flag: DepthFlag): boolean =>
  depthFor(map, node).includes(flag);
