/**
 * Чтение справочника через react-query — одно на экран справочника и на
 * выборы в документах модуля.
 *
 * - Экран справочника: `useRefdataList('currencies')` — все записи, архивные
 *   с меткой «Архив».
 * - Выбор в НОВОМ документе (валюта, страна, единица, статья):
 *   `useActiveRefdata('currencies')` — `?active=1`, архивных записей в
 *   ответе нет, и предложить их нельзя (ТЗ §18). Старый документ со ссылкой
 *   на архивную запись показывает её из своих данных, а не из этого списка.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import {
  refdataApi, refdataKeys,
  type Article, type ArticleGroup, type Country, type Currency, type ExchangeRate,
  type ListParams, type MrpValue, type RefdataCollection, type Uom, type VatRate,
} from './api';

/** Тип строки каждой коллекции. */
export interface RefdataRows {
  countries: Country;
  currencies: Currency;
  rates: ExchangeRate;
  vat: VatRate;
  mrp: MrpValue;
  uoms: Uom;
  articleGroups: ArticleGroup;
  articles: Article;
}

/** Коллекции с архивом (`is_active`) — только у них есть смысл `?active=1`. */
export type ArchivableCollection = 'countries' | 'currencies' | 'uoms' | 'articleGroups' | 'articles';

// Справочники меняются редко (правит один ФД управляющей компании), а
// выборы в документах открываются часто — пять минут свежести снимают
// лишние запросы, правка на экране справочника сбрасывает кэш сама.
const STALE_MS = 5 * 60 * 1000;

export function useRefdataList<C extends RefdataCollection>(
  name: C,
  params?: ListParams,
): UseQueryResult<RefdataRows[C][]> {
  const list = refdataApi[name].list as (p?: ListParams) => Promise<RefdataRows[C][]>;
  return useQuery({
    queryKey: refdataKeys.list(name, params),
    queryFn: () => list(params),
    staleTime: STALE_MS,
  });
}

/** Для выборов в новых документах — без архивных записей. */
export function useActiveRefdata<C extends ArchivableCollection>(
  name: C,
): UseQueryResult<RefdataRows[C][]> {
  return useRefdataList(name, { active: true });
}
