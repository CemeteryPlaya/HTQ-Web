/**
 * Типы домена доступа (`/api/access/v1`).
 *
 * Соответствуют замороженному контракту §4 спецификации стадии 2
 * (`docs/plans/2026-08-29-stage2-access-and-roles-spec.md`). Контракт — стык
 * между двумя исполнителями, поэтому расхождение здесь чинится правкой
 * документа и согласованием, а не подгонкой типов под то, что пришло.
 */

import type {
  AccessLevel,
  DepthFlag,
  DepthPreset,
  PermissionMap,
  ScopeKind,
} from '@/lib/auth/permissions';

/** §4.1. Каталог ролей глобален: одна роль действует во всех компаниях. */
export interface Role {
  id: number;
  code: string;
  title: string;
  /** Служебная роль — удалять нельзя (409). */
  is_system: boolean;
}

export interface RoleInput {
  code: string;
  title: string;
}

/** §4.2. Глубина роли на одном узле реестра функций. */
export interface RolePermission {
  /** Путь узла: `hr`, `hr.employees`, `hr.employees.salary`. */
  node: string;
  flags: DepthFlag[];
  /** Название пресета, если набор совпал с известным; иначе `null`. */
  preset: DepthPreset | null;
}

/** Что отправляем при сохранении: либо пресет, либо флаги — но не оба. */
export type RolePermissionInput =
  | { node: string; preset: DepthPreset }
  | { node: string; flags: DepthFlag[] };

/** Узел реестра функций: модуль → функция → поле. */
export interface AccessFunctionNode {
  path: string;
  title: string;
  kind: 'module' | 'function' | 'field';
  /**
   * Признаки глубины, ОСМЫСЛЕННЫЕ для этого узла.
   *
   * Не всякая функция описывается CRUD'ом: «войти в конференцию» и «написать
   * сообщение» — действия, у них есть только «доступно» и «нет доступа».
   * Предлагать для них «удалять» значит предлагать задать бессмыслицу, о
   * которой потом никто не скажет, что она означает.
   */
  flags: DepthFlag[];
  /**
   * Уровни, которые осмысленно предлагать для узла. Считает их сервер:
   * у модуля-инструмента их три («нет доступа», «пользователь»,
   * «администратор»), у модуля-картотеки шесть, у функции — по применимым
   * признакам. Фронт их не выводит заново — иначе два ответа на один вопрос.
   */
  presets: DepthPreset[];
  children: AccessFunctionNode[];
}

/** Узел-страницы: плоский, только «видно» и «не видно». */
export interface AccessPageNode {
  path: string;
  title: string;
  kind: 'page';
  flags: DepthFlag[];
  presets: DepthPreset[];
  /** Путь маршрута, как он записан в routeDefinitions. */
  route: string;
  children?: never;
}

export interface AccessFunctionsResponse {
  tree: AccessFunctionNode[];
  pages: AccessPageNode[];
  flags: { key: DepthFlag; title: string }[];
  presets: { key: DepthPreset; title: string; flags: DepthFlag[] }[];
}

/** §4.3. Роль в наборе должности — штатный путь выдачи прав. */
export interface PositionRole {
  role_id: number;
  code: string;
  title: string;
}

/** §4.4. Личное назначение — исключительный путь. */
export interface RoleAssignment {
  role_id: number;
  scope_kind: ScopeKind;
  /** `null` обязателен при `scope_kind: 'company'`. */
  scope_id: number | null;
}

/** §4.5. Права текущего пользователя в компании запроса. */
export interface AccessMe {
  /** `null` вне контекста компании — переходный режим подпроекта 1, не ошибка. */
  company: string | null;
  permissions: PermissionMap;
  /**
   * Глубина по узлам реестра — полная картина прав.
   *
   * Уровни модулей выше (`permissions`) — её проекция, оставленная ради
   * маршрутов и гейта. Скрывать отдельные поля и кнопки нужно по этой карте:
   * уровень модуля о поле ничего не знает.
   */
  depth: Record<string, DepthFlag[]>;
  /**
   * Страницы, закрытые роли ЯВНЫМ запретом.
   *
   * Слой выше остальных: не видя страницы, человек не сделает на ней ничего,
   * какие бы глубины ему ни выдали. При этом это вето, а не разрешение —
   * страница без запрета работает по обычным правилам, иначе всякая роль без
   * полного перечня страниц оказалась бы бесполезной.
   */
  hidden_pages: string[];
  /**
   * Компании ниже по дереву владения, над сотрудниками которых пользователь
   * начальник по внешней иерархии (§1.4). Стадия его отдаёт, но выборки по
   * нему не режет — только отображение (§7).
   */
  subordinate_companies: string[];
}
