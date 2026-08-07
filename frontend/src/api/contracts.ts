/**
 * api/contracts.ts
 * Клиент домена «Бюджеты / Реестр контрагентов / Договоры».
 *
 * Пути без завершающего слэша — бэкенд регистрирует оба написания
 * (APPEND_SLASH=False), но у этой аппки фронтенд первый потребитель, так
 * что достаточно придерживаться одного стиля.
 */

import api from './client';
import { apiPath } from './endpoints';
import type { ApprovalProcess } from '@/types/signoff';
import type {
  Administrator,
  Agreement,
  AgreementStatus,
  Budget,
  BudgetFullCreatePayload,
  BudgetLineFlat,
  ContractsEnums,
  Counterparty,
  CounterpartyFullCreatePayload,
  Country,
  Invoice,
  InvoiceStatus,
  Program,
} from '@/types/contracts';

const path = (suffix: string) => apiPath('contracts', suffix);

export interface BudgetListParams {
  administrator_id?: number;
  period_year?: number;
  status?: string;
  approval_state?: string;
}

export interface AgreementListParams {
  /** По бюджету ЦЕЛИКОМ — все его программы. */
  budget_id?: number;
  /** По одной программе. */
  budget_line_id?: number;
  counterparty_id?: number;
  administrator_id?: number;
  program_id?: number;
  period_year?: number;
  status?: string;
}

/** Те же фильтры, что у договоров (у бэкенда это тот же набор параметров). */
export type InvoiceListParams = AgreementListParams;

/**
 * Отправка на согласование живёт ЗДЕСЬ, а не в api/signoff.ts, и это не
 * случайность. У signoff есть общий `POST /processes`, но он принимает
 * `subject_id` любого типа и потому обходит доменные права мимо их
 * владельца — на бэкенде он оставлен операторским. Штатный путь — эндпоинт
 * предметной аппки, которая только и знает, кому её объект разрешено
 * отправлять.
 *
 * Ответ — карточка ПРОЦЕССА (201), а не отправленного объекта.
 */
