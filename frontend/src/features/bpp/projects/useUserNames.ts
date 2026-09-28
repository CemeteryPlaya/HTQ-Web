/**
 * Имена пользователей по `user_id` для руководителя и участников проекта.
 *
 * Ручки «имя по id» на платформе нет, «Проект» хранит только `user_id`, —
 * имена берутся из кадрового списка сотрудников (тот же запрос и ключ кеша,
 * что у `EmployeePicker`, поэтому второго запроса нет). Нет права на кадры
 * или запрос упал — «Пользователь №id»: это штатная деградация подписи, а не
 * подмена данных.
 */
import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { fetchEmployees } from '@/api/hr';

export function useUserNames(): (userId: number | null | undefined) => string {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['hr', 'employees', 'picker'],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const names = useMemo(() => {
    const map = new Map<number, string>();
    for (const employee of data ?? []) {
      const id = employee.user_id ?? employee.user;
      if (id != null && employee.full_name) map.set(id, employee.full_name);
    }
    return map;
  }, [data]);

  return useCallback((userId) => {
    if (userId === null || userId === undefined) return '—';
    return names.get(userId) ?? t('bpp.projects.user', 'Пользователь №{{id}}', { id: userId });
  }, [names, t]);
}
