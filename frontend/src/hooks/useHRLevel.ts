import { useMemo } from 'react';

import { usePermissions } from './usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';

export type HRLevel = 'junior' | 'middle' | 'senior' | 'lead' | null;

/**
 * Кадровый уровень и предикаты «может ли» — теперь СЧИТАЮТСЯ из общих прав
 * (`usePermissions`, `/access/v1/me`), а не из старой ручки
 * `hr/v1/employees/hr-level/` (задача 8 блока I). Сама ручка и параллельная
 * кадровая модель прав снимаются отдельно, задачей 9 — этот хук лишь
 * перестаёт быть их потребителем на фронте.
 *
 * Публичный интерфейс НЕ меняется: 35 файлов, которые зовут `useHRLevel`,
 * продолжают работать без правки. Единственное дополнение — `isError`,
 * которого раньше не было вовсе (см. докстринг у поля ниже).
 */

// ── Узлы кадрового домена (backend/apps/hr/access_functions.py) ────────────
//
// Строками, а не импортом: TS не может импортировать Python-модуль, поэтому
// узлы и признаки — буквальный перенос данных через границу языков, тем же
// приёмом, что использует сам backend/apps/hr/legacy_roles.py (см. его
// докстринг о том, почему литералы, а не импорт apps.access.depth).
const NODE_EMPLOYEES = 'hr.employees';
const NODE_EMPLOYEES_IDENTITY = 'hr.employees.identity';
const NODE_EMPLOYEES_SALARY = 'hr.employees.salary';
const NODE_EMPLOYEES_PASSPORT = 'hr.employees.passport';
const NODE_EMPLOYEES_FAMILY = 'hr.employees.family';
// Перевод — отдельный под-узел (фикс-раунд 1 задачи 9 блока I): раньше ключ
// вёл на hr.employees с EDIT и совпадал с hr.employees.edit, то есть middle
// «переводил» по той же кнопке, что и правил, — сервер отдавал бы 403.
const NODE_EMPLOYEES_TRANSFER = 'hr.employees.transfer';
const NODE_DEPARTMENTS = 'hr.departments';
const NODE_POSITIONS = 'hr.positions';
const NODE_ORG = 'hr.org';
const NODE_DOCUMENTS = 'hr.documents';
const NODE_REPORTS = 'hr.reports';
const NODE_ACCOUNTS = 'hr.accounts';
const NODE_IDENTITY_REQUESTS = 'hr.identity_requests';
const NODE_CALENDAR = 'hr.production_calendar';
const NODE_STAFFING = 'hr.staffing';

// Наборы признаков — дословно backend/apps/hr/legacy_roles.py (VIEW/EDIT/
// CREATE/FULL/DELETE/PURGE). `apps.access.depth` намеренно не включает EDIT
// в DELETE («удалить» и «переписать» — разные полномочия), отсюда PURGE.
const VIEW: DepthFlag[] = ['view'];
const EDIT: DepthFlag[] = ['view', 'edit'];
const CREATE: DepthFlag[] = ['view', 'create'];
const FULL: DepthFlag[] = ['view', 'create', 'edit'];
const DELETE: DepthFlag[] = ['view', 'create', 'edit', 'delete'];
const PURGE: DepthFlag[] = ['view', 'delete'];

interface NodeFlags {
  node: string;
  flags: DepthFlag[];
}

/**
 * Старый ключ прав (`backend/apps/hr/permissions.py`) → узел + признаки,
 * которые он подразумевал. Перенесено ДОСЛОВНО из
 * `backend/apps/hr/legacy_roles.py::KEY_TO_NODE` — второе соответствие
 * здесь не изобретается.
 *
 * Ключ `contracts.advance_payment.record_payment` (см.
 * `backend/apps/contracts/services/advance_payment_service.py`) сюда
 * СОЗНАТЕЛЬНО не входит: узел им не принадлежит `apps.hr`, а придумывать
 * соответствие для чужого узла — то самое, что запрещено и backend-у
 * (`legacy_roles.py::DEFERRED_KEYS`, тот же повод). Два похожих на вид ключа
 * из `apps.contracts` — `contracts.accountable_funds_request.mark_paid` и
 * `contracts.contract_payment.record_payment` — здесь тоже отсутствуют, но
 * это НЕ тот же случай: они не входят в `apps/hr/permissions.py::ALL_KEYS`
 * вовсе (проверено чтением файла), а `resolve_hr_access` в старом коде
 * (`apps/hr/access.py`) пересекал `Position.permissions` именно с
 * `ALL_KEYS` (`perms = frozenset(...) & ALL_KEYS`) — то есть эти два ключа
 * физически не могли попасть в старый ответ `permissions[]`, и `hasPerm`
 * для них был `false` ДО этой задачи тоже. Регрессия — ровно один ключ,
 * `contracts.advance_payment.record_payment`: `hasPerm` для него теперь
 * всегда `false` (раньше давал `true` тому, у чьей должности он был
 * проставлен в `Position.permissions`, минуя admin-роль в `contracts`),
 * пока `apps.contracts` не заведёт для него собственный узел реестра. См.
 * отчёт задачи 8, раздел «Fix round 1».
 */