export const contractsApi = {
  // ─── Справочники ───────────────────────────────────────────────────────
  getEnums: () => api.get<ContractsEnums>(path('enums')),

  listCountries: () => api.get<Country[]>(path('countries')),
  createCountry: (data: { name: string; iso_code?: string }) =>
    api.post<Country>(path('countries'), data),

  listPrograms: (params?: { is_active?: boolean }) =>
    api.get<Program[]>(path('programs'), { params }),
  createProgram: (data: { name: string; expense_item: string; code?: string }) =>
    api.post<Program>(path('programs'), data),

  listAdministrators: (params?: { is_active?: boolean; country_id?: number }) =>
    api.get<Administrator[]>(path('administrators'), { params }),
  createAdministrator: (data: { country_id: number; project_name: string }) =>
    api.post<Administrator>(path('administrators'), data),

  // ─── Бюджеты ───────────────────────────────────────────────────────────
  listBudgets: (params?: BudgetListParams) =>
    api.get<Budget[]>(path('budgets'), { params }),
  getBudget: (id: number) => api.get<Budget>(path(`budgets/${id}`)),
  /**
   * Заявка на бюджет вместе со справочниками — одним запросом, одной
   * транзакцией на бэкенде. Именно это шлёт форма: разбивать на отдельные
   * POST'ы из браузера нельзя, упавший третий оставил бы наполовину
   * заведённые справочники.
   *
   * Отдаёт ОДИН бюджет со вложенными строками — по одной на программу.
   */
  createBudgetFull: (payload: BudgetFullCreatePayload) =>
    api.post<Budget>(path('budgets/full'), payload),
  /**
   * Плоский список строк ВСЕХ бюджетов — то, из чего форма договора строит
   * каскад «администратор → программа → год». Отдельный ресурс, а не разбор
   * вложенных `lines` из `listBudgets`: строке здесь нужен развёрнутый
   * контекст бюджета и остаток.
   */
  listBudgetLines: (params?: {
    budget_id?: number;
    administrator_id?: number;
    program_id?: number;
    period_year?: number;
    approval_state?: string;
  }) => api.get<BudgetLineFlat[]>(path('budget-lines'), { params }),
  /** Дополнить уже заведённый бюджет программой. Отдаёт бюджет целиком. */
  addBudgetLine: (budgetId: number, data: { program_id: number; amount: string; note?: string }) =>
    api.post<Budget>(path(`budgets/${budgetId}/lines`), data),
  getBudgetLine: (lineId: number) =>
    api.get<BudgetLineFlat>(path(`budget-lines/${lineId}`)),
  updateBudgetLine: (lineId: number, data: Partial<{ amount: string; note: string }>) =>
    api.patch<BudgetLineFlat>(path(`budget-lines/${lineId}`), data),
  deleteBudgetLine: (lineId: number) => api.delete(path(`budget-lines/${lineId}`)),
  updateBudget: (id: number, data: Partial<Budget>) =>
    api.patch<Budget>(path(`budgets/${id}`), data),
  deleteBudget: (id: number) => api.delete(path(`budgets/${id}`)),
  listBudgetAgreements: (id: number) =>
    api.get<Agreement[]>(path(`budgets/${id}/agreements`)),
  submitBudget: (id: number) =>
    api.post<ApprovalProcess>(path(`budgets/${id}/submit`)),

  // ─── Реестр контрагентов ───────────────────────────────────────────────
  listCounterparties: (params?: { search?: string; status?: string }) =>
    api.get<Counterparty[]>(path('counterparties'), { params }),
  getCounterparty: (id: number) =>
    api.get<Counterparty>(path(`counterparties/${id}`)),
  createCounterparty: (data: {
    bin_iin: string;
    name: string;
    country_id: number;
    vat?: boolean;
    contact_name?: string;
    phone?: string;
    email?: string;
    address?: string;
  }) => api.post<Counterparty>(path('counterparties'), data),
  /**
   * Карточка контрагента вместе со страной — одним запросом, одной
   * транзакцией. Это шлёт форма: страну в ней можно вписать новой, и
   * заводить её отдельным вызовом значило бы оставить её висеть, если
   * следом упадёт создание самого контрагента (чаще всего — дубль БИН).
   */
  createCounterpartyFull: (payload: CounterpartyFullCreatePayload) =>
    api.post<Counterparty>(path('counterparties/full'), payload),
  updateCounterparty: (id: number, data: Partial<Counterparty>) =>
    api.patch<Counterparty>(path(`counterparties/${id}`), data),
  submitCounterparty: (id: number) =>
    api.post<ApprovalProcess>(path(`counterparties/${id}/submit`)),

  // ─── Договоры ──────────────────────────────────────────────────────────
  listAgreements: (params?: AgreementListParams) =>
    api.get<Agreement[]>(path('agreements'), { params }),
  getAgreement: (id: number) => api.get<Agreement>(path(`agreements/${id}`)),
  createAgreement: (data: {
    number: string;
    name: string;
    /** Договор ссылается на СТРОКУ бюджета: деньги выделены программе. */
    budget_line_id: number;
    counterparty_id: number;
    amount: string;
    payment_type: string;
    currency?: string;
    signed_date?: string | null;
    status?: AgreementStatus;
  }) => api.post<Agreement>(path('agreements'), data),
  updateAgreement: (id: number, data: Record<string, unknown>) =>
    api.patch<Agreement>(path(`agreements/${id}`), data),
  /**
   * Только из черновика. Бэкенд перед запуском заново проверяет валюту,
   * справочники и лимит бюджета: `on_review` уже занимает бюджет, так что
   * проверять его ПОСЛЕ старта было бы поздно.
   */
  submitAgreement: (id: number) =>
    api.post<ApprovalProcess>(path(`agreements/${id}/submit`)),
  /** Единственный путь смены статуса — переход проверяется на бэкенде. */
  changeAgreementStatus: (id: number, status: AgreementStatus) =>
    api.post<Agreement>(path(`agreements/${id}/status`), { status }),
  uploadAgreementFile: (id: number, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<Agreement>(path(`agreements/${id}/file`), form);
  },
  getAgreementFileUrl: (id: number) =>
    api.get<{ url: string }>(path(`agreements/${id}/file-url`)),

  // ─── Счета на оплату (без договора) ────────────────────────────────────
  //
  // Устроены как договоры, но проще: без `number`, `payment_type`,
  // `signed_date`, `currency` (её снимает бэкенд со строки бюджета).
  // Согласование — то же, что у договора (`submitInvoice`), с одним отличием:
  // скан обязателен уже на отправке (счёт без договора и ЕСТЬ платёжный
  // документ), и его отсутствие бэкенд отобьёт 409-м.
  listInvoices: (params?: InvoiceListParams) =>
    api.get<Invoice[]>(path('invoices'), { params }),
  getInvoice: (id: number) => api.get<Invoice>(path(`invoices/${id}`)),
  submitInvoice: (id: number) =>
    api.post<ApprovalProcess>(path(`invoices/${id}/submit`)),
  createInvoice: (data: {
    name: string;
    /** Счёт ссылается на СТРОКУ бюджета: деньги выделены программе. */
    budget_line_id: number;
    counterparty_id: number;
    amount: string;
    note?: string;
  }) => api.post<Invoice>(path('invoices'), data),
  updateInvoice: (id: number, data: Record<string, unknown>) =>
    api.patch<Invoice>(path(`invoices/${id}`), data),
  /** Единственный путь смены статуса — переход проверяется на бэкенде. */
  changeInvoiceStatus: (id: number, status: InvoiceStatus) =>
    api.post<Invoice>(path(`invoices/${id}/status`), { status }),
  uploadInvoiceFile: (id: number, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<Invoice>(path(`invoices/${id}/file`), form);
  },
  getInvoiceFileUrl: (id: number) =>
    api.get<{ url: string }>(path(`invoices/${id}/file-url`)),
};
