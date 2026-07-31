/**
 * Общая рамка раздела «Согласования»: шапка приложения, боковая навигация,
 * контент, подвал. Устроена как ContractsShell — панель живёт в рамке, а не
 * на одной странице, чтобы не пропадать при переходе внутри раздела.
 *
 * «Маршруты» видны только администратору: править их может лишь он
 * (`api_view(admin=True)`), а читать разрешено всем — фронтенду надо
 * показывать, кто будет согласовывать, до отправки. Пункт меню всё равно
 * скрыт: настройка платформы обычному сотруднику не нужна, а страница
 * закрыта ещё и роутером (`requiresRole: 'admin'`).
 */

import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { GitBranch, Inbox, ListChecks } from 'lucide-react';

import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasAnyRole } from '@/lib/auth/roles';
import { cn } from '@/lib/utils';

/** Те же роли, что считает администраторскими раздел «Запросы». */
const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

interface NavItem {
  to: string;
  label: string;
  icon: typeof Inbox;
  /** Активен и для вложенных путей. */
  matchPrefix?: string;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { to: '/signoff', label: 'Ждёт меня', icon: Inbox },
  {
    to: '/signoff/processes',
    label: 'Согласования',
    icon: ListChecks,
    matchPrefix: '/signoff/processes',
  },
  {
    to: '/signoff/routes',
    label: 'Маршруты',
    icon: GitBranch,
    matchPrefix: '/signoff/routes',
    adminOnly: true,
  },
];

export function SignoffShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const { activeProfile } = useActiveProfile();
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);

  const items = NAV.filter((item) => !item.adminOnly || isAdmin);
  const isActive = (item: NavItem) =>
    item.matchPrefix ? pathname.startsWith(item.matchPrefix) : pathname === item.to;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 container mx-auto px-4 py-8">
        <div className="flex flex-col gap-6 md:flex-row md:gap-8">
          <aside className="md:w-56 shrink-0">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 px-3">
              Согласования
            </h2>
            <nav className="flex flex-row gap-1 overflow-x-auto md:flex-col md:overflow-visible">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={cn(
                      'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors whitespace-nowrap',
                      isActive(item)
                        ? 'bg-accent text-accent-foreground font-medium'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </aside>

          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </div>
      <Footer />
    </div>
  );
}
