/**
 * Типы читателей сводки холдинга (блок H, задача 5).
 *
 * `GET /api/hr/v1/holding/headcount` и `GET /api/tasks/v1/holding/projects` —
 * обе ручки готовы (задачи 3 и 4), это только форма их ответа для клиента.
 * Списки компаний у двух ручек могут не совпадать — компания без единой
 * строки в домене в его сводку не попадает; страница сводит их по
 * `company_slug` сама (см. `GroupSummary.tsx`).
 */

export interface HoldingHeadcountRow {
  company_slug: string;
  /**
   * Может совпасть со слагом — так ручка честно показывает компанию,
   * которой уже нет в реестре (осиротевшая строка после неудачного отката
   * `company_create`, см. CLAUDE.md). Отдельной обработки не требует.
   */
  company_name: string;
  employees_active: number;
  employees_total: number;
  departments_active: number;
  positions_active: number;
  staffing_headcount: number;
  staffing_payroll: number;
}

export interface HoldingHeadcountTotals {
  employees_active: number;
  employees_total: number;
  staffing_headcount: number;
  staffing_payroll: number;
}

export interface HoldingHeadcount {
  companies: HoldingHeadcountRow[];
  totals: HoldingHeadcountTotals;
}

export interface HoldingProjectsRow {
  company_slug: string;
  company_name: string;
  projects_active: number;
  sites_active: number;
  tasks_open: number;
  tasks_overdue: number;
  /** `null` — у компании нет ни одного отчёта. Это НЕ сегодня и НЕ ноль. */
  reports_last_date: string | null;
}

export interface HoldingProjectsTotals {
  projects_active: number;
  sites_active: number;
  tasks_open: number;
  tasks_overdue: number;
}

export interface HoldingProjects {
  companies: HoldingProjectsRow[];
  totals: HoldingProjectsTotals;
}
