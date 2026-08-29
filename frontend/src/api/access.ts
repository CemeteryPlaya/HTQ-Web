/**
 * api/access.ts
 * Клиент домена доступа (`/api/access/v1`) по замороженному контракту §4
 * спецификации стадии 2.
 *
 * Пути без завершающего слэша — бэкенд регистрирует оба написания
 * (`APPEND_SLASH=False`); придерживаемся одного стиля, как в api/signoff.ts.
 *
 * Слой транспортный: разбора и ветвлений здесь нет намеренно. Ответ `/me`
 * уже приходит в той же форме, в какой его потребляет `usePermissions`
 * (§4.5), поэтому нормализация была бы лишним местом для расхождения.
 */

import api from './client';
import { apiPath } from './endpoints';
import { ACCESS_ME_FIXTURE, usesAccessFixture } from './access.fixture';
import type {
  AccessMe,
  PositionRole,
  Role,
  RoleAssignment,
  RoleInput,
  RolePermission,
} from '@/types/access';

const path = (suffix: string) => apiPath('access', suffix);

export const accessApi = {
  // ─── §4.1 Каталог ролей (глобальный) ──────────────────────────────────
  /** Плоский список: у роли нет ни веса, ни родителя — иерархию несёт должность. */
  listRoles: () => api.get<Role[]>(path('roles')),
  createRole: (body: RoleInput) => api.post<Role>(path('roles'), body),
  renameRole: (id: number, title: string) =>
    api.patch<Role>(path(`roles/${id}`), { title }),
  /** 409 `in_use`, если роль назначена хоть одной должности или пользователю. */
  deleteRole: (id: number) => api.delete<void>(path(`roles/${id}`)),

  // ─── §4.2 Права роли ──────────────────────────────────────────────────
  getRolePermissions: (id: number) =>
    api.get<RolePermission[]>(path(`roles/${id}/permissions`)),
  /** Набор заменяется целиком: отсутствующий в списке модуль равен `none`. */
  putRolePermissions: (id: number, permissions: RolePermission[]) =>
    api.put<RolePermission[]>(path(`roles/${id}/permissions`), permissions),

  // ─── §4.3 Роли должности — штатный путь ───────────────────────────────
  getPositionRoles: (positionId: number) =>
    api.get<PositionRole[]>(path(`positions/${positionId}/roles`)),
  putPositionRoles: (positionId: number, roleIds: number[]) =>
    api.put<PositionRole[]>(path(`positions/${positionId}/roles`), {
      role_ids: roleIds,
    }),

  // ─── §4.4 Личные назначения — исключительный путь ──────────────────────
  getAssignments: (userId: number) =>
    api.get<RoleAssignment[]>(path(`assignments/${userId}`)),
  putAssignments: (userId: number, assignments: RoleAssignment[]) =>
    api.put<RoleAssignment[]>(path(`assignments/${userId}`), assignments),

  // ─── §4.5 Права текущего пользователя ─────────────────────────────────
  /**
   * Режим фикстуры — явный и только по флагу `VITE_ACCESS_FIXTURE=1`.
   * Это не fallback: он не срабатывает от ошибки запроса, поэтому реальная
   * поломка бэкенда остаётся видимой поломкой.
   */
  getMe: async (): Promise<AccessMe> => {
    if (usesAccessFixture()) return ACCESS_ME_FIXTURE;
    const res = await api.get<AccessMe>(path('me'));
    return res.data;
  },
};

export default accessApi;
