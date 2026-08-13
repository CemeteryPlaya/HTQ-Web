import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Building2, CheckSquare, FileText, LayoutDashboard, Receipt, Wallet } from 'lucide-react';

import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { BackToProfile } from '@/components/BackToProfile';
import { cn } from '@/lib/utils';

/**
 * Общая рамка раздела «Договоры»: шапка приложения, боковая панель
 * навигации, контент, подвал.
 *
 * Панель живёт здесь, а не только на /contracts, чтобы не пропадать при
 * переходе на список или форму — иначе из бюджетов в реестр контрактов
 * пришлось бы возвращаться через хаб.
 */

interface NavItem {
  to: string;
  label: string;
  icon: typeof Wallet;
  /** Активен и для вложенных путей (`/new` и будущие `/:id`). */
  matchPrefix?: string;
  disabled?: boolean;
  hint?: string;
}

interface NavSection {
  label?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { to: '/contracts', label: 'Обзор', icon: LayoutDashboard },
      { to: '/contracts/tasks', label: 'Ждёт меня', icon: CheckSquare },
    ],
  },
  {
    label: 'Бюджеты и справочники',
    items: [
      { to: '/contracts/budgets', label: 'Бюджеты', icon: Wallet, matchPrefix: '/contracts/budgets' },
      { to: '/contracts/counterparties', label: 'Реестр контрагентов', icon: Building2, matchPrefix: '/contracts/counterparties' },
    ],
  },
  {
    label: 'Договорная работа',
    items: [
      { to: '/contracts/agreements', label: 'Договоры', icon: FileText, matchPrefix: '/contracts/agreements' },
      { to: '/contracts/advance-payments', label: 'Предоплаты', icon: Wallet, matchPrefix: '/contracts/advance-payments' },
      { to: '/contracts/contract-payments', label: 'Оплаты по договорам', icon: Wallet, matchPrefix: '/contracts/contract-payments' },
      { to: '/contracts/completion-acts', label: 'Акты выполненных работ', icon: FileText, matchPrefix: '/contracts/completion-acts' },
    ],
  },
  {
    label: 'Расходы без договора',
    items: [
      { to: '/contracts/invoices', label: 'Счета без договора', icon: Receipt, matchPrefix: '/contracts/invoices' },
      { to: '/contracts/accountable-funds-requests', label: 'Подотчётные средства', icon: Wallet, matchPrefix: '/contracts/accountable-funds-requests' },
    ],
  },
];

export function ContractsShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();

  const isActive = (item: NavItem) =>
    item.matchPrefix ? pathname.startsWith(item.matchPrefix) : pathname === item.to;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 container mx-auto px-4 py-8">
        <BackToProfile className="mb-6" />
        <div className="flex flex-col gap-6 md:flex-row md:gap-8">
          <aside className="md:w-56 shrink-0">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 px-3">
              Договоры
            </h2>
            <nav className="flex flex-row gap-3 overflow-x-auto md:flex-col md:gap-5 md:overflow-visible">
              {NAV_SECTIONS.map((section) => (
                <section key={section.label ?? section.items[0].to} className="flex shrink-0 flex-row gap-1 md:flex-col">
                  {section.label && <p className="flex shrink-0 items-center whitespace-nowrap px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground md:block">
                    {section.label}
                  </p>}
                  {section.items.map((item) => {
                    const Icon = item.icon;
                    const classes = cn(
                      'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors whitespace-nowrap',
                      isActive(item)
                        ? 'bg-accent text-accent-foreground font-medium'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                      item.disabled && 'opacity-50 cursor-not-allowed hover:bg-transparent',
                    );

                    if (item.disabled) {
                      return (
                        <span key={item.to} className={classes} aria-disabled="true">
                          <Icon className="h-4 w-4 shrink-0" />
                          {item.label}
                          {item.hint && (
                            <span className="text-xs ml-auto hidden md:inline">
                              {item.hint}
                            </span>
                          )}
                        </span>
                      );
                    }

                    return (
                      <Link key={item.to} to={item.to} className={classes}>
                        <Icon className="h-4 w-4 shrink-0" />
                        {item.label}
                      </Link>
                    );
                  })}
                </section>
              ))}
            </nav>
          </aside>

          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </div>
      <Footer />
    </div>
  );
}
