/**
 * Клиент «KPI снабжения» (`/api/bpp/v1/kpi/…`; ТЗ §12.5–12.6, R-01; сервер —
 * `apps/bpp/views_kpi.py`, `services/alternatives/report.py`).
 *
 * - Фильтры отчёта — период по дате выбора, покупатель (СН/ПМ, целое), проект,
 *   статья; живут в адресе страницы. У записей ещё `status`, `own_document`.
 * - Деньги и доля — строки-десятичные; на экран только через `formatMoney`.
 *   `share_pct: null` — «подано» ноль, доли нет («—»).
 * - Идемпотентное аннулирование — заголовок `Idempotency-Key` от диалога.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import { exportRegistry, type ExportOutcome } from '../core/registryExport';

export type Money = string;

export const KPI_BASE = '/bpp/kpi';
export const kpiRecordHref = (id: string) => `${KPI_BASE}/${id}`;

export type KpiStatus = 'preliminary' | 'confirmed' | 'annulled';

export interface KpiFilters {
  period_from: string;
  period_to: string;
  buyer_id: string;
  project_id: string;
  article_id: string;
}

export const FILTER_KEYS = [
  'period_from', 'period_to', 'buyer_id', 'project_id', 'article_id',
] as const satisfies readonly (keyof KpiFilters)[];

export const EMPTY_FILTERS: KpiFilters = {
  period_from: '', period_to: '', buyer_id: '', project_id: '', article_id: '',
};

export function filtersFromSearch(params: URLSearchParams): KpiFilters {
  const out = { ...EMPTY_FILTERS };
  for (const key of FILTER_KEYS) out[key] = params.get(key) ?? '';
  return out;
}

/** Только заданные фильтры — параметры запроса. */
export function filterParams(filters: KpiFilters): Record<string, string> {
  return Object.fromEntries(FILTER_KEYS.filter((key) => filters[key]).map((key) => [key, filters[key]]));
}

/** Дополнительный отбор записей, с которым открывается список из ячейки. */
export interface RecordsSelection {
  title: string;
  buyer_id?: string;
  status?: KpiStatus;
  own_document?: '1';
}

export interface KpiReportRow {
  buyer_id: number | null;
  name: string | null;
  role: string;
  role_label: string;
  submitted: number;
  selected: number;
  confirmed: number;
  share_pct: string | null;
  saving: Money;
  overspend: Money;
  own_document_count: number;
}

export interface KpiReport {
  rows: KpiReportRow[];
  total: KpiReportRow;
  filters: Record<string, string | number | null>;
}

export interface KpiRecord {
  id: string;
  version: number;
  offer_id: string;
  offer_number: string;
  /** `/bpp/alternatives/<id>` — экран альтернатив (задача 6). */
  offer_url: string;
  buyer_id: number;
  buyer_name: string;
  buyer_role: string;
  own_document: boolean;
  project_id: string;
  article_id: string;
  source_type: string;
  source_id: string;
  source_number: string;
  source_url: string;
  source_amount_kzt: Money;
  result_type: string;
  result_id: string;
  result_number: string;
  result_url: string;
  result_amount_kzt: Money | null;
  saving_amount: Money | null;
  saving_pct: string | null;
  status: KpiStatus;
  status_label: string;
  status_changed_at: string | null;
  selected_at: string;
  selected_by_id: number | null;
  annul_comment: string;
  annulled_by_id: number | null;
}

export interface KpiRecordsPage {
  items: KpiRecord[];
  total: number;
}

export const KPI_KEY = ['bpp', 'kpi'] as const;
export const kpiKeys = {
  all: KPI_KEY,
  /** Отчёт по фильтрам; список покупателей берётся из него же без `buyer_id` — тот же ключ, один запрос. */
  report: (filters: KpiFilters) => [...KPI_KEY, 'report', filterParams(filters)] as const,
  records: (params: Record<string, string>) => [...KPI_KEY, 'records', params] as const,
  card: (id: string) => [...KPI_KEY, 'card', id] as const,
};

const path = (suffix: string) => apiPath('bpp', `kpi/${suffix}`);

export const kpiApi = {
  report: (filters: KpiFilters) =>
    api.get<KpiReport>(path('report'), { params: filterParams(filters) }).then((r) => r.data),
  records: (params: Record<string, string>) =>
    api.get<KpiRecordsPage>(path('records'), { params }).then((r) => r.data),
  card: (id: string) => api.get<KpiRecord>(path(`records/${id}`)).then((r) => r.data),
  annul: (id: string, version: number, comment: string, key: string) =>
    api.post<KpiRecord>(path(`records/${id}/annul`), { version, comment },
      { headers: { 'Idempotency-Key': key } }).then((r) => r.data),
  exportReport: (filters: KpiFilters): Promise<ExportOutcome> =>
    exportRegistry(path('report/export'), filterParams(filters), 'KPI снабжения'),
};
