/**
 * Спецификации полей Т-2 карточки сотрудника — ЕДИНЫЙ источник правды.
 *
 * Потребителей два: `CardT2SectionDialog` (посекционная правка с карточки
 * сотрудника) и `EmployeeFormDialog` (те же поля встроены в форму создания/
 * редактирования). Держать два списка полей нельзя: они разъедутся на первой
 * же правке, и одна из форм начнёт молча терять поле.
 *
 * Порядок секций в `T2_SECTIONS` совпадает с порядком полей
 * `EmployeeCardT2Patch` на бэкенде (financial, personal, certs) — именно в нём
 * `employee_card_t2_service.upsert` применяет патч.
 */
import type { CardT2, CardT2Section } from '@/api/hr';

export type FieldKind = 'text' | 'money' | 'date';

export interface FieldSpec {
  name: string;
  kind: FieldKind;
  labelKey: string;
  labelFallback: string;
}

export const T2_SECTIONS: readonly CardT2Section[] = ['financial', 'personal', 'certs'];

export const SECTION_FIELDS: Record<CardT2Section, FieldSpec[]> = {
  financial: [
    { name: 'salary', kind: 'money', labelKey: 'hr.pages.employees.fields.salary', labelFallback: 'Оклад' },
    { name: 'bonus', kind: 'money', labelKey: 'hr.pages.employees.fields.bonus', labelFallback: 'Премия' },
    { name: 'bank_account', kind: 'text', labelKey: 'hr.pages.employees.fields.bankAccount', labelFallback: 'Банковский счёт' },
  ],
  personal: [
    { name: 'passport_data', kind: 'text', labelKey: 'hr.pages.employees.fields.passportData', labelFallback: 'Паспортные данные' },
    { name: 'inn', kind: 'text', labelKey: 'hr.pages.employees.fields.inn', labelFallback: 'ИИН/ИНН' },
    { name: 'birth_date', kind: 'date', labelKey: 'hr.pages.employees.fields.birthDate', labelFallback: 'Дата рождения' },
    { name: 'birth_place', kind: 'text', labelKey: 'hr.pages.employees.fields.birthPlace', labelFallback: 'Место рождения' },
    { name: 'citizenship', kind: 'text', labelKey: 'hr.pages.employees.fields.citizenship', labelFallback: 'Гражданство' },
  ],
  certs: [
    { name: 'sro_permit_number', kind: 'text', labelKey: 'hr.pages.employees.fields.sroPermitNumber', labelFallback: 'Номер допуска СРО' },
    { name: 'sro_permit_expiry', kind: 'date', labelKey: 'hr.pages.employees.fields.sroPermitExpiry', labelFallback: 'Срок действия допуска СРО' },
    { name: 'safety_cert_number', kind: 'text', labelKey: 'hr.pages.employees.fields.safetyCertNumber', labelFallback: 'Номер сертификата ОТ' },
    { name: 'safety_cert_expiry', kind: 'date', labelKey: 'hr.pages.employees.fields.safetyCertExpiry', labelFallback: 'Срок действия сертификата ОТ' },
  ],
};

export const SECTION_TITLE: Record<CardT2Section, { key: string; fallback: string }> = {
  financial: { key: 'hr.pages.employees.sections.financial', fallback: 'Финансовые данные (конфиденциально)' },
  personal: { key: 'hr.pages.employees.sections.personal', fallback: 'Личные данные' },
  certs: { key: 'hr.pages.employees.sections.sro', fallback: 'СРО и Охрана труда' },
};

/** Деньги: бэкенд делает Decimal(str(v)) и отвечает 422 на мусор. */
export const MONEY_RE = /^\d+([.,]\d{1,2})?$/;

/** Состояние формы Т-2: все поля всех секций как строки (пустая = «нет значения»). */
export type T2FormState = Record<CardT2Section, Record<string, string>>;

export function emptyT2Form(): T2FormState {
  const out = {} as T2FormState;
  for (const section of T2_SECTIONS) {
    out[section] = Object.fromEntries(SECTION_FIELDS[section].map((f) => [f.name, '']));
  }
  return out;
}

/**
 * Раскладывает ответ `GET /card/t2` в состояние формы.
 *
 * Секции, отсутствующей в ответе (нет права view), в форме соответствуют
 * пустые поля — и она не должна попасть в payload: этим занимается
 * `buildCardT2Payload`, которому вызывающий передаёт список разрешённых
 * секций.
 */
export function t2FormFromServer(data: CardT2 | undefined): T2FormState {
  const out = emptyT2Form();
  if (!data) return out;
  for (const section of T2_SECTIONS) {
    const values = data[section] as Record<string, string | null> | undefined;
    if (!values) continue;
    for (const f of SECTION_FIELDS[section]) {
      out[section][f.name] = values[f.name] ?? '';
    }
  }
  return out;
}

export function isT2SectionDirty(
  form: T2FormState,
  initial: T2FormState,
  section: CardT2Section,
): boolean {
  return SECTION_FIELDS[section].some(
    (f) => (form[section][f.name] ?? '') !== (initial[section][f.name] ?? ''),
  );
}

/**
 * Собирает блок `card_t2` тела запроса.
 *
 * Отправляются ТОЛЬКО изменённые секции из числа разрешённых. Отправлять всё
 * подряд нельзя: открыть модалку и нажать «Сохранить» означало бы переписать
 * Т-2 тем, что успело подгрузиться (или не подгрузилось).
 *
 * `undefined` вместо пустого объекта — чтобы вызывающий просто не клал ключ в
 * тело запроса.
 */
export function buildCardT2Payload(
  form: T2FormState,
  initial: T2FormState,
  sections: CardT2Section[],
): Record<string, Record<string, string | null>> | undefined {
  const out: Record<string, Record<string, string | null>> = {};
  for (const section of sections) {
    if (!isT2SectionDirty(form, initial, section)) continue;
    out[section] = Object.fromEntries(
      SECTION_FIELDS[section].map((f) => {
        const raw = (form[section][f.name] ?? '').trim();
        if (raw === '') return [f.name, null];
        return [f.name, f.kind === 'money' ? raw.replace(',', '.') : raw];
      }),
    );
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

/** Ключи результата — `"<section>.<field>"`, чтобы форма могла подсветить поле. */
export function validateT2Money(
  form: T2FormState,
  sections: CardT2Section[],
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const section of sections) {
    for (const f of SECTION_FIELDS[section]) {
      if (f.kind !== 'money') continue;
      const raw = (form[section][f.name] ?? '').trim();
      if (raw === '') continue;
      if (!MONEY_RE.test(raw)) {
        errors[`${section}.${f.name}`] = 'Введите число, например 450000 или 450000.50';
      }
    }
  }
  return errors;
}
