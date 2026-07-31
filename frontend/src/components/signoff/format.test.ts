/**
 * Однострочный рендер условия ветки.
 *
 * Логику самого ветвления проверяет бэкенд (`apps/signoff/tests/`); здесь —
 * только то, за что отвечает фронтенд: превратить предикат в фразу, которую
 * человек прочтёт. Ошибка тут не ломает согласование, но делает карточку
 * этапа бессмысленной («admin_country_id одно из 1, 4»), а именно по ней
 * администратор проверяет, что настроил маршрут правильно.
 */

import { describe, expect, it } from 'vitest';

import { conditionText } from './format';
import type { SubjectField } from '@/types/signoff';

const FIELDS: SubjectField[] = [
  {
    key: 'admin_country_id',
    label: 'Страна администратора бюджета',
    type: 'choice',
    options: [
      { value: 1, label: 'Казахстан' },
      { value: 2, label: 'Узбекистан' },
    ],
  },
  { key: 'amount', label: 'Сумма', type: 'number', options: [] },
];

describe('conditionText', () => {
  it('разворачивает значения справочника в подписи', () => {
    const text = conditionText(
      [{ field: 'admin_country_id', op: 'in', value: [1, 2] }],
      FIELDS,
    );
    expect(text).toBe(
      'Страна администратора бюджета одно из Казахстан, Узбекистан',
    );
  });

  it('соединяет предикаты через «и» — они и правда И, не ИЛИ', () => {
    const text = conditionText(
      [
        { field: 'admin_country_id', op: 'eq', value: 1 },
        { field: 'amount', op: 'gt', value: 5000000 },
      ],
      FIELDS,
    );
    expect(text).toBe(
      'Страна администратора бюджета равно Казахстан и Сумма больше 5000000',
    );
  });

  it('без схемы полей показывает сырые ключи, а не падает', () => {
    // Схема есть не везде (список процессов её не тянет). Читаемость хуже,
    // но пустая строка вместо условия была бы хуже вдвойне.
    const text = conditionText(
      [{ field: 'admin_country_id', op: 'eq', value: 1 }],
      [],
    );
    expect(text).toBe('admin_country_id равно 1');
  });

  it('значение вне справочника показывает как есть', () => {
    // Так выглядит маршрут, отставший от справочника: страну удалили, а
    // ветка на неё осталась. Показать id честнее, чем скрыть строку.
    const text = conditionText(
      [{ field: 'admin_country_id', op: 'eq', value: 99 }],
      FIELDS,
    );
    expect(text).toBe('Страна администратора бюджета равно 99');
  });

  it('пустое условие — пустая строка', () => {
    expect(conditionText([], FIELDS)).toBe('');
  });
});
