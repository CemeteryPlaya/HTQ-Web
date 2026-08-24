import React, { useState, useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { BackToProfile } from '@/components/BackToProfile';
import { type HRLevel, useHRLevel } from '@/hooks/useHRLevel';
import { Input } from '@/components/ui/input';
import { HRQuickActionsBar } from './HRQuickActionsBar';
import { cn } from '@/lib/utils';
import {
  Users,
  Building2,
  Briefcase,
  FileText,
  Clock,
  ClipboardList,
  History,
  Handshake,
  Archive,
  Link2,
  Network,
  IdCard,
  CalendarDays,
  Wallet,
  Search,
  X,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react';

type HRNavItem = {
  to: string;
  icon: LucideIcon;
  labelKey: string;
  levels: Array<'junior' | 'middle' | 'senior' | 'lead'>;
  category: 'people' | 'org' | 'tracking' | 'admin';
};

const navItems: HRNavItem[] = [
  // ── Персонал
  { to: '/hr/employees', icon: Users, labelKey: 'hr.nav.employees', levels: ['junior', 'middle', 'senior', 'lead'], category: 'people' },
  { to: '/hr/accounts', icon: IdCard, labelKey: 'hr.nav.accounts', levels: ['lead'], category: 'people' },
  { to: '/hr/recruitment', icon: ClipboardList, labelKey: 'hr.nav.recruitment', levels: ['middle', 'senior', 'lead'], category: 'people' },
  { to: '/hr/archive', icon: Archive, labelKey: 'hr.nav.archive', levels: ['senior', 'lead'], category: 'people' },

  // ── Организация
  { to: '/hr/departments', icon: Building2, labelKey: 'hr.nav.structure', levels: ['middle', 'senior', 'lead'], category: 'org' },
  { to: '/hr/positions', icon: Briefcase, labelKey: 'hr.nav.positions', levels: ['middle', 'senior', 'lead'], category: 'org' },
  { to: '/hr/org-chart', icon: Network, labelKey: 'hr.nav.orgChart', levels: ['junior', 'middle', 'senior', 'lead'], category: 'org' },
  { to: '/hr/pmo', icon: Handshake, labelKey: 'hr.nav.pmo', levels: ['senior', 'lead'], category: 'org' },

  // ── Учёт и Время
  { to: '/hr/time-tracking', icon: Clock, labelKey: 'hr.nav.timeTracking', levels: ['middle', 'senior', 'lead'], category: 'tracking' },
  { to: '/hr/production-calendar', icon: CalendarDays, labelKey: 'hr.nav.productionCalendar', levels: ['junior', 'middle', 'senior', 'lead'], category: 'tracking' },
  { to: '/hr/staffing', icon: Wallet, labelKey: 'hr.nav.staffing', levels: ['senior', 'lead'], category: 'tracking' },
  { to: '/hr/documents', icon: FileText, labelKey: 'hr.nav.documents', levels: ['junior', 'middle', 'senior', 'lead'], category: 'tracking' },

  // ── История и Сервис
  { to: '/hr/share-links', icon: Link2, labelKey: 'hr.nav.shareLinks', levels: ['senior', 'lead'], category: 'admin' },
  { to: '/hr/history', icon: History, labelKey: 'hr.nav.history', levels: ['senior', 'lead'], category: 'admin' },
];

const categoryTitles: Record<string, string> = {
  people: 'hr.nav.groups.people',
  org: 'hr.nav.groups.org',
  tracking: 'hr.nav.groups.tracking',
  admin: 'hr.nav.groups.admin',
};

interface Props {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const HRLayout: React.FC<Props> = ({ title, subtitle, children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const { level } = useHRLevel();
  const [searchQuery, setSearchQuery] = useState('');

  const visibleNavItems = useMemo(() => {
    return navItems.filter((item) => level && item.levels.includes(level as Exclude<HRLevel, null>));
  }, [level]);

  const filteredNavItems = useMemo(() => {
    if (!searchQuery.trim()) return visibleNavItems;
    const q = searchQuery.toLowerCase();
    return visibleNavItems.filter((item) => {
      const label = t(item.labelKey).toLowerCase();
      return label.includes(q);
    });
  }, [visibleNavItems, searchQuery, t]);

  const groupedNav = useMemo(() => {
    const groups: Record<string, HRNavItem[]> = {
      people: [],
      org: [],
      tracking: [],
      admin: [],
    };
    filteredNavItems.forEach((item) => {
      if (groups[item.category]) {
        groups[item.category].push(item);
      }
    });
    return groups;
  }, [filteredNavItems]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1">
        <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          {/* Header & Back link */}
          <div className="mb-6 flex flex-col gap-3">
            <BackToProfile className="mb-0 text-xs" />

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.25em] text-primary/80">
                  {t('hr.title', 'HR Модуль')}
                </div>
                <h1 className="text-3xl font-extrabold tracking-tight text-foreground">{title}</h1>
                {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
              </div>
            </div>
          </div>

          {/* Mobile Horizontal Navigation */}
          <div className="mb-6 flex items-center gap-1.5 overflow-x-auto rounded-2xl border bg-card/80 p-2 shadow-2xs lg:hidden scrollbar-none">
            {visibleNavItems.map((item) => {
              const active = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    'flex min-h-[44px] items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold whitespace-nowrap transition-all',
                    active
                      ? 'bg-primary text-primary-foreground shadow-2xs'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                >
                  <item.icon className="h-4 w-4 shrink-0" />
                  {t(item.labelKey)}
                </Link>
              );
            })}
          </div>

          <div className="grid gap-8 lg:grid-cols-[260px_1fr]">
            {/* Desktop Sidebar Navigation */}
            <aside className="hidden lg:block">
              <div className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto rounded-2xl border bg-card p-3.5 shadow-2xs space-y-4 scrollbar-thin">
                {/* Search Box */}
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                  <Input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('hr.nav.searchPlaceholder')}
                    className="h-8.5 pl-8 pr-7 text-xs bg-muted/40 border-muted focus-visible:bg-background rounded-lg transition-colors"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 top-2 text-muted-foreground hover:text-foreground p-0.5 rounded-sm"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>

                {filteredNavItems.length === 0 && (
                  <div className="py-6 text-center text-xs text-muted-foreground">
                    {t('common.nothingFound')}
                  </div>
                )}

                {/* Categorized Menu */}
                {Object.entries(groupedNav).map(([catKey, items]) => {
                  if (items.length === 0) return null;
                  return (
                    <div key={catKey} className="space-y-1">
                      <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">
                        {categoryTitles[catKey] || catKey}
                      </div>
                      <nav className="flex flex-col gap-0.5">
                        {items.map((item) => {
                          const active = location.pathname === item.to;
                          return (
                            <Link
                              key={item.to}
                              to={item.to}
                              className={cn(
                                'group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150',
                                'text-muted-foreground hover:bg-accent/80 hover:text-foreground',
                                active && 'bg-primary/10 text-primary font-semibold border-l-2 border-primary pl-2.5 shadow-2xs'
                              )}
                            >
                              <item.icon className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110" />
                              <span className="flex-1 truncate">{t(item.labelKey)}</span>
                              {active && <ChevronRight className="h-3.5 w-3.5 opacity-60 shrink-0" />}
                            </Link>
                          );
                        })}
                      </nav>
                    </div>
                  );
                })}
              </div>
            </aside>

            {/* Main HR Page Content */}
            <div className="min-w-0 space-y-6">
              <HRQuickActionsBar />
              {children}
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default HRLayout;
