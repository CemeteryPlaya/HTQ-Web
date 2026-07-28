/**
 * types/contracts.ts
 * Типы домена «Бюджеты / Реестр контрактов / Договоры» (backend: apps.contracts).
 *
 * Денежные суммы приходят СТРОКАМИ, а не числами: на бэкенде это
 * Decimal(18,2), и разбор их в JS-number терял бы копейки на суммах
 * договоров. Форматирование и арифметика — только над строками/Decimal-ом
 * на сервере, здесь они просто переносятся.
 */

export interface Country {
  id: number;
  name: string;
  iso_code: string;
}

export interface Program {
  id: number;
  name: string;
  /** «Статья расходов» — живёт в той же строке, что и программа. */
  expense_item: string;
  code: string;
  is_active: boolean;
}

export interface Administrator {
  id: number;
  full_name: string;
  country_id: number;
  project_name: string;
  user_id: number | null;
  is_active: boolean;
}

export type BudgetStatus = 'active' | 'closed';

export interface Budget {
  id: number;
  administrator_id: number;
  administrator_name: string;
  program_id: number;
  program_name: string;
  expense_item: string;
  amount: string;
  currency: string;
  period_year: number;
  status: BudgetStatus;
  note: string;
  /** Вычисляется на бэкенде из договоров — колонки в БД нет. */
  committed: string;
  /** amount − committed. Тоже вычисляется, не хранится. */
  remaining: string;
  created_at: string;
  updated_at: string;
}

export type CounterpartyStatus = 'active' | 'inactive' | 'blocked';

export interface Counterparty {
  id: number;
  bin_iin: string;
  name: string;
  country_id: number;
  vat: string;
  contacts: string;
  address: string;
  status: CounterpartyStatus;
  created_at: string;
  updated_at: string;
}

export type PaymentType = 'prepayment' | 'postpayment' | 'staged';

export type AgreementStatus =
  | 'draft'
  | 'on_review'
  | 'approved'
  | 'signed'
  | 'executed'
  | 'terminated';

export interface Agreement {
  id: number;
  number: string;
  name: string;
  budget_id: number;
  /** Разворачивается из бюджетной строки — на договоре такой колонки нет. */
  administrator_id: number;
  administrator_name: string;
  program_id: number;
  program_name: string;
  expense_item: string;
  period_year: number;
  counterparty_id: number;
  counterparty_name: string;
  counterparty_bin_iin: string;
  payment_type: PaymentType;
  amount: string;
  currency: string;
  file_id: string | null;
  signed_date: string | null;
  status: AgreementStatus;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Пара value/label из `GET /enums` — источник подписей для селектов. */
export interface EnumOption {
  value: string;
  label: string;
}

export interface ContractsEnums {
  agreement_status: EnumOption[];
  budget_status: EnumOption[];
  counterparty_status: EnumOption[];
  payment_type: EnumOption[];
  /** Из каких статусов договор занимает бюджет. */
  committing_statuses: AgreementStatus[];
  transitions: Record<AgreementStatus, AgreementStatus[]>;
}

// ─── Составная заявка на бюджет ──────────────────────────────────────────
//
// Форма заполняется целиком, вместе со справочниками: у каждой вложенной
// части либо `id` уже существующей записи, либо поля для её создания.
// Бэкенд разбирает это в одной транзакции (POST /budgets/full).

export interface CountryInput {
  id?: number;
  name?: string;
  iso_code?: string;
}

export interface AdministratorInput {
  id?: number;
  full_name?: string;
  project_name?: string;
  country?: CountryInput;
}

export interface ProgramInput {
  id?: number;
  name?: string;
  expense_item?: string;
  code?: string;
}

export interface BudgetFullCreatePayload {
  administrator: AdministratorInput;
  program: ProgramInput;
  amount: string;
  period_year: number;
  currency: string;
  note: string;
}
