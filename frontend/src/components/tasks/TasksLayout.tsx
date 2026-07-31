import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { BackToProfile } from '@/components/BackToProfile';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasElevatedAccess } from '@/lib/auth/roles';
import {
  BarChart3, CheckSquare, ClipboardList, Map, CalendarRange, HardHat, Layers,
  MapPin, Truck,
} from 'lucide-react';

/**
 * ``elevatedOnly`` mirrors ``requiresRole`` on the matching route. Without
 * it a regular employee sees four menu items that bounce them straight back
 * to /myprofile — a menu that advertises doors it then slams.
 */
const taskNavItems = [
  { to: '/tasks', icon: CheckSquare, labelKey: 'tasks.nav.tasks', elevatedOnly: false },
  // Ежедневка видна всем: отчитывается исполнитель, а не руководитель.
  { to: '/tasks/daily', icon: ClipboardList, labelKey: 'tasks.nav.daily', elevatedOnly: false },
  { to: '/tasks/roadmap', icon: Map, labelKey: 'tasks.nav.roadmap', elevatedOnly: true },
  // Historical path outside /tasks/* — the active check compares the whole
  // pathname, so it highlights correctly regardless of the prefix.
  { to: '/manage/projects', icon: Layers, labelKey: 'tasks.nav.projects', elevatedOnly: true },
  { to: '/tasks/reports', icon: BarChart3, labelKey: 'tasks.nav.reports', elevatedOnly: true },
  { to: '/tasks/resources', icon: CalendarRange, labelKey: 'tasks.nav.resources', elevatedOnly: true },
  { to: '/tasks/equipment', icon: Truck, labelKey: 'tasks.nav.equipment', elevatedOnly: true },
  { to: '/tasks/sites', icon: MapPin, labelKey: 'tasks.nav.sites', elevatedOnly: true },
  { to: '/tasks/contractors', icon: HardHat, labelKey: 'tasks.nav.contractors', elevatedOnly: true },
];

interface Props {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const TasksLayout: React.FC<Props> = ({ title, subtitle, children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const { activeProfile } = useActiveProfile();
  const elevated = hasElevatedAccess(activeProfile);
  const navItems = taskNavItems.filter((item) => elevated || !item.elevatedOnly);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1">
        <div className="container mx-auto px-4 py-8">
          <div className="mb-6 flex flex-col gap-4">
            <BackToProfile className="mb-0" />

            <div>
              <div className="text-sm uppercase tracking-[0.3em] text-muted-foreground">{t('tasks.title')}</div>
              <h1 className="font-display text-3xl font-semibold text-foreground">{title}</h1>
              {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
            </div>
          </div>

          <div className="mb-6 flex items-center gap-2 overflow-x-auto rounded-xl border bg-card/70 p-2 shadow-[var(--shadow-soft)] lg:hidden">
            {navItems.map((item) => {
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

          <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)] items-start">
            <aside className="hidden lg:block">
              <div className="rounded-2xl border bg-card/70 p-4 shadow-[var(--shadow-soft)]">
                <div className="text-xs uppercase tracking-[0.25em] text-muted-foreground mb-3">
                  {t('tasks.navigation')}
                </div>
                <nav className="flex flex-col gap-2">
                  {navItems.map((item) => {
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

export default TasksLayout;
