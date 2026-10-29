/**
 * Ошибки по полям из двух конвертов бэкенда тендерного модуля:
 * - сервис — `{detail, code, fields: [{field, message}]}` (имена полей тела,
 *   `items[0].qty`);
 * - платформенная проверка типов pydantic — `{detail: [{type, loc, msg}]}`
 *   (422 без `code`): `loc` → то же имя поля, текст — свой, русский, потому
 *   что `msg` pydantic английский.
 */
import { describe, expect, it } from 'vitest';

import { fieldErrorsOf, isTypeError, itemFieldErrors } from './fieldErrors';

const coded = {
  response: {
    status: 422,
    data: {
      detail: 'Не удалось сохранить заявку.',
      code: 'E-VAL-01',
      fields: [
        { field: 'project_id', message: 'Выберите проект' },
        { field: 'items[1].qty', message: 'количество: нужно число больше нуля' },
      ],
    },
  },
};

const pydantic = {
  response: {
    status: 422,
    data: {
      detail: [
        { type: 'uuid_parsing', loc: ['items', 0, 'uom_id'], msg: 'Input should be a valid UUID' },
        { type: 'datetime_parsing', loc: ['body', 'deadline_at'], msg: 'Input should be a valid datetime' },
      ],
    },
  },
};

describe('fieldErrorsOf', () => {
  it('конверт сервиса — поля как есть', () => {
    expect(fieldErrorsOf(coded, 'Неверный формат')).toEqual({
      project_id: 'Выберите проект',
      'items[1].qty': 'количество: нужно число больше нуля',
    });
  });

  it('pydantic — loc в имя поля, текст — запасной русский', () => {
    expect(fieldErrorsOf(pydantic, 'Неверный формат')).toEqual({
      'items[0].uom_id': 'Неверный формат',
      deadline_at: 'Неверный формат',
    });
    expect(isTypeError(pydantic)).toBe(true);
    expect(isTypeError(coded)).toBe(false);
  });

  it('не ошибка API — пусто', () => {
    expect(fieldErrorsOf(new Error('сеть'), 'x')).toEqual({});
    expect(isTypeError(new Error('сеть'))).toBe(false);
  });
});

describe('itemFieldErrors', () => {
  it('items[i].x → ключ строки формы, прочие поля — отдельно', () => {
    const keys = ['row-a', 'row-b'];
    expect(itemFieldErrors(fieldErrorsOf(coded, ''), keys)).toEqual({
      fields: { project_id: 'Выберите проект' },
      items: { 'row-b': 'количество: нужно число больше нуля' },
    });
  });
});
