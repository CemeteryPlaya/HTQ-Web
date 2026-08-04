/**
 * useHomeContent — тексты лендинга из БД с откатом на i18n.
 *
 * ПОЧЕМУ С ОТКАТОМ, А НЕ ПРОСТО ИЗ API. Главная — публичное лицо компании и
 * первое, что видит посетитель. Если бэкенд лежит, база пуста или блок ещё не
 * заполнен, страница обязана показать прежний текст из i18n, а не пустую
 * вёрстку. Поэтому любой геттер принимает i18n-ключ и возвращает его перевод,
 * когда в БД ничего нет.
 *
 * Следствие для разработки: секцию можно переводить на БД по одной, ничего не
 * ломая — пока в базе пусто, компонент ведёт себя ровно как раньше.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { fetchPublicHomeSections, type HomeSectionPublic } from '@/api/homeSections';

export interface HomeSectionContent {
  /** Блок скрыт редактором — секцию рисовать не нужно. */
  hidden: boolean;
  /** Текст поля секции: из БД, иначе перевод `fallbackKey`. */
  text: (field: 'tag' | 'title' | 'description', fallbackKey: string) => string;
  /** Элементы блока из БД. Пусто — компонент рисует свой статический список. */
  items: HomeSectionPublic['items'];
}

export function useHomeContent() {
  const { i18n } = useTranslation();
  const lang = i18n.language || 'ru';

  const { data } = useQuery({
    queryKey: ['home-sections', lang],
    queryFn: () => fetchPublicHomeSections(lang),
    // Лендинг открывают часто и надолго; лишние рефетчи ему ни к чему.
    staleTime: 5 * 60 * 1000,
    // Упавший запрос НЕ должен ронять страницу — компоненты сами откатятся
    // на i18n, поэтому ошибку просто проглатываем.
    retry: 1,
  });

  return useMemo(() => {
    const byKey = new Map((data ?? []).map((s) => [s.key, s]));
    /** Ключи, пришедшие с сервера. Нужны, чтобы отличить «блок скрыт
     *  редактором» от «данных ещё нет»: пока список не загрузился, прятать
     *  ничего нельзя, иначе страница мигала бы при каждом открытии. */
    const loaded = data !== undefined;
    return { byKey, loaded };
  }, [data]);
}

/**
 * Контент одной секции. `sectionKey` совпадает с колонкой `key` в БД.
 *
 * `t` передаётся вызывающим, а не берётся здесь: компоненты уже держат свой
 * `useTranslation()`, и второй экземпляр в том же дереве только плодил бы
 * подписки на смену языка.
 */
export function useHomeSection(sectionKey: string): HomeSectionContent {
  const { byKey, loaded } = useHomeContent();
  const { t } = useTranslation();

  return useMemo(() => {
    const section = byKey.get(sectionKey);
    return {
      // Скрываем ТОЛЬКО когда список уже загружен и секции в нём нет:
      // сервер отдаёт лишь видимые. До загрузки показываем — иначе лендинг
      // моргал бы пустотой на каждом заходе.
      hidden: loaded && !section,
      text: (field, fallbackKey) => {
        const value = section?.[field];
        return value && value.trim() ? value : t(fallbackKey);
      },
      items: section?.items ?? [],
    };
  }, [byKey, loaded, sectionKey, t]);
}
