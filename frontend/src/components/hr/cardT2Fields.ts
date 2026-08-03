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
import type { CardT2Section } from '@/api/hr';

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
