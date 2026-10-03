/**
 * Имена пользователей по `user_id` для руководителя и участников проекта.
 *
 * Берутся из учёток `users` через `GET project/v1/user-names?ids=…`, а не из
 * кадрового списка сотрудников: у ТД, ОД и ПМ кадровых прав нет, и `hr/v1/
 * employees` отвечал им 403 («Пользователь №13» вместо ФИО). Сервер отдаёт
 * имена только руководителей и участников проектов. Нет имени (запрос упал,
 * id чужой) — «Пользователь №id»: штатная деградация подписи, а не подмена.
 */
import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export function useUserNames(
  userIds: ReadonlyArray<number | null | undefined>,
): (userId: number | null | undefined) => string {
  const { t } = useTranslation();
  const ids = useMemo(
    () => [...new Set(userIds.filter((id): id is number => typeof id === 'number'))].sort((a, b) => a - b),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [userIds.join(',')],
  );
  const { data } = useQuery({
    queryKey: ['project', 'user-names', ids.join(',')],
    queryFn: () =>
      api
        .get<Record<string, string>>(apiPath('project', 'user-names'), { params: { ids: ids.join(',') } })
        .then((r) => r.data),
    enabled: ids.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  return useCallback((userId) => {
    if (userId === null || userId === undefined) return '—';
    return data?.[String(userId)] ?? t('bpp.projects.user', 'Пользователь №{{id}}', { id: userId });
  }, [data, t]);
}
