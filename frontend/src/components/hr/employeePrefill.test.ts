import { describe, expect, it } from 'vitest';

import type { PrefillFieldDiff, PrefillPreview } from '@/types/hr';
import {
  defaultSelection,
  isSelectable,
  matchQueryIsAnswerable,
  pickValues,
} from '@/components/hr/employeePrefill';

/**
 * Здесь проверяется обещание задачи целиком: заполненное поле не
 * перезаписывается молча. Всё остальное в диалоге — оформление вокруг этих
 * трёх функций.
 */

const row = (over: Partial<PrefillFieldDiff>): PrefillFieldDiff => ({
  field: 'phone',
  current: null,
  incoming: '+7 700 000 00 00',
  current_display: '',
  incoming_display: '+7 700 000 00 00',
  state: 'fill',
  ...over,
});

describe('defaultSelection', () => {
  it('отмечает пустые поля — заполнить пустое ничего не разрушает', () => {
    const fields = [
      row({ field: 'phone', state: 'fill' }),
      row({ field: 'middle_name', state: 'fill' }),
    ];
    expect(defaultSelection(fields)).toEqual(['phone', 'middle_name']);
  });

  it('НЕ отмечает расхождения — их разрешает человек, а не умолчание', () => {
    const fields = [
      row({ field: 'phone', state: 'conflict', current: '+7 700 111 11 11' }),
      row({ field: 'email', state: 'fill' }),
    ];
    expect(defaultSelection(fields)).toEqual(['email']);
  });

  it('не отмечает совпадающие — переносить там нечего', () => {
    expect(defaultSelection([row({ field: 'first_name', state: 'same' })])).toEqual([]);
  });
});

describe('isSelectable', () => {
  it('совпадающую строку выбрать нельзя', () => {
    expect(isSelectable(row({ state: 'same' }))).toBe(false);
  });

  it('пустую и конфликтную — можно', () => {
    expect(isSelectable(row({ state: 'fill' }))).toBe(true);
    expect(isSelectable(row({ state: 'conflict' }))).toBe(true);
  });
});

describe('pickValues', () => {
  const preview = (fields: PrefillFieldDiff[]): PrefillPreview => ({
    source: { type: 'user', id: 1, title: 'Иванов Иван', subtitle: 'i@htq.test' },
    values: {},
    fields,
    fillable: fields.filter((f) => f.state === 'fill').length,
    conflicts: fields.filter((f) => f.state === 'conflict').length,
  });

  it('отдаёт только отмеченное', () => {
    const data = preview([
      row({ field: 'phone', state: 'fill', incoming: '+7 700 000 00 00' }),
      row({ field: 'email', state: 'fill', incoming: 'i@htq.test' }),
    ]);
    expect(pickValues(data, ['phone'])).toEqual({ phone: '+7 700 000 00 00' });
  });

  it('игнорирует отмеченное совпадающее поле', () => {
    const data = preview([row({ field: 'first_name', state: 'same', incoming: 'Иван' })]);
    expect(pickValues(data, ['first_name'])).toEqual({});
  });

  it('игнорирует поле, которого в предпросмотре не было', () => {
    const data = preview([row({ field: 'phone', state: 'fill' })]);
    expect(pickValues(data, ['status', 'hire_date'])).toEqual({});
  });
});

describe('matchQueryIsAnswerable', () => {
  const query = (over: Partial<Parameters<typeof matchQueryIsAnswerable>[0]>) => ({
    email: '', phone: '', firstName: '', lastName: '', ...over,
  });

  it('пустая форма — не спрашиваем (иначе это выгрузка справочника)', () => {
    expect(matchQueryIsAnswerable(query({}))).toBe(false);
  });

  it('почта с доменом — спрашиваем', () => {
    expect(matchQueryIsAnswerable(query({ email: 'i@htq.test' }))).toBe(true);
    expect(matchQueryIsAnswerable(query({ email: 'i@' }))).toBe(false);
  });

  it('короткий номер не опознаёт человека', () => {
    expect(matchQueryIsAnswerable(query({ phone: '5581' }))).toBe(false);
    expect(matchQueryIsAnswerable(query({ phone: '+7 (700) 483-55-81' }))).toBe(true);
  });

  it('одной фамилии мало, имени с фамилией — достаточно', () => {
    expect(matchQueryIsAnswerable(query({ lastName: 'Иванов' }))).toBe(false);
    expect(matchQueryIsAnswerable(query({ firstName: 'Иван', lastName: 'Иванов' }))).toBe(true);
  });
});