const KEY_TO_NODE: Record<string, NodeFlags> = {
  'hr.employees.view': { node: NODE_EMPLOYEES, flags: VIEW },
  'hr.employees.view.all': { node: NODE_EMPLOYEES, flags: VIEW },
  'hr.employees.create': { node: NODE_EMPLOYEES, flags: CREATE },
  'hr.employees.edit': { node: NODE_EMPLOYEES, flags: EDIT },
  'hr.employees.delete': { node: NODE_EMPLOYEES, flags: PURGE },
  'hr.employees.transfer': { node: NODE_EMPLOYEES_TRANSFER, flags: EDIT },

  'hr.departments.view': { node: NODE_DEPARTMENTS, flags: VIEW },
  'hr.departments.edit': { node: NODE_DEPARTMENTS, flags: EDIT },
  'hr.positions.view': { node: NODE_POSITIONS, flags: VIEW },
  'hr.positions.edit': { node: NODE_POSITIONS, flags: EDIT },
  'hr.org.edit': { node: NODE_ORG, flags: DELETE },

  'hr.documents.view': { node: NODE_DOCUMENTS, flags: VIEW },
  'hr.documents.manage': { node: NODE_DOCUMENTS, flags: FULL },

  'hr.reports.view': { node: NODE_REPORTS, flags: VIEW },

  'hr.users.list': { node: NODE_ACCOUNTS, flags: VIEW },
  'hr.users.manage': { node: NODE_ACCOUNTS, flags: FULL },

  'hr.identity.view': { node: NODE_IDENTITY_REQUESTS, flags: VIEW },
  'hr.identity.manage': { node: NODE_IDENTITY_REQUESTS, flags: EDIT },
  'hr.identity.force': { node: NODE_EMPLOYEES_IDENTITY, flags: EDIT },

  'hr.card.financial.view': { node: NODE_EMPLOYEES_SALARY, flags: VIEW },
  'hr.card.financial.edit': { node: NODE_EMPLOYEES_SALARY, flags: EDIT },
  'hr.card.personal.view': { node: NODE_EMPLOYEES_PASSPORT, flags: VIEW },
  'hr.card.personal.edit': { node: NODE_EMPLOYEES_PASSPORT, flags: EDIT },
  'hr.card.groups.view': { node: NODE_EMPLOYEES_FAMILY, flags: VIEW },
  'hr.card.groups.edit': { node: NODE_EMPLOYEES_FAMILY, flags: EDIT },

  'hr.calendar.view': { node: NODE_CALENDAR, flags: VIEW },
  'hr.calendar.manage': { node: NODE_CALENDAR, flags: DELETE },

  'hr.staffing.view': { node: NODE_STAFFING, flags: VIEW },
  'hr.staffing.manage': { node: NODE_STAFFING, flags: DELETE },
};

/**
 * Кадровый уровень и предикаты текущего пользователя.
 *
 * `options.enabled` управлял отдельным сетевым запросом старой ручки; права
 * теперь читает общий `usePermissions()` — тот же кэш на 5 минут, что уже
 * стоит почти на каждой защищённой странице. У `usePermissions` нет
 * параметра `enabled` (и это осознанный выбор её задачи: права нужны почти
 * всегда), поэтому здесь он не пробрасывается. Поведение это не меняет:
 * `Header.tsx` — единственный вызывающий, кому вообще есть смысл гасить
 * запрос до логина, — уже сегодня зовёт `usePermissions()` безусловно на
 * той же строке, что и `useHRLevel({ enabled: isLoggedIn })`, так что лишний
 * (безвредный, см. отчёт задачи 8) запрос при разлогиненном пользователе
 * появился не с этой правкой.
 */
