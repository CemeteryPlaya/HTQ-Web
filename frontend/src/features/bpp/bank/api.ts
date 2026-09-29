/**
 * Клиент «Оплаты факт» — загрузки банковских выписок (`/api/bpp/v1/bank/
 * imports…`; ТЗ §11.1–11.2, L-07, A4.1; сервер — `apps/bpp/views_bank.py`,
 * `services/bank/imports.py`).
 *
 * - загрузка — multipart (`account_id`, `file`, `period_from`, `period_to`,
 *   `comment`) с `Idempotency-Key`; формат файла задаёт шаблон счёта, у
 *   выписки 1С период берётся из файла. Ответ — карточка загрузки в
 *   «Обрабатывается» и `warnings` — пересечение периода с прошлыми
 *   загрузками счёта (повторные операции отсекутся как дубли, BR-075);
 * - карточка (`imports/<id>`) — её экран опрашивает, пока идёт разбор;
 * - строки (`imports/<id>/lines`) — страницами `{items, total, page,
 *   page_size}`.
 *
 * Загружает `bpp.bank` `edit` (ФД), смотрят — `bpp.bank` `view` (ФД, БУХ).
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { RegistryPage } from '../core/registryTypes';
import type { StatementFormat } from '../settings/api';

export type BankImportStatus = 'processing' | 'loaded' | 'failed' | 'cancelled';

/** Строка реестра L-07. */
export interface BankImportRow {
  id: string;
  number: string;
  account: { id: string; iban: string; bank_name: string; currency: string };
  bank_name: string;
  format: StatementFormat;
  period_from: string;
  period_to: string;
  status: BankImportStatus;
  status_label: string;
  filename: string;
  comment: string;
  /** Документов (строк данных) в файле. */
  rows_total: number;
  /** Из них списаний со счёта организации. */
  debits: number;
  /** Сколько списаний уже записано — прогресс разбора. */
  rows_done: number;
  /** Пропущено дублей (BR-075). */
  duplicates: number;
  errors_count: number;
  /** Строк выписки в базе (без отменённых). */
  lines: number;
  matched: number;
  unmatched: number;
  author_id: number | null;
  author_name: string | null;
  created_at: string;
  finished_at: string | null;
}

/** Карточка загрузки — строка реестра плюс ход разбора и ошибки строк. */
export interface BankImportCard extends BankImportRow {
  /** «Строка 17: не распознана дата „31.02.2026“». */
  errors: string[];
  /** Почему не загрузилась вся выписка («Ошибка загрузки»). */
  failure: string;
  /** 0…100. */
  progress: number;
  file: { id?: string | number; filename?: string } | null;
  /** Только в ответе загрузки. */
  warnings?: string[];
}

export interface StatementLine {
  id: string;
  row_no: number;
  doc_date: string;
  doc_number: string;
  /** Строка-десятичная. */
  amount: string;
  currency: string;
  recipient_name: string;
  recipient_bin: string;
  recipient_iban: string;
  purpose: string;
  match_status: string;
  match_status_label: string;
  /** Отменённые строки приходят только с `?include_cancelled=1` — экран их не просит. */
  cancelled_at: string | null;
}

export interface ImportInput {
  account_id: string;
  file: File;
  period_from: string;
  period_to: string;
  comment: string;
}

/** Экраны «Оплаты факт» внутри раздела `/bpp`. */
export const BANK_BASE = '/bpp/bank';
export const bankImportHref = (id: string) => `${BANK_BASE}/${id}`;

/** Адрес реестра для `BppRegistry` (относительно `/api/`). */
export const BANK_IMPORTS_ENDPOINT = apiPath('bpp', 'bank/imports');

/** Пока загрузка «Обрабатывается» — экран опрашивает её раз в столько мс. */
export const IMPORT_POLL_MS = 2000;

/** Потолок файла выписки (ТЗ §11.2 «до 20 МБ»; тип файла `bank_statement`). */
export const MAX_FILE_MB = 20;

const path = (suffix: string) => apiPath('bpp', `bank/imports/${suffix}`);

export const bankImportApi = {
  create: (key: string, input: ImportInput) => {
    const form = new FormData();
    form.append('account_id', input.account_id);
    form.append('file', input.file);
    if (input.period_from) form.append('period_from', input.period_from);
    if (input.period_to) form.append('period_to', input.period_to);
    if (input.comment.trim()) form.append('comment', input.comment.trim());
    return api.post<BankImportCard>(BANK_IMPORTS_ENDPOINT, form, {
      headers: { 'Idempotency-Key': key },
    }).then((r) => r.data);
  },

  get: (id: string) => api.get<BankImportCard>(path(id)).then((r) => r.data),

  lines: (id: string, page: number, pageSize: number) =>
    api.get<RegistryPage<StatementLine>>(path(`${id}/lines`), {
      params: { page, page_size: pageSize },
    }).then((r) => r.data),
};

export const bankImportKey = (id: string) => ['bpp', 'bank', 'import', id] as const;
