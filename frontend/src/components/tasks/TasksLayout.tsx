import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { ArrowLeft, BarChart3, CheckSquare, Map, CalendarRange, Truck } from 'lucide-react';

const taskNavItems = [
  { to: '/tasks', icon: CheckSquare, labelKey: 'tasks.nav.tasks' },
  { to: '/tasks/roadmap', icon: Map, labelKey: 'tasks.nav.roadmap' },
  { to: '/tasks/reports', icon: BarChart3, labelKey: 'tasks.nav.reports' },
  { to: '/tasks/resources', icon: CalendarRange, labelKey: 'tasks.nav.resources' },
  { to: '/tasks/equipment', icon: Truck, labelKey: 'tasks.nav.equipment' },
];

interface Props {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const TasksLayout: React.FC<Props> = ({ title, subtitle, children }) => {
  const { t } = useTranslation();
  const location = useLocation();

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
              {t('tasks.backToMain')}
            </Link>

            <div>
              <div className="text-sm uppercase tracking-[0.3em] text-muted-foreground">{t('tasks.title')}</div>
              <h1 className="font-display text-3xl font-semibold text-foreground">{title}</h1>
              {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
            </div>
          </div>

          <div className="mb-6 flex items-center gap-2 overflow-x-auto rounded-xl border bg-card/70 p-2 shadow-[var(--shadow-soft)] lg:hidden">
            {taskNavItems.map((item) => {
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
                  {taskNavItems.map((item) => {
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
