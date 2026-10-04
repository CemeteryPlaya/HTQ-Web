/**
 * Проверки реквизитов контрагента на фронте (ТЗ §18) — ТОТ ЖЕ алгоритм и те
 * же тексты, что на сервере (`backend/apps/bpp/services/counterparties/validation.py`).
 *
 * Сервер остаётся судьёй: здесь лишь не даём отправить заведомый отказ
 * E-CTR-03/E-CTR-04 и показываем причину у поля до запроса. Поэтому правило
 * переписано дословно, без «улучшений»: расхождение с сервером хуже, чем
 * его отсутствие, — фронт пропустил бы номер, который сервер отвергнет, или
 * наоборот не дал бы сохранить верный.
 *
 * БИН/ИИН — 12 цифр с контрольным разрядом по алгоритму РК: сумма первых 11
 * цифр с весами 1…11 по модулю 11; остаток 10 — второй проход с весами
 * 3…11, 1, 2; остаток 10 во втором проходе — номер недействителен.
 * Остальные остатки сравниваются с 12-й цифрой.
 *
 * Рег. номер нормализуется до проверки: пробелы и любые дефисы/тире
 * отбрасываются, буквы — в верхний регистр (так его хранит сервер).
 */

export type CounterpartyKind = 'legal' | 'ip' | 'individual' | 'nonresident';

export const NONRESIDENT_MAX = 30;

const WEIGHTS_1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const WEIGHTS_2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2];
// Пробелы и любые дефисы/тире: «-» и U+2010…U+2015 — как `_STRIP` сервера.
const STRIP = /[\s\-‐-―]+/g;
const TWELVE_DIGITS = /^\d{12}$/;
const IBAN_KZ = /^KZ\d{2}[A-Z0-9]{16}$/;
const BIC = /^[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?$/;

/** Итог проверки: нормализованное значение или текст отказа. */
export type CheckResult =
  | { ok: true; value: string; message?: undefined }
  | { ok: false; message: string; value?: undefined };

const fail = (message: string): CheckResult => ({ ok: false, message });

// ── рег. номер ──────────────────────────────────────────────────────────

export function normalizeRegNumber(raw: string | null | undefined): string {
  return String(raw ?? '').replace(STRIP, '').toUpperCase();
}

const rest = (digits: number[], weights: number[]) =>
  digits.slice(0, 11).reduce((sum, digit, index) => sum + digit * weights[index], 0) % 11;

/** Контрольный разряд БИН/ИИН. `value` — уже нормализованный номер. */
export function binIinIsValid(value: string): boolean {
  if (!TWELVE_DIGITS.test(value ?? '')) return false;
  const digits = [...value].map(Number);
  let check = rest(digits, WEIGHTS_1);
  if (check === 10) {
    check = rest(digits, WEIGHTS_2);
    if (check === 10) return false;
  }
  return check === digits[11];
}

/**
 * Проверить рег. номер так же, как сервер (`check_reg_number`).
 *
 * Казахстан — БИН/ИИН с контрольным разрядом. Нерезидент — свободный номер
 * до 30 символов. Резидентский тип с другой страной тоже получает свободный
 * номер: алгоритм РК к чужим номерам неприменим. Нерезидент со страной
 * «Казахстан» — противоречие.
 */
export function checkRegNumber(
  kind: CounterpartyKind | string,
  countryCode: string,
  raw: string | null | undefined,
): CheckResult {
  const number = normalizeRegNumber(raw);
  const country = (countryCode ?? '').toUpperCase();
  if (!number) return fail('Укажите БИН/ИИН или регистрационный номер контрагента.');
  if (kind === 'nonresident' && country === 'KZ') {
    return fail(
      'Нерезидент не может быть из Казахстана. Для казахстанского контрагента выберите '
      + 'тип «Юридическое лицо», «ИП» или «Физическое лицо» и укажите БИН/ИИН.',
    );
  }
  if (country === 'KZ') {
    if (!TWELVE_DIGITS.test(number)) {
      return fail(`БИН/ИИН «${number}» должен состоять из 12 цифр. `
        + 'Проверьте номер по документам контрагента.');
    }
    if (!binIinIsValid(number)) {
      return fail(`БИН/ИИН «${number}» не прошёл проверку контрольного разряда. `
        + 'Проверьте номер по документам контрагента.');
    }
    return { ok: true, value: number };
  }
  if (number.length > NONRESIDENT_MAX) {
    return fail(`Регистрационный номер нерезидента — не длиннее ${NONRESIDENT_MAX} символов `
      + '(без пробелов и дефисов).');
  }
  return { ok: true, value: number };
}

// ── банковские реквизиты ────────────────────────────────────────────────

export const normalizeIban = (raw: string | null | undefined): string =>
  String(raw ?? '').replace(/\s+/g, '').toUpperCase();

export const normalizeBic = normalizeIban;

/**
 * Остаток от деления длинного числа-строки на 97 — по кускам, без BigInt:
 * 34-значное число не помещается в `number`, а результат нужен точный.
 */
function mod97(numeric: string): number {
  let remainder = 0;
  for (let index = 0; index < numeric.length; index += 7) {
    remainder = Number(`${remainder}${numeric.slice(index, index + 7)}`) % 97;
  }
  return remainder;
}

/** IBAN Казахстана: `KZ` + 18 знаков, контроль ISO 13616 (mod 97 = 1). */
export function ibanIsValid(value: string): boolean {
  if (!IBAN_KZ.test(value ?? '')) return false;
  const moved = value.slice(4) + value.slice(0, 4);
  const numeric = [...moved].map((ch) => parseInt(ch, 36).toString()).join('');
  return mod97(numeric) === 1;
}

/** БИК (SWIFT): 8 или 11 знаков — банк, страна, город, филиал. */
export const bicIsValid = (value: string): boolean => BIC.test(value ?? '');

export function checkIban(raw: string | null | undefined): CheckResult {
  const value = normalizeIban(raw);
  if (!value) return fail('Укажите IBAN счёта.');
  if (!ibanIsValid(value)) {
    return fail(`IBAN «${value}» неверен: нужен счёт вида KZ + 18 знаков `
      + 'с верными контрольными цифрами. Проверьте реквизиты.');
  }
  return { ok: true, value };
}

export function checkBic(raw: string | null | undefined): CheckResult {
  const value = normalizeBic(raw);
  if (!value) return fail('Укажите БИК счёта.');
  if (!bicIsValid(value)) {
    return fail(`БИК «${value}» неверен: нужно 8 или 11 латинских букв `
      + 'и цифр (например, HSBKKZKX). Проверьте реквизиты.');
  }
  return { ok: true, value };
}