export function useHRLevel(_options: { enabled?: boolean } = {}) {
  const perm = usePermissions();

  return useMemo(() => {
    // Соответствие уровней — ДОСЛОВНО backend/apps/access/depth.py::
    // legacy_level (delete → admin, create|edit → write, view → read),
    // уже посчитанное бэкендом в perm.level('hr'); здесь оно только
    // переименовано в кадровые названия (backend/apps/hr/legacy_roles.py::
    // ROLE_CODES — hr-junior/middle/senior/lead).
    //
    // middle и senior делят один и тот же уровень ('write') — разница
    // между ними в старой модели была ОБЛАСТЬЮ выдачи, не признаком
    // (см. "Решение 1" в legacy_roles.py у EMPLOYEES_VIEW_ALL): задача 2
    // заводит hr-junior/hr-middle с областью DEPARTMENT, hr-senior/hr-lead —
    // с COMPANY, и тот же расчёт делает бэкенд в
    // apps/access/services/resolve.py::permissions_for. Без этого 'senior'
    // был бы недостижим, а `isSenior` (гейтит ~9 экранов HR) — эквивалентен
    // одному только `isLead`.
    const hrScope = perm.scope('hr');
    const scopeKind = hrScope?.kind ?? null;
    const accessLevel = perm.level('hr');

    let level: HRLevel = null;
    if (accessLevel === 'admin') {
      level = 'lead';
    } else if (accessLevel === 'write') {
      level = scopeKind === 'company' ? 'senior' : 'middle';
    } else if (accessLevel === 'read') {
      level = 'junior';
    }

    /**
     * `can_*` считаются по КОНКРЕТНОМУ узлу через `perm.can`, а не выводятся
     * из агрегированного `level` выше: уровень — проекция по всему
     * поддереву `hr`, и роль может держать `delete` на другом узле
     * (скажем, `hr.documents`), не имея его на `hr.employees` — вывод из
     * уровня в этом случае соврал бы, что сотрудника можно удалить.
     */
    const canDo = (node: string, flags: DepthFlag[]): boolean =>
      flags.every((flag) => perm.can(node, flag));

    const hasPerm = (key: string): boolean => {
      const mapped = KEY_TO_NODE[key];
      return mapped !== undefined && canDo(mapped.node, mapped.flags);
    };

    const scopeDepartmentId = hrScope?.kind === 'department' ? hrScope.id : null;

    return {
      level,
      scopeDepartmentId,
      hasHrAccess: level !== null,
      isLead: level === 'lead',
      isSenior: level === 'senior' || level === 'lead',
      isSeniorOrAbove: level === 'senior' || level === 'lead',
      isMiddle: level === 'middle',
      isMiddleOrAbove: level === 'middle' || level === 'senior' || level === 'lead',
      isJunior: level === 'junior',
      canReadAll: canDo(NODE_EMPLOYEES, VIEW),
      canWriteBasic: canDo(NODE_EMPLOYEES, EDIT),
      canCreateEmployee: canDo(NODE_EMPLOYEES, CREATE),
      canTransferEmployee: canDo(NODE_EMPLOYEES_TRANSFER, EDIT),
      canDeleteEmployee: canDo(NODE_EMPLOYEES, PURGE),
      canListUserOptions: canDo(NODE_ACCOUNTS, VIEW),
      canManageUserOptions: canDo(NODE_ACCOUNTS, FULL),
      /**
       * Плоский список старых ключей ушёл вместе с сетевым запросом: его
       * единственный потребитель во всём фронте — `hasPerm` ниже (проверено
       * grep'ом по `useHRLevel()` — ни один из 35 файлов не читает
       * `.permissions` напрямую), а он теперь считает по узлам, а не по
       * присланной строке. Поле остаётся пустым массивом ради формы, а не
       * убирается — правило задачи 8: интерфейс не меняется, даже когда
       * содержимое поля больше неоткуда взять.
       */
      permissions: [] as string[],
      hasPerm,
      isLoading: perm.isLoading,
      /**
       * «Права не загрузились» ≠ «прав нет» (docstring `usePermissions`).
       * Раньше это было неразличимо: неудачный запрос отдавал `level: null`
       * — то же самое, что у штатного «доступа нет». `level` здесь ПО-
       * ПРЕЖНЕМУ `null` при ошибке (отказ в закрытую — тот же принцип, что
       * уже реализован в `usePermissions`: пустая карта прав на ошибке, а
       * не «пока не знаем, разрешим»), но теперь причина отличима через
       * `isError` — раньше эта информация не терялась при передаче, её
       * попросту неоткуда было взять.
       */
      isError: perm.isError,
    };
  }, [perm]);
}
