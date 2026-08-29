/**
 * Фикстура ответа `/access/v1/me` — точный пример из §4.5 контракта.
 *
 * Нужна, пока исполнитель A не довёл ручку (задача A6): по спецификации фронт
 * до этого момента разрабатывается против неё.
 *
 * ⚠️ **Фикстура НЕ подставляется при ошибке запроса.** Молчаливая подмена
 * данных о правах — ровно тот случай, против которого в проекте написан
 * `src/lib/fallback.ts`, и на поверхности доступа она опаснее, чем где-либо
 * ещё: пользователь увидел бы разделы, которых сервер ему не даст, а разбор
 * начался бы с «почему API отвечает 403». Включается только явным флагом
 * `VITE_ACCESS_FIXTURE=1`, то есть осознанным решением разработчика.
 */

import type { AccessMe } from '@/types/access';

export const ACCESS_ME_FIXTURE: AccessMe = {
  company: 'hi-tech-qazaqstan',
  permissions: {
    hr: { level: 'admin', scope: { kind: 'company', id: null } },
    tasks: { level: 'write', scope: { kind: 'department', id: 3 } },
    contracts: { level: 'read', scope: { kind: 'company', id: null } },
  },
  subordinate_companies: ['kurly-kg', 'htq-uz'],
};

/** Ответ вне контекста компании — тоже из §4.5, и это не ошибка. */
export const ACCESS_ME_NO_COMPANY: AccessMe = {
  company: null,
  permissions: {},
  subordinate_companies: [],
};

/** Включён ли режим фикстуры. Только явный флаг, никакой автоподстановки. */
export const usesAccessFixture = (): boolean =>
  import.meta.env.VITE_ACCESS_FIXTURE === '1';
