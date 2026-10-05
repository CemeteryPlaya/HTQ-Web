/**
 * Поля шаблона выписки — зеркало `apps/bpp/services/bank/templates.py`
 * (`FIELDS`, `required_fields`): форма показывает недостающие обязательные
 * колонки до «Сохранить», сервер проверяет то же самое (422 `E-VAL-01`).
 *
 * Обязательны дата, номер документа, сумма (одна колонка со знаком или
 * «Дебет» и «Кредит» — по режиму) и назначение. Выписке 1С колонки не
 * нужны вовсе: её поля задаёт стандарт формата.
 */
import type { AmountMode, StatementFormat } from './api';

export interface TemplateField {
  key: string;
  labelKey: string;
  label: string;
}

const f = (key: string, label: string): TemplateField => ({
  key, labelKey: `bpp.bankSettings.fields.${key}`, label,
});

export const TEMPLATE_FIELDS: TemplateField[] = [
  f('date', 'Дата'),
  f('doc_number', 'Номер документа'),
  f('amount', 'Сумма'),
  f('debit', 'Дебет'),
  f('credit', 'Кредит'),
  f('currency', 'Валюта'),
  f('payer_account', 'Счёт плательщика'),
  f('recipient_name', 'Получатель'),
  f('recipient_bin', 'БИН/ИИН получателя'),
  f('recipient_iban', 'IBAN получателя'),
  f('purpose', 'Назначение платежа'),
];

const AMOUNT_FIELDS: Record<AmountMode, string[]> = {
  signed: ['amount'],
  split: ['debit', 'credit'],
};

/** Поля суммы, которых в этом режиме нет (в форме не показываются). */
export const unusedAmountFields = (mode: AmountMode): string[] =>
  mode === 'signed' ? AMOUNT_FIELDS.split : AMOUNT_FIELDS.signed;

export const requiredFields = (mode: AmountMode): string[] =>
  ['date', 'doc_number', ...AMOUNT_FIELDS[mode], 'purpose'];

/** Обязательные поля без заголовка; у 1С — никаких. */
export function missingRequired(
  format: StatementFormat, mode: AmountMode, columns: Record<string, string>,
): TemplateField[] {
  if (format === 'onec') return [];
  const required = requiredFields(mode);
  return TEMPLATE_FIELDS.filter(
    (field) => required.includes(field.key) && !(columns[field.key] ?? '').trim(),
  );
}

/** Подписи форматов — для селекта шаблона и формы загрузки. */
export const FORMAT_LABELS: Record<StatementFormat, [string, string]> = {
  onec: ['bpp.bankSettings.formats.onec', '1С (1CClientBankExchange, .txt)'],
  xlsx: ['bpp.bankSettings.formats.xlsx', 'Excel (.xlsx)'],
  csv: ['bpp.bankSettings.formats.csv', 'CSV'],
};

/** Допустимые расширения файла по формату (`templates.EXTENSIONS`). */
export const FORMAT_ACCEPT: Record<StatementFormat, string> = {
  onec: '.txt',
  xlsx: '.xlsx',
  csv: '.csv,.txt',
};
