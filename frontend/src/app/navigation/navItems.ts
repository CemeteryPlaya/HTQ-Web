/**
 * navItems — ЕДИНЫЙ источник разделов приложения для авторизованного
 * пользователя.
 *
 * ЗАЧЕМ. Раньше десктопный `Header` и мобильный `BottomNav` вели свои списки
 * независимо, и они разошлись: из шапки были недостижимы мессенджер, почта и
 * файлы, а с телефона — договоры и согласования. Любая новая вкладка требовала
 * правки в двух местах, и одно из них регулярно забывали. Теперь список один,
 * а компоненты лишь по-разному его показывают: шапка — первые `primary` ссылок
 * в ряд и остальные в меню «Ещё», нижняя панель — свои иконки.
 *
 * Порядок в массиве значим: он же задаёт, что попадёт в видимую часть шапки, а
 * что уедет под «Ещё». Ставить новый раздел в начало — осознанное решение, а не
 * деталь оформления.
 */
import {
  Calendar,
  CheckSquare,
  FileSignature,
  FileText,
  FolderOpen,
  Mail,
  MessageCircle,
  Newspaper,
  Stamp,
  Users,
  type LucideIcon,
} from 'lucide-react';

/** Какое право нужно, чтобы раздел был виден. */
export type NavRequirement = 'always' | 'editor' | 'hr' | 'tasks' | 'department';

export interface NavItem {
  /** Стабильный ключ для React и тестов. */
  id: string;
  href: string;
  icon: LucideIcon;
  /** i18n-ключ и запасная подпись (в проекте всюду `t(key, fallback)`). */
  labelKey: string;
  labelFallback: string;
  requires: NavRequirement;
  /** Показывать в мобильной нижней панели. */
  inBottomNav?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'tasks', href: '/tasks', icon: CheckSquare, labelKey: 'profile.sidebar.tasks', labelFallback: 'Задачи', requires: 'tasks', inBottomNav: true },
  { id: 'calendar', href: '/calendar', icon: Calendar, labelKey: 'hr.nav.calendar', labelFallback: 'Календарь', requires: 'always', inBottomNav: true },
  { id: 'messenger', href: '/messenger', icon: MessageCircle, labelKey: 'nav.messenger', labelFallback: 'Чаты', requires: 'always', inBottomNav: true },
  { id: 'email', href: '/email', icon: Mail, labelKey: 'nav.email', labelFallback: 'Почта', requires: 'always', inBottomNav: true },
  { id: 'contracts', href: '/contracts', icon: FileSignature, labelKey: 'contracts.nav.title', labelFallback: 'Договоры', requires: 'always' },
  { id: 'signoff', href: '/signoff', icon: Stamp, labelKey: 'signoff.nav.title', labelFallback: 'Согласования', requires: 'always' },
  { id: 'employees', href: '/hr/employees', icon: Users, labelKey: 'profile.sidebar.employees', labelFallback: 'Сотрудники', requires: 'hr', inBottomNav: true },
  { id: 'files', href: '/files', icon: FolderOpen, labelKey: 'nav.files', labelFallback: 'Файлы', requires: 'department', inBottomNav: true },
  { id: 'news', href: '/news', icon: Newspaper, labelKey: 'header.news', labelFallback: 'Новости', requires: 'always' },
  { id: 'manage-news', href: '/manage/news', icon: FileText, labelKey: 'profile.sidebar.manageNews', labelFallback: 'Упр. Новостями', requires: 'editor' },
];

export interface NavAbilities {
  isEditor: boolean;
  isHr: boolean;
  hasTasks: boolean;
  hasDepartment: boolean;
}

const allowed = (item: NavItem, a: NavAbilities): boolean => {
  switch (item.requires) {
    case 'always': return true;
    case 'editor': return a.isEditor;
    case 'hr': return a.isHr;
    case 'tasks': return a.hasTasks;
    case 'department': return a.hasDepartment;
    default: return false;
  }
};

/** Разделы, доступные пользователю, в каноническом порядке. */
export const visibleNavItems = (a: NavAbilities): NavItem[] =>
  NAV_ITEMS.filter((item) => allowed(item, a));

/** Разделы для мобильной нижней панели. */
export const bottomNavItems = (a: NavAbilities): NavItem[] =>
  visibleNavItems(a).filter((item) => item.inBottomNav);

/**
 * Делит список для шапки: первые `primaryCount` идут в ряд, остальные — в меню
 * «Ещё». Если «остаток» — ровно один пункт, меню ради него не заводим: одна
 * ссылка занимает меньше места, чем кнопка с выпадающим списком.
 */
export const splitForHeader = (
  items: NavItem[],
  primaryCount: number,
): { primary: NavItem[]; overflow: NavItem[] } => {
  if (items.length <= primaryCount + 1) return { primary: items, overflow: [] };
  return { primary: items.slice(0, primaryCount), overflow: items.slice(primaryCount) };
};
