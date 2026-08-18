import React, { useState, useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { BackToProfile } from '@/components/BackToProfile';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasElevatedAccess } from '@/lib/auth/roles';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  BarChart3,
  CheckSquare,
  ClipboardList,
  Map,
  CalendarRange,
  HardHat,
  Layers,
  MapPin,
  Truck,
  Search,
  Users,
  X,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react';

type TaskNavItem = {
  to: string;
  icon: LucideIcon;
  labelKey: string;
  elevatedOnly: boolean;
  category: 'ops' | 'planning' | 'resources' | 'analytics';
};

const taskNavItems: TaskNavItem[] = [
  // ── Оперативные работы
  { to: '/tasks', icon: CheckSquare, labelKey: 'tasks.nav.tasks', elevatedOnly: false, category: 'ops' },
  { to: '/tasks/daily', icon: ClipboardList, labelKey: 'tasks.nav.daily', elevatedOnly: false, category: 'ops' },
  { to: '/tasks/project-daily', icon: Users, labelKey: 'tasks.nav.projectDaily', elevatedOnly: true, category: 'ops' },

  // ── Планирование
  { to: '/tasks/roadmap', icon: Map, labelKey: 'tasks.nav.roadmap', elevatedOnly: true, category: 'planning' },
  { to: '/manage/projects', icon: Layers, labelKey: 'tasks.nav.projects', elevatedOnly: true, category: 'planning' },

  // ── Ресурсы и объекты
  { to: '/tasks/resources', icon: CalendarRange, labelKey: 'tasks.nav.resources', elevatedOnly: true, category: 'resources' },
  { to: '/tasks/equipment', icon: Truck, labelKey: 'tasks.nav.equipment', elevatedOnly: true, category: 'resources' },
  { to: '/tasks/sites', icon: MapPin, labelKey: 'tasks.nav.sites', elevatedOnly: true, category: 'resources' },
  { to: '/tasks/contractors', icon: HardHat, labelKey: 'tasks.nav.contractors', elevatedOnly: true, category: 'resources' },

  // ── Аналитика
  { to: '/tasks/reports', icon: BarChart3, labelKey: 'tasks.nav.reports', elevatedOnly: true, category: 'analytics' },
];

const categoryTitles: Record<string, string> = {
  ops: 'Оперативные работы',
  planning: 'Планирование',
  resources: 'Ресурсы и объекты',
  analytics: 'Аналитика и отчеты',
};

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
  const [searchQuery, setSearchQuery] = useState('');

  const visibleNavItems = useMemo(() => {
    return taskNavItems.filter((item) => elevated || !item.elevatedOnly);
  }, [elevated]);

  const filteredNavItems = useMemo(() => {
    if (!searchQuery.trim()) return visibleNavItems;
    const q = searchQuery.toLowerCase();
    return visibleNavItems.filter((item) => {
      const label = t(item.labelKey).toLowerCase();
      return label.includes(q);
    });
  }, [visibleNavItems, searchQuery, t]);

  const groupedNav = useMemo(() => {
    const groups: Record<string, TaskNavItem[]> = {
      ops: [],
      planning: [],
      resources: [],
      analytics: [],
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
                <div className="text-xs font-bold uppercase tracking-[0.25em] text-primary/80">
                  {t('tasks.title', 'Модуль Работ')}
                </div>
                <h1 className="font-display text-3xl font-bold tracking-tight text-foreground sm:text-4xl mt-1">
                  {title}
                </h1>
                {subtitle && (
                  <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
                )}
              </div>
            </div>
          </div>

          {/* Mobile horizontal scroll nav */}
          <div className="mb-6 flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none lg:hidden">
            {visibleNavItems.map((item) => {
              const active = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    'flex min-h-[44px] items-center gap-2 px-4 py-2 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all duration-200 border shadow-2xs',
                    active
                      ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                      : 'bg-card text-muted-foreground hover:bg-muted/80 hover:text-foreground border-border/50'
                  )}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {t(item.labelKey)}
                </Link>
              );
            })}
          </div>

          {/* Main Layout Grid */}
          <div className="grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)] items-start">
            {/* Desktop Sticky Sidebar */}
            <aside className="hidden lg:block sticky top-24 z-20">
              <div className="rounded-3xl border bg-card/85 backdrop-blur-md p-4 shadow-sm space-y-4">
                {/* Search input inside nav */}
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Поиск разделов..."
                    className="pl-8 pr-8 h-8 text-xs rounded-xl bg-muted/30 border-muted-foreground/20 focus:bg-background"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>

                <nav className="space-y-4">
                  {Object.entries(groupedNav).map(([catKey, items]) => {
                    if (items.length === 0) return null;
                    return (
                      <div key={catKey} className="space-y-1.5">
                        <div className="px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">
                          {categoryTitles[catKey]}
                        </div>
                        <div className="space-y-1">
                          {items.map((item) => {
                            const active = location.pathname === item.to;
                            return (
                              <Link
                                key={item.to}
                                to={item.to}
                                className={cn(
                                  'group flex items-center justify-between rounded-xl px-3 py-2 text-xs font-medium transition-all duration-150',
                                  active
                                    ? 'bg-primary text-primary-foreground font-semibold shadow-2xs'
                                    : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'
                                )}
                              >
                                <div className="flex items-center gap-2.5 min-w-0">
                                  <item.icon
                                    className={cn(
                                      'h-4 w-4 shrink-0 transition-transform group-hover:scale-110',
                                      active ? 'text-primary-foreground' : 'text-muted-foreground group-hover:text-foreground'
                                    )}
                                  />
                                  <span className="truncate">{t(item.labelKey)}</span>
                                </div>
                                {active && <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-80" />}
                              </Link>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                  {filteredNavItems.length === 0 && (
                    <div className="py-4 text-center text-xs text-muted-foreground">
                      Разделы не найдены
                    </div>
                  )}
                </nav>
              </div>
            </aside>

            {/* Content Area */}
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
