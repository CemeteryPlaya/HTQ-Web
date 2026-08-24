/**
 * Словарь подписей, который переводится в момент чтения.
 *
 * Такие таблицы (`{ active: 'Активный', ... }`) объявляются на уровне модуля,
 * а словарь i18n на импорте ещё не загружен: подставить `t(...)` прямо в
 * значения нельзя — язык застынет тем, что было при загрузке бандла.
 *
 * Поэтому значения хранятся КЛЮЧАМИ, а прокси переводит их на каждом
 * обращении. Места использования при этом не меняются — остаётся обычное
 * чтение `STATUS_LABELS[status]`, — и переключение языка подхватывается без
 * перезагрузки страницы.
 */
import i18next from '@/i18n';

export function translatedMap<K extends string>(keys: Record<K, string>): Record<K, string> {
  return new Proxy(keys, {
    get: (target, prop: string) =>
      prop in target ? i18next.t(target[prop as K]) : undefined,
  }) as Record<K, string>;
}
