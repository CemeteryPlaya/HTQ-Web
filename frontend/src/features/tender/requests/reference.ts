/**
 * Справочники экранов заявки на тендер: проекты и статьи бюджета — ручками
 * заявки в роли заявки (ПМ видит только проекты-участия, статьи — группы
 * роли); единицы измерения и названия статей — тем же клиентом
 * справочников, что форма заявки БЗО (`features/bpp/refdata/api`), и под
 * теми же ключами react-query: кэш общий. Проект в карточке и реестре
 * приходит готовым (`project`, `project_code`) — отдельно его не ищем.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { refdataApi, refdataKeys } from '@/features/bpp/refdata/api';

import { tenderRequestKeys, tenderRequestsApi, type InitiatorRole } from './api';

const LONG = 10 * 60 * 1000;

/** Поиск проекта для формы: сервер отдаёт не больше 20 по `q`. */
export function useRequestProjects(q: string, role: InitiatorRole | '', enabled = true) {
  return useQuery({
    queryKey: tenderRequestKeys.projects(q, role),
    queryFn: () => tenderRequestsApi.projects(q, role),
    enabled,
    staleTime: 60 * 1000,
  });
}

export function useRequestArticles(projectId: string, role: InitiatorRole | '', enabled = true) {
  return useQuery({
    queryKey: tenderRequestKeys.articles(projectId, role),
    queryFn: () => tenderRequestsApi.articles(projectId, role as InitiatorRole),
    enabled: enabled && Boolean(projectId) && Boolean(role),
  });
}

/** Единицы измерения: `active` — только действующие (выбор в форме). */
export function useUoms(active: boolean) {
  return useQuery({
    queryKey: refdataKeys.list('uoms', { active }),
    queryFn: () => refdataApi.uoms.list({ active }),
    staleTime: LONG,
  });
}

/** `id → короткое имя` единицы, включая архивные (карточка старой заявки). */
export function useUomNames(): Map<string, string> {
  const { data } = useUoms(false);
  return useMemo(() => new Map((data ?? []).map((uom) => [uom.id, uom.short_name])), [data]);
}

/** `id → «Код — Название»` статьи, включая архивные. */
export function useArticleNames(): Map<string, string> {
  const { data } = useQuery({
    queryKey: refdataKeys.list('articles', { active: false }),
    queryFn: () => refdataApi.articles.list({ active: false }),
    staleTime: LONG,
  });
  return useMemo(
    () => new Map((data ?? []).map((article) => [article.id, `${article.code} — ${article.name}`])),
    [data],
  );
}
