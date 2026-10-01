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
import type { QueryClient } from '@tanstack/react-query';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import { exportRegistry, type ExportOutcome } from '../core/registryExport';
import type { RegistryPage } from '../core/registryTypes';
import { DASHBOARD_KEY } from '../dashboard/api';
import type { StatementFormat } from '../settings/api';

export type BankImportStatus = 'processing' | 'loaded' | 'reconciled' | 'failed' | 'cancelled';

/** Статус строки выписки (`LineMatchStatus`). */
export type LineMatchStatus = 'unmatched' | 'matched' | 'needs_review' | 'excluded';

/** Вкладка результата сверки — параметр `tab` ручки строк (`review` = `needs_review`). */
export type ReconTab = 'matched' | 'review' | 'unmatched' | 'excluded';
export const RECON_TABS: ReconTab[] = ['matched', 'review', 'unmatched', 'excluded'];
/** Ключ вкладки в итогах карточки. */
export const TAB_TOTAL_KEY: Record<ReconTab, LineMatchStatus> = {
  matched: 'matched', review: 'needs_review', unmatched: 'unmatched', excluded: 'excluded',
};

/** Число действующих строк группы и Σ их сумм. */
export interface GroupTotal {
  count: number;
  amount: string;
}

/** Итоги сверки по вкладкам; `unallocated` — Σ частей строк, не разложенных на счета. */
export interface ReconTotals {
  matched: GroupTotal;
  needs_review: GroupTotal;
  unmatched: GroupTotal;
  excluded: GroupTotal;
  unallocated: string;
}

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
  needs_review?: number;
  unmatched: number;
  excluded?: number;
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
  /** Итоги сверки по вкладкам (после разбора). */
  totals?: ReconTotals;
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
  match_status: LineMatchStatus | string;
  match_status_label: string;
  /** Номера счетов, найденные в назначении. */
  found_numbers?: string[];
  review_reason?: string;
  /** Причина «Требует проверки» — текст ТЗ §11.2. */
  review_reason_label?: string;
  matches?: LineMatch[];
  allocated?: string;
  /** Часть строки, не разложенная ни на один счёт. */
  unallocated?: string;
  excluded_comment?: string;
  /** Отменённые строки приходят только с `?include_cancelled=1` — экран их не просит. */
  cancelled_at: string | null;
}

/** Сопоставление строки со счётом. */
export interface LineMatch {
  id: string;
  invoice_id: string;
  invoice_number: string;
  invoice_url: string;
  invoice_status: string;
  invoice_status_label: string;
  invoice_amount: string;
  invoice_currency: string;
  /** «Оплачено по банку всего» счёта (только подтверждённые сопоставления). */
  paid_bank_amount: string;
  recon_status: string;
  recon_status_label: string;
  /** Сколько платежа отнесено на этот счёт. */
  amount: string;
  state: 'active' | 'review';
  manual: boolean;
  comment: string;
  review_reason: string;
  review_reason_label: string;
}

/** Кандидат для «Сопоставить вручную». */
export interface MatchCandidate {
  id: string;
  number: string;
  status: string;
  status_label: string;
  amount: string;
  currency_code: string;
  paid_bank_amount: string;
  remainder: string;
  recon_status: string;
  recon_status_label: string;
  counterparty: { id: string; name: string; reg_number: string };
  same_bin: boolean;
  ext_number: string;
  ext_date: string | null;
}

export interface Allocation {
  invoice_id: string;
  amount: string;
}

/** Сколько счетов и строк заденет отмена загрузки. */
export interface CancelImpact {
  invoices: number;
  lines: number;
}

export interface ImportInput {
  account_id: string;
  file: File;
  period_from: string;
  period_to: string;
  comment: string;
}

/**
 * Окно автосверки: сервер ставит «Загружена», и только потом гонит
 * автосверку, после которой загрузка становится «Сверена». Пока `finished_at`
 * моложе этого окна, экран продолжает опрашивать карточку, а «Сверить»
 * недоступна (иначе сверка запустилась бы второй раз параллельно).
 */
export const AUTOMATCH_WINDOW_MS = 3 * 60 * 1000;

/** «Загружена», автосверка ещё может идти. */
export function autoMatchRunning(card: { status: string; finished_at: string | null }, now = Date.now()): boolean {
  if (card.status !== 'loaded' || !card.finished_at) return false;
  const finished = Date.parse(card.finished_at);
  return Number.isFinite(finished) && now - finished < AUTOMATCH_WINDOW_MS;
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
const linePath = (suffix: string) => apiPath('bpp', `bank/lines/${suffix}`);
const idem = (key: string) => ({ headers: { 'Idempotency-Key': key } });

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

  lines: (id: string, page: number, pageSize: number, tab?: ReconTab) =>
    api.get<RegistryPage<StatementLine>>(path(`${id}/lines`), {
      params: { page, page_size: pageSize, ...(tab ? { tab } : {}) },
    }).then((r) => r.data),

  /** «Сверить» — автосверка загрузки «Загружена». */
  reconcile: (key: string, id: string) =>
    api.post<BankImportCard>(path(`${id}/reconcile`), {}, idem(key)).then((r) => r.data),

  impact: (id: string) => api.get<CancelImpact>(path(`${id}/impact`)).then((r) => r.data),

  cancel: (key: string, id: string, comment: string) =>
    api.post<BankImportCard>(path(`${id}/cancel`), { comment }, idem(key)).then((r) => r.data),

  /**
   * «Выгрузить результат» — xlsx `Сверка ВП-….xlsx`. Общий помощник добавляет
   * `?format=xlsx`; ручка `export` параметр не читает и всегда отдаёт xlsx.
   */
  exportResult: (id: string, number: string): Promise<ExportOutcome> =>
    exportRegistry(path(`${id}/export`), {}, `Сверка ${number}`),

  candidates: (lineId: string, q: string) =>
    api.get<{ items: MatchCandidate[] }>(linePath(`${lineId}/candidates`), {
      params: q ? { q } : {},
    }).then((r) => r.data.items),

  match: (key: string, lineId: string, allocations: Allocation[], comment = '') =>
    api.post<StatementLine>(linePath(`${lineId}/match`), { allocations, comment }, idem(key))
      .then((r) => r.data),

  confirm: (key: string, lineId: string, comment: string) =>
    api.post<StatementLine>(linePath(`${lineId}/confirm`), { comment }, idem(key)).then((r) => r.data),

  cancelMatch: (key: string, lineId: string, comment: string) =>
    api.post<StatementLine>(linePath(`${lineId}/cancel-match`), { comment }, idem(key))
      .then((r) => r.data),

  exclude: (key: string, lineId: string, comment: string) =>
    api.post<StatementLine>(linePath(`${lineId}/exclude`), { comment }, idem(key)).then((r) => r.data),
};

export const bankImportKey = (id: string) => ['bpp', 'bank', 'import', id] as const;

/**
 * После загрузки и после каждого действия сверки: карточка и строки
 * загрузки, реестры (счета меняют статус сверки) и дашборд «Оплаты».
 */
export function invalidateRecon(queryClient: QueryClient, importId?: string): Promise<unknown> {
  return Promise.all([
    importId ? queryClient.invalidateQueries({ queryKey: bankImportKey(importId) }) : null,
    queryClient.invalidateQueries({ queryKey: ['bpp', 'registry'] }),
    queryClient.invalidateQueries({ queryKey: ['bpp', 'invoice'] }),
    queryClient.invalidateQueries({ queryKey: DASHBOARD_KEY }),
  ]);
}
