import { useMemo } from 'react';

import { usePermissions } from './usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';

/**
 * ⚠️ ОСТАВЛЕН ТОЛЬКО ДЛЯ `src/pages/contracts/*` (зона другого разработчика).
 *
 * Задача 10 блока I «Единая модель прав» перевела все кадровые экраны и
 * общие компоненты на `usePermissions` напрямую. Четыре экрана contracts
 * (`AccountableFundsRequestDetail`, `AdvancePaymentDetail`,
 * `CompletionActDetail`, `ContractPaymentDetail`) читают отсюда `hasPerm`,
 * и править их в этом блоке нельзя — поэтому хук не удалён (буква брифа), а
 * ужат до того, что им нужно: `hasPerm`, `isLoading`, `isError`,
 * `permissions`. Удалить после их перехода на `usePermissions` (roadmap §6).
 * Сторож `src/hooks/__tests__/useHRLevelImporters.test.ts` не пускает сюда
 * новых импортёров: любой другой файл, который импортирует или мокает этот
 * хук, — возврат ко второй модели прав.
 *
 * Второй модели прав здесь и нет: всё считается из `/access/v1/me` через
 * `usePermissions`; `hasPerm` — перевод старого строкового ключа в узел
 * реестра и признаки по таблице ниже, дословно перенесённой из
 * `backend/apps/hr/legacy_roles.py::KEY_TO_NODE`. Уровни (`junior`…`lead`),
 * предикаты `isSenior`/`isLead`/… и `can*` сняты вместе с их потребителями —
 * чтобы хук не соблазнял вернуться к ним.
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
 *
 * Кадровые ключи в таблице живых потребителей на фронте не имеют (задача 10
 * перевела их на `can(node, flag)`), но таблица оставлена целиком: это
 * данные, зеркало бэкенда, и обрезать её до «того, что просят contracts»
 * значило бы оставить `hasPerm`, который на любой ключ отвечает `false`, —
 * такой хук лгал бы формой.
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
 * `hasPerm(старый ключ)` для четырёх экранов contracts — и только для них.
 *
 * `options.enabled` управлял отдельным сетевым запросом старой ручки; права
 * теперь читает общий `usePermissions()` — тот же кэш на 5 минут, что уже
 * стоит почти на каждой защищённой странице. У `usePermissions` нет
 * параметра `enabled` (и это осознанный выбор её задачи: права нужны почти
 * всегда), поэтому здесь он не пробрасывается.
 */
export function useHRLevel(_options: { enabled?: boolean } = {}) {
  const perm = usePermissions();

  return useMemo(() => {
    /**
     * Ключ раскрывается в узел + ВСЕ его признаки (`flags.every`), ровно как
     * `apps/hr/rbac.py::NodeAccess.has` на бэкенде; ключ вне таблицы —
     * `false`, а не исключение: здесь это не ошибка программиста, а штатный
     * ответ для чужих ключей `contracts.*` (см. докстринг таблицы).
     */
    const hasPerm = (key: string): boolean => {
      const mapped = KEY_TO_NODE[key];
      return mapped !== undefined && mapped.flags.every((flag) => perm.can(mapped.node, flag));
    };

    return {
      /**
       * Плоский список старых ключей ушёл вместе с сетевым запросом (задача
       * 8): `hasPerm` считает по узлам, а не по присланной строке. Поле
       * остаётся пустым массивом ради формы, которую читают экраны contracts.
       */
      permissions: [] as string[],
      hasPerm,
      isLoading: perm.isLoading,
      /**
       * «Права не загрузились» ≠ «прав нет» (докстринг `usePermissions`):
       * `hasPerm` при ошибке отвечает `false` (отказ в закрытую), а причина
       * отличима через `isError`.
       */
      isError: perm.isError,
    };
  }, [perm]);
}
