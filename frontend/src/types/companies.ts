/**
 * Типы домена реестра компаний (`/api/companies/v1`).
 *
 * Соответствуют таблице «Контракт API» плана
 * docs/plans/2026-09-14-block-a-company-registry.md; расхождение чинится
 * правкой плана, а не подгонкой типов.
 */

export type CompanyKind = 'holding' | 'construction' | 'it' | 'service' | 'regional';
export type CompanyStatus = 'active' | 'archived';

export interface Company {
  id: number;
  slug: string;
  /**
   * Блок I.2: короткий адрес компании (`htq` вместо `hi-tech-qazaqstan`).
   * `null` — компания открывается по слагу.
   */
  subdomain?: string | null;
  name: string;
  kind: CompanyKind;
  status: CompanyStatus;
  country: string;
  parent_slug: string | null;
  /** Преемник компании, закрытой банкротством; `null` — преемника нет. */
  successor_slug?: string | null;
  archived_at: string | null;
  /**
   * Задача 7 блока C, решение заказчика 4: показывать ли дочерней компании
   * список держателей прав из вышестоящих компаний. Настройка компании —
   * правит её только платформенный администратор (`PATCH companies/<slug>`,
   * тот же гейт, что у остальных полей).
   */
  show_external_holders: boolean;
  /**
   * Решение 19.10: где ведётся БЗО компании (слаг); `null` — у неё самой.
   * Запросы БЗО с её поддомена работают в данных той компании.
   */
  bpp_data_company_slug?: string | null;
}

/** Ответ `POST companies/<slug>/bankrupt` (и предпросмотра `dry_run`). */
export interface BankruptResult {
  company: Company;
  successor: Company;
  members_total: number;
  members_granted: number;
  members_already: number;
  archived: boolean;
  dry_run: boolean;
}

export interface CompanyTreeNode {
  slug: string;
  name: string;
  kind: CompanyKind;
  status: CompanyStatus;
  country: string;
  children: CompanyTreeNode[];
}

export interface MyCompany {
  slug: string;
  /** Короткий адрес; `null` — адрес по слагу. */
  subdomain?: string | null;
  name: string;
  kind: CompanyKind;
  is_default: boolean;
  is_current: boolean;
  /** Компания в архиве — только чтение; приходит только суперпользователю. */
  is_archived?: boolean;
  /** Решение 19.10: где ведётся БЗО этой компании — для плашки в разделе БЗО. */
  bpp_data_company_slug?: string | null;
  bpp_data_company_name?: string | null;
}

/**
 * `parent_slug: null` — «без родителя»; отсутствие ключа — «не трогать».
 * `subdomain: ''` или `null` — снять короткий адрес (компания вернётся на
 * адрес по слагу); отсутствие ключа — «не трогать».
 */
export interface CompanyPatch {
  name?: string;
  kind?: CompanyKind;
  country?: string;
  parent_slug?: string | null;
  show_external_holders?: boolean;
  subdomain?: string | null;
  /** Где вести БЗО: слаг компании; `''`/`null` — у себя; нет ключа — не трогать. */
  bpp_data_company_slug?: string | null;
}

export interface CompanyModule {
  app_label: string;
  enabled: boolean;
  message: string;
  is_core: boolean;
  /** Родительский модуль подмодуля (`apps.core.models.KNOWN_SUBMODULES`); null — модуль. */
  parent?: string | null;
}

export interface CompanyMembership {
  user_id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  is_default: boolean;
  /**
   * Решение 19.10: участник без входа числится в компании (роли, уведомления,
   * выбор сотрудника), но войти на её поддомен не может.
   */
  login_allowed?: boolean;
}

/** Уровень модуля — то же множество, что `AccessLevel` в `src/types/access.ts`. */
export interface ExternalHolderModule {
  module: string;
  level: string;
}

/**
 * Строка `GET companies/<slug>/external-holders` (задача 7 блока C). Ровно
 * четыре поля — раскрытие данных сотрудника холдинга дочерней компании
 * намеренно ограничено ими на бэкенде; лишнего здесь не бывает.
 */
export interface ExternalHolder {
  full_name: string;
  home_company: string;
  position: string;
  modules: ExternalHolderModule[];
}

export const COMPANY_KIND_LABELS: Record<CompanyKind, string> = {
  holding: 'Холдинг',
  construction: 'Строительная',
  it: 'IT-компания',
  service: 'Сервисная',
  regional: 'Региональная (устар.)',
};
