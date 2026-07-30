/**
 * types/contracts.ts
 * Типы домена «Бюджеты / Реестр контрагентов / Договоры» (backend: apps.contracts).
 *
 * Денежные суммы приходят СТРОКАМИ, а не числами: на бэкенде это
 * Decimal(18,2), и разбор их в JS-number терял бы копейки на суммах
 * договоров. Форматирование и арифметика — только над строками/Decimal-ом
 * на сервере, здесь они просто переносятся.
 */

import type { ApprovalState } from './signoff';

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
  /**
   * Готовая подпись «код название» (без кода — просто название). Собирает
   * бэкенд, чтобы формат не расползался; `program_name` в карточках бюджета
   * и договора — она же.
   */
  display_name: string;
  is_active: boolean;
}

export interface Administrator {
  id: number;
  country_id: number;
  /** Название страны — подпись записи собирается из проекта и страны. */
  country_name: string;
  project_name: string;
  /** Готовая подпись «проект страна». Собирает бэкенд, чтобы формат жил в одном месте. */
  display_name: string;
  user_id: number | null;
  is_active: boolean;
}

export type BudgetStatus = 'active' | 'closed';

/**
 * Строка бюджета ВНУТРИ его карточки: программа и выделенная ей сумма.
 *
 * Года, валюты и администратора здесь нет — они написаны на самом бюджете.
 * Именно на строку ссылается договор: деньги выделены программе.
 */
export interface BudgetLine {
  id: number;
  budget_id: number;
  program_id: number;
  /** Подпись «код название» — собирает бэкенд. */
  program_name: string;
  expense_item: string;
  amount: string;
  note: string;
  /** Вычисляется на бэкенде из договоров строки — колонки в БД нет. */
  committed: string;
  /** amount − committed. Тоже вычисляется, не хранится. */
  remaining: string;
}

/**
 * Бюджет проекта на год — КОНТЕЙНЕР строк, а не сумма.
 *
 * `allocated` — сумма строк, а не хранимое поле: см. докстринг
 * `services/budget_calc.py` на бэкенде. Согласуется бюджет целиком,
 * поэтому `approval_state` живёт здесь, а не на строке.
 */
export interface Budget {
  id: number;
  administrator_id: number;
  administrator_name: string;
  period_year: number;
  currency: string;
  status: BudgetStatus;
  /**
   * Вторая, НЕЗАВИСИМАЯ ось состояния — место записи в маршруте
   * согласования (примесь `signoff.Approvable`). `status` — жизненный цикл
   * самой записи, и путать их нельзя: отклонённый бюджет не «закрывается»,
   * его как раз собираются переделать и отправить снова.
   */
  approval_state: ApprovalState;
  note: string;
  /** Сумма строк. Вычисляется, не хранится. */
  allocated: string;
  committed: string;
  remaining: string;
  lines: BudgetLine[];
  created_at: string;
  updated_at: string;
}

/**
 * Строка ВНЕ своей карточки — с развёрнутым контекстом бюджета.
 *
 * Это то, что читает форма договора: там выбирают программу, из которой
 * берутся деньги, и ей нужны администратор, год и валюта рядом со строкой.
 */
export interface BudgetLineFlat extends BudgetLine {
  administrator_id: number;
  administrator_name: string;
  period_year: number;
  currency: string;
  /** Статус и согласование — РОДИТЕЛЬСКОГО бюджета: своих у строки нет. */
  budget_status: BudgetStatus;
  approval_state: ApprovalState;
}

export type CounterpartyStatus = 'active' | 'inactive' | 'blocked';

export interface Counterparty {
  id: number;
  bin_iin: string;
  name: string;
  country_id: number;
  /** Признак плательщика НДС — «с НДС / без НДС», не ставка и не номер свидетельства. */
  vat: boolean;
  /** Словесная форма признака, с бэкенда: «с НДС» / «без НДС». */
  vat_label: string;
  contacts: string;
  address: string;
  status: CounterpartyStatus;
  /** Ось согласования — отдельно от `status`. См. Budget.approval_state. */
  approval_state: ApprovalState;
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
  /** На что договор ссылается на самом деле — на СТРОКУ бюджета. */
  budget_line_id: number;
  /** Родительский бюджет строки — для ссылки на его карточку. */
  budget_id: number;
  /** Разворачивается из строки бюджета — на договоре такой колонки нет. */
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
  /**
   * Единственный из трёх, где согласование имеет доменное последствие: оно
   * двигает `status` по своей же таблице переходов (`draft → on_review` на
   * отправку, `→ approved` на согласование, отказ и отзыв возвращают в
   * `draft`). Оси всё равно разные — договор бывает согласован по маршруту
   * и расторгнут по существу.
   */
  approval_state: ApprovalState;
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
  project_name?: string;
  country?: CountryInput;
}

export interface ProgramInput {
  id?: number;
  name?: string;
  expense_item?: string;
  code?: string;
}

export interface CounterpartyFullCreatePayload {
  bin_iin: string;
  name: string;
  country: CountryInput;
  vat: boolean;
  contacts: string;
  address: string;
  status?: CounterpartyStatus;
}

/** Одна строка заявки: программа и её собственная сумма. */
export interface BudgetProgramLine {
  program: ProgramInput;
  amount: string;
  note: string;
}

export interface BudgetFullCreatePayload {
  administrator: AdministratorInput;
  /** По строке на программу — бюджет создаётся со всеми или ни с одной. */
  programs: BudgetProgramLine[];
  period_year: number;
  currency: string;
  note: string;
}
