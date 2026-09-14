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
  name: string;
  kind: CompanyKind;
  status: CompanyStatus;
  country: string;
  parent_slug: string | null;
  archived_at: string | null;
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
  name: string;
  kind: CompanyKind;
  is_default: boolean;
  is_current: boolean;
}

/** `parent_slug: null` — «без родителя»; отсутствие ключа — «не трогать». */
export interface CompanyPatch {
  name?: string;
  kind?: CompanyKind;
  country?: string;
  parent_slug?: string | null;
}

export interface CompanyModule {
  app_label: string;
  enabled: boolean;
  message: string;
  is_core: boolean;
}

export interface CompanyMembership {
  user_id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  is_default: boolean;
}

export const COMPANY_KIND_LABELS: Record<CompanyKind, string> = {
  holding: 'Холдинг',
  construction: 'Строительная',
  it: 'IT-компания',
  service: 'Сервисная',
  regional: 'Региональная (устар.)',
};
