/** Layout wrapper for all /requests pages — mirrors TasksLayout (Header,
 *  back-to-profile link, page title, side nav). */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';

import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import {
  ArrowLeft, BarChart3, ClipboardList, Database, FolderKanban, Layers, LineChart, Table2, Inbox as InboxIcon,
} from 'lucide-react';

import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasAnyRole } from '@/lib/auth/roles';

const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

const requestsNavItems = [
  { to: '/requests',           icon: InboxIcon,    label: 'Запросы',        adminOnly: false },
  { to: '/requests/my-stats',  icon: LineChart,    label: 'Моя статистика', adminOnly: false },
  { to: '/requests/templates', icon: Layers,       label: 'Шаблоны',        adminOnly: true },
  { to: '/requests/reference', icon: Database,     label: 'Справочники',    adminOnly: true },
  { to: '/requests/data',      icon: Table2,       label: 'Управление данными', adminOnly: false },
  { to: '/requests/projects',  icon: FolderKanban, label: 'Проекты',        adminOnly: true },
  { to: '/requests/stats',     icon: BarChart3,    label: 'Статистика',     adminOnly: true },
];

interface Props {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export const RequestsLayout: React.FC<Props> = ({ title, subtitle, actions, children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const { activeProfile } = useActiveProfile();
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);
  const visibleNavItems = requestsNavItems.filter((item) => !item.adminOnly || isAdmin);

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
              {t('tasks.backToMain', 'К моему профилю')}
            </Link>

            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="text-sm uppercase tracking-[0.3em] text-muted-foreground flex items-center gap-2">
                  <ClipboardList className="h-4 w-4" />
                  {t('profile.sidebar.requests', 'Запросы')}
                </div>
                <h1 className="font-display text-3xl font-semibold text-foreground">{title}</h1>
                {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
              </div>
              {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
            </div>
          </div>

          <div className="mb-6 flex items-center gap-2 overflow-x-auto rounded-xl border bg-card/70 p-2 shadow-[var(--shadow-soft)] lg:hidden">
            {visibleNavItems.map((item) => {
              const active = item.to === '/requests'
                ? location.pathname === '/requests'
                : location.pathname.startsWith(item.to);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>

          <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)] items-start">
            <aside className="hidden lg:block">
              <div className="rounded-2xl border bg-card/70 p-4 shadow-[var(--shadow-soft)]">
                <div className="text-xs uppercase tracking-[0.25em] text-muted-foreground mb-3">
                  Навигация
                </div>
                <nav className="flex flex-col gap-2">
                  {visibleNavItems.map((item) => {
                    const active = item.to === '/requests'
                      ? location.pathname === '/requests'
                      : location.pathname.startsWith(item.to);
                    return (
                      <Link
                        key={item.to}
                        to={item.to}
                        className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                          active
                            ? 'bg-primary text-primary-foreground'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                        }`}
                      >
                        <item.icon className="h-4 w-4" />
                        {item.label}
                      </Link>
                    );
                  })}
                </nav>
              </div>
            </aside>

            <div className="space-y-6 min-w-0 w-full">
              {children}
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default RequestsLayout;
