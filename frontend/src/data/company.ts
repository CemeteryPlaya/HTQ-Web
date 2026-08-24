// Единый источник данных компании для главной страницы.
// Цифры раньше дублировались в HeroSection / StatsSection / MissionSection и
// успели разойтись между собой (722 МВт против 160 МВт, 15+ проектов против 10).
// Держим их здесь в одном экземпляре; локализуются только подписи и единицы.

import { projects } from './projects';

export const companyStats = {
  /** Лет опыта на рынке. */
  years: 10,
  /** Количество проектов — выводится из данных, поэтому разойтись не может. */
  projects: projects.length,
  /** МВт, в проектах которых участвовала компания. */
  totalMw: 160,
  /** МВт, построенных по полному циклу в Казахстане. */
  fullCycleMw: 90,
} as const;

/** «160» + локализованная единица → «160 МВт» / «160 MW». */
export const formatMw = (value: number, unit: string) => `${value} ${unit}`;

export interface SocialLink {
  /** Название площадки — бренды не переводятся, поэтому не i18n-ключ. */
  name: string;
  href: string;
}

export interface LegalLink {
  /** i18n-ключ подписи, например ``footer.privacy``. */
  labelKey: string;
  href: string;
}

/** Соцсети. Пусто, пока нет реальных URL — Footer скрывает блок при пустом массиве. */
export const socialLinks: SocialLink[] = [];

/** Политика/условия. Пусто, пока нет страниц /privacy и /terms. */
export const legalLinks: LegalLink[] = [];
