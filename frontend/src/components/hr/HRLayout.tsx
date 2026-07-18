import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { type HRLevel, useHRLevel } from '@/hooks/useHRLevel';
import {
  Users,
  Building2,
  Briefcase,
  FileText,
  Clock,
  ClipboardList,
  ArrowLeft,
  History,
  Handshake,
  Archive,
  Link2,
  Network,
  SlidersHorizontal,
  IdCard,
  CalendarDays,
  Wallet
} from 'lucide-react';
const navItems = [
  { to: '/hr/employees', icon: Users, labelKey: 'hr.nav.employees', levels: ['junior', 'middle', 'senior', 'lead'] },
  { to: '/hr/accounts', icon: IdCard, labelKey: 'hr.nav.accounts', levels: ['lead'] },
  { to: '/hr/departments', icon: Building2, labelKey: 'hr.nav.structure', levels: ['middle', 'senior', 'lead'] },
  { to: '/hr/positions', icon: Briefcase, labelKey: 'hr.nav.positions', levels: ['middle', 'senior', 'lead'] },
  { to: '/admin/levels', icon: SlidersHorizontal, labelKey: 'hr.nav.levels', levels: ['lead'] },
  { to: '/hr/org-chart', icon: Network, labelKey: 'hr.nav.orgChart', levels: ['junior', 'middle', 'senior', 'lead'] },
  { to: '/hr/pmo', icon: Handshake, labelKey: 'hr.nav.pmo', levels: ['senior', 'lead'] },
  { to: '/hr/share-links', icon: Link2, labelKey: 'hr.nav.shareLinks', levels: ['senior', 'lead'] },
  { to: '/hr/time-tracking', icon: Clock, labelKey: 'hr.nav.timeTracking', levels: ['middle', 'senior', 'lead'] },
  { to: '/hr/recruitment', icon: ClipboardList, labelKey: 'hr.nav.recruitment', levels: ['middle', 'senior', 'lead'] },
  { to: '/hr/archive', icon: Archive, labelKey: 'hr.nav.archive', levels: ['senior', 'lead'] },
  { to: '/hr/documents', icon: FileText, labelKey: 'hr.nav.documents', levels: ['junior', 'middle', 'senior', 'lead'] },
  { to: '/hr/history', icon: History, labelKey: 'hr.nav.history', levels: ['senior', 'lead'] },
  { to: '/hr/production-calendar', icon: CalendarDays, labelKey: 'hr.nav.productionCalendar', levels: ['junior', 'middle', 'senior', 'lead'] },
  { to: '/hr/staffing', icon: Wallet, labelKey: 'hr.nav.staffing', levels: ['senior', 'lead'] },
];

interface Props {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const HRLayout: React.FC<Props> = ({ title, subtitle, children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const { level } = useHRLevel();
  const visibleNavItems = navItems.filter((item) => level && item.levels.includes(level as Exclude<HRLevel, null>));

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1">
        <div className="container mx-auto px-4 py-8">
          <div className="mb-6 flex flex-col gap-4">
            <Link
              to="/myprofile"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
              {t('hr.backToMain')}
            </Link>

            <div>
              <div className="text-sm uppercase tracking-[0.3em] text-muted-foreground">{t('hr.title')}</div>
              <h1 className="font-display text-3xl font-semibold text-foreground">{title}</h1>
              {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
            </div>
          </div>

          <div className="mb-6 flex items-center gap-2 overflow-x-auto rounded-xl border bg-card/70 p-2 shadow-[var(--shadow-soft)] lg:hidden">
            {visibleNavItems.map((item) => {
              const active = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${active
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    }`}
                >
                  <item.icon className="h-4 w-4" />
                  {t(item.labelKey)}
                </Link>
              );
            })}
          </div>

          <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
            <aside className="hidden lg:block">
              <div className="rounded-2xl border bg-card/70 p-4 shadow-[var(--shadow-soft)]">
                <div className="text-xs uppercase tracking-[0.25em] text-muted-foreground mb-3">
                  {t('hr.navigation')}
                </div>
                <nav className="flex flex-col gap-2">
                  {visibleNavItems.map((item) => {
                    const active = location.pathname === item.to;
                    return (
                      <Link
                        key={item.to}
                        to={item.to}
                        className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${active
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                          }`}
                      >
                        <item.icon className="h-4 w-4" />
                        {t(item.labelKey)}
                      </Link>
                    );
                  })}
                </nav>
              </div>
            </aside>

            <div className="space-y-6">
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
