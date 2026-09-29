/**
 * Клиент справочника «Банковские счета организации и шаблоны выписок»
 * (`/api/bpp/v1/bank/accounts…`, `bank/templates…`; ТЗ §11.1, §18, A3.1;
 * сервер — `apps/bpp/views_bank.py`, `services/bank/settings.py`).
 *
 * Читают держатели `bpp.bank` или `bpp.settings` `view` (ФД, БУХ, АДМ),
 * заводят и правят — `bpp.settings` `edit` (АДМ). Удаления нет: архив —
 * `is_active: false`. Записывающие ручки идемпотентны (`Idempotency-Key` от
 * `useIdempotentAction`), правка сверяет `version` (409 `E-CON-01`).
 *
 * Предпросмотр образца (`templates/<id>/preview`) ничего не сохраняет и
 * читает СОХРАНЁННЫЙ шаблон — несохранённые правки формы он не видит.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type StatementFormat = 'onec' | 'xlsx' | 'csv';
export type AmountMode = 'signed' | 'split';

export interface StatementTemplate {
  id: string;
  name: string;
  format: StatementFormat;
  encoding: string;
  delimiter: string;
  /** Маска для человека: «ДД.ММ.ГГГГ». */
  date_format: string;
  /** Поле выписки → текст заголовка колонки в файле. */
  columns: Record<string, string>;
  amount_mode: AmountMode;
  is_active: boolean;
  /** Сколько действующих счетов разбирается по шаблону. */
  active_accounts: number;
  version: number;
}

export interface TemplateInput {
  name: string;
  format: StatementFormat;
  encoding: string;
  delimiter: string;
  date_format: string;
  columns: Record<string, string>;
  amount_mode: AmountMode;
}

export interface OrgAccount {
  id: string;
  iban: string;
  bank_name: string;
  bic: string;
  currency: string;
  template: { id: string; name: string; format: StatementFormat };
  is_active: boolean;
  version: number;
}

export interface AccountInput {
  iban: string;
  bic: string;
  bank_name: string;
  currency: string;
  template_id: string;
}

export interface PreviewColumn {
  field: string;
  label: string;
  header: string;
  /** Номер колонки в файле с 0; `null` — необязательная колонка не нашлась. */
  index: number | null;
}

export interface PreviewRow {
  row_no: number;
  date: string;
  doc_number: string;
  /** Строка-десятичная, по модулю. */
  amount: string;
  direction: 'debit' | 'credit';
  currency?: string;
  payer_account?: string;
  recipient_name?: string;
  recipient_bin?: string;
  recipient_iban?: string;
  purpose?: string;
}

export interface TemplatePreview {
  header_row: number;
  columns: PreviewColumn[];
  rows: PreviewRow[];
  errors: string[];
}

/** Экран настроек внутри раздела `/bpp`; вкладка — в `?tab=`. */
export const SETTINGS_BASE = '/bpp/settings';
export const settingsTabHref = (tab: 'accounts' | 'templates') => `${SETTINGS_BASE}?tab=${tab}`;

const path = (suffix: string) => apiPath('bpp', `bank/${suffix}`);
const keyed = (key: string) => ({ headers: { 'Idempotency-Key': key } });
const activeOnly = (active: boolean) => (active ? { params: { active: 1 } } : undefined);

export const bankSettingsApi = {
  accounts: (active = false) =>
    api.get<OrgAccount[]>(path('accounts'), activeOnly(active)).then((r) => r.data),

  createAccount: (key: string, body: AccountInput) =>
    api.post<OrgAccount>(path('accounts'), body, keyed(key)).then((r) => r.data),

  updateAccount: (
    id: string, key: string, body: Partial<AccountInput> & { version: number; is_active?: boolean },
  ) => api.patch<OrgAccount>(path(`accounts/${id}`), body, keyed(key)).then((r) => r.data),

  templates: (active = false) =>
    api.get<StatementTemplate[]>(path('templates'), activeOnly(active)).then((r) => r.data),

  createTemplate: (key: string, body: TemplateInput) =>
    api.post<StatementTemplate>(path('templates'), body, keyed(key)).then((r) => r.data),

  updateTemplate: (
    id: string, key: string,
    body: Partial<TemplateInput> & { version: number; is_active?: boolean },
  ) => api.patch<StatementTemplate>(path(`templates/${id}`), body, keyed(key)).then((r) => r.data),

  preview: (id: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<TemplatePreview>(path(`templates/${id}/preview`), form).then((r) => r.data);
  },
};

/** Ключи кеша: общие для вкладок настроек и формы загрузки выписки. */
export const ACCOUNTS_KEY = ['bpp', 'bank', 'accounts'] as const;
export const TEMPLATES_KEY = ['bpp', 'bank', 'templates'] as const;
