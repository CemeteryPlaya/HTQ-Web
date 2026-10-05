/**
 * Проверка реквизитов на фронте — те же векторы, что у сервера
 * (`backend/apps/bpp/tests/counterparties/test_validation.py`).
 *
 * Сервер не зашивает номера руками, а находит их перебором
 * (`tests/counterparties/common.py`): здесь тот же перебор написан заново и
 * сверен с найденными им значениями — две независимые записи одного правила.
 */
import { describe, expect, it } from 'vitest';

import {
  bicIsValid, binIinIsValid, checkBic, checkIban, checkRegNumber, ibanIsValid,
  normalizeRegNumber,
} from './validation';

const W1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const W2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2];
const rest = (body: string, weights: number[]) =>
  [...body].reduce((sum, d, i) => sum + Number(d) * weights[i], 0) % 11;

function* bodies(start = 10 ** 10) {
  for (let n = start; n < start + 500_000; n += 1) yield String(n).padStart(11, '0');
}

function binFirstPass(): string {
  for (const body of bodies()) {
    const r = rest(body, W1);
    if (r !== 10) return body + r;
  }
  throw new Error('не найден');
}

function binSecondPass(): string {
  for (const body of bodies()) {
    if (rest(body, W1) === 10 && rest(body, W2) !== 10) return body + rest(body, W2);
  }
  throw new Error('не найден');
}

function binBodyTenTwice(): string {
  for (const body of bodies()) {
    if (rest(body, W1) === 10 && rest(body, W2) === 10) return body;
  }
  throw new Error('не найден');
}

/** IBAN Казахстана с верными контрольными цифрами — `common.kz_iban`. */
function kzIban(account: string): string {
  const numeric = [...`${account}KZ00`].map((ch) => parseInt(ch, 36).toString()).join('');
  const check = 98 - Number(BigInt(numeric) % 97n);
  return `KZ${String(check).padStart(2, '0')}${account}`;
}

// Значения, которые находит перебор сервера (сверено запуском common.py).
const FIRST_PASS = '100000000001';
const SECOND_PASS = '100000000205';
const TEN_TWICE_BODY = '10000000028';

describe('БИН/ИИН — контрольный разряд', () => {
  it('перебор находит те же номера, что и сервер', () => {
    expect(binFirstPass()).toBe(FIRST_PASS);
    expect(binSecondPass()).toBe(SECOND_PASS);
    expect(binBodyTenTwice()).toBe(TEN_TWICE_BODY);
  });

  it('первый проход', () => {
    expect(binIinIsValid(FIRST_PASS)).toBe(true);
    const wrong = FIRST_PASS.slice(0, 11) + String((Number(FIRST_PASS[11]) + 1) % 10);
    expect(binIinIsValid(wrong)).toBe(false);
  });

  it('остаток 10 — второй проход с весами 3…11, 1, 2', () => {
    expect(binIinIsValid(SECOND_PASS)).toBe(true);
    const others = Array.from({ length: 10 }, (_, d) => SECOND_PASS.slice(0, 11) + d)
      .filter((n) => n !== SECOND_PASS);
    expect(others.some(binIinIsValid)).toBe(false);
  });

  it('остаток 10 и во втором проходе — недействителен при любом 12-м разряде', () => {
    const all = Array.from({ length: 10 }, (_, d) => TEN_TWICE_BODY + d);
    expect(all.some(binIinIsValid)).toBe(false);
    const result = checkRegNumber('legal', 'KZ', `${TEN_TWICE_BODY}0`);
    expect(result.ok).toBe(false);
  });

  it('длина и буквы', () => {
    expect(binIinIsValid(FIRST_PASS.slice(0, 11))).toBe(false);
    expect(binIinIsValid(`${FIRST_PASS}0`)).toBe(false);
    expect(binIinIsValid(`A${FIRST_PASS.slice(1)}`)).toBe(false);
    for (const raw of [FIRST_PASS.slice(0, 11), `${FIRST_PASS}0`, `БИН${FIRST_PASS}`]) {
      expect(checkRegNumber('ip', 'KZ', raw).ok).toBe(false);
    }
  });

  it('пробелы, дефисы и тире отбрасываются', () => {
    const n = FIRST_PASS;
    const raw = ` ${n.slice(0, 3)} ${n.slice(3, 6)}-${n.slice(6, 9)}–${n.slice(9)} `;
    expect(normalizeRegNumber(raw)).toBe(n);
    expect(checkRegNumber('individual', 'kz', raw)).toEqual({ ok: true, value: n });
  });
});

describe('рег. номер нерезидента и чужой страны', () => {
  it('свободный номер до 30 символов', () => {
    expect(checkRegNumber('nonresident', 'RU', 'ОГРН 1027700132195'))
      .toEqual({ ok: true, value: 'ОГРН1027700132195' });
    const thirty = 'A'.repeat(30);
    expect(checkRegNumber('nonresident', 'RU', thirty)).toEqual({ ok: true, value: thirty });
    expect(checkRegNumber('nonresident', 'KG', [...thirty].join('-')))
      .toEqual({ ok: true, value: thirty });
    expect(checkRegNumber('nonresident', 'RU', 'A'.repeat(31)).ok).toBe(false);
  });

  it('пустой номер и нерезидент из Казахстана — отказ', () => {
    expect(checkRegNumber('nonresident', 'RU', ' - ').ok).toBe(false);
    expect(checkRegNumber('nonresident', 'KZ', FIRST_PASS).ok).toBe(false);
  });

  it('российское ИП — не БИН: алгоритм РК не применяется', () => {
    expect(checkRegNumber('ip', 'RU', '304500116000157'))
      .toEqual({ ok: true, value: '304500116000157' });
  });
});

describe('IBAN и БИК', () => {
  it('IBAN — KZ + 18 знаков, mod 97', () => {
    const good = 'KZ86125KZT5004100100';
    expect(ibanIsValid(good)).toBe(true);
    expect(kzIban('125KZT5004100199')).toBe('KZ32125KZT5004100199');
    expect(ibanIsValid(kzIban('125KZT5004100199'))).toBe(true);
    expect(ibanIsValid('KZ87125KZT5004100100')).toBe(false); // контрольные цифры
    expect(ibanIsValid('KZ86125KZT500410010')).toBe(false); // 17 знаков после KZ
    expect(ibanIsValid('RU86125KZT5004100100')).toBe(false); // не Казахстан
    expect(checkIban(' kz86 125k zt50 0410 0100 ')).toEqual({ ok: true, value: good });
    expect(checkIban('KZ87125KZT5004100100').ok).toBe(false);
  });

  it('БИК — 8 или 11 знаков', () => {
    expect(bicIsValid('HSBKKZKX')).toBe(true);
    expect(bicIsValid('HSBKKZKX001')).toBe(true);
    for (const bad of ['HSBKKZK', 'HSBKKZKX0', 'HSBKKZKX0012', '1234KZKX', '']) {
      expect(bicIsValid(bad)).toBe(false);
    }
    expect(checkBic('hsbkkzkx')).toEqual({ ok: true, value: 'HSBKKZKX' });
    expect(checkBic('HSBK').ok).toBe(false);
  });
});
