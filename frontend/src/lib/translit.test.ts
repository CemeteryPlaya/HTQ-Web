/**
 * Транслитерация и корпоративный адрес.
 *
 * Отдельно — сторож на расхождение с серверной таблицей. Разъехавшись, они
 * дадут адрес, который не совпадёт с реальным ящиком: форма предложит
 * `sanzhar.inamzhanov`, а провижионер заведёт `sanzar.inamzanov`, и разберутся
 * с этим уже на почтовом сервере, а не в коде.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  TRANSLIT_MAP,
  corporateEmail,
  emailLocalPart,
  slug,
  translit,
  withSuggestedEmail,
} from './translit';

describe('транслитерация', () => {
  it('переводит кириллицу побуквенно', () => {
    expect(translit('Санжар')).toBe('sanzhar');
    expect(translit('Инамжанов')).toBe('inamzhanov');
    expect(translit('Щербаков')).toBe('shcherbakov');
    expect(translit('Юлия')).toBe('yuliya');
  });

  it('снимает мягкий и твёрдый знаки', () => {
    expect(translit('Игорь')).toBe('igor');
    expect(translit('Объедков')).toBe('obedkov');
  });

  it('латиницу оставляет как есть', () => {
    expect(translit('Smith')).toBe('smith');
  });

  it('slug отсекает пробелы, дефисы и прочее', () => {
    expect(slug('Анна-Мария')).toBe('annamariya');
    expect(slug(' Пётр ')).toBe('petr');
  });
});

describe('корпоративный адрес', () => {
  it('собирается по шаблону имя.фамилия', () => {
    expect(corporateEmail('Санжар', 'Инамжанов', 'htq.group'))
      .toBe('sanzhar.inamzhanov@htq.group');
  });

  it('одно пустое имя не даёт точки на краю', () => {
    expect(emailLocalPart('Санжар', '')).toBe('sanzhar');
    expect(emailLocalPart('', 'Инамжанов')).toBe('inamzhanov');
  });

  it('без имени и фамилии адрес не предлагается вовсе', () => {
    // Не `user@htq.group`: заведомо неверный адрес, отправленный не глядя,
    // хуже пустого поля.
    expect(corporateEmail('', '')).toBe('');
  });
});

describe('подстановка адреса в форму', () => {
  const form = { first_name: 'Санжар', last_name: 'Инамжанов', email: '' };

  it('подставляет адрес, пока его не правили', () => {
    expect(withSuggestedEmail(form, false).email).toBe('sanzhar.inamzhanov@htq.group');
  });

  it('не трогает адрес, который правили руками', () => {
    const edited = { ...form, email: 's.inamzhanov@htq.group' };
    expect(withSuggestedEmail(edited, true).email).toBe('s.inamzhanov@htq.group');
  });

  it('пересчитывает адрес при смене фамилии', () => {
    const next = withSuggestedEmail({ ...form, last_name: 'Петров' }, false);
    expect(next.email).toBe('sanzhar.petrov@htq.group');
  });

  it('очищает адрес, если имя стёрли, — а не оставляет чужой', () => {
    const filled = { ...form, email: 'sanzhar.inamzhanov@htq.group' };
    expect(withSuggestedEmail({ ...filled, first_name: '', last_name: '' }, false).email).toBe('');
  });

  it('прочие поля формы не трогает', () => {
    const withExtras = { ...form, patronymic: 'Ерланович', password: 'secret' };
    expect(withSuggestedEmail(withExtras, false)).toMatchObject({
      patronymic: 'Ерланович', password: 'secret',
    });
  });
});

describe('сторож: таблица совпадает с серверной', () => {
  it('посимвольно равна apps/mail/services/mailbox_service.py::_TRANSLIT', () => {
    const source = readFileSync(
      resolve(__dirname, '../../../backend/apps/mail/services/mailbox_service.py'),
      'utf-8',
    );
    const block = source.split('_TRANSLIT = {')[1].split('}')[0];

    const backend: Record<string, string> = {};
    for (const [, key, value] of block.matchAll(/"(.)":\s*"([^"]*)"/g)) {
      backend[key] = value;
    }

    expect(Object.keys(backend).length).toBeGreaterThan(30);
    expect(TRANSLIT_MAP).toEqual(backend);
  });
});
