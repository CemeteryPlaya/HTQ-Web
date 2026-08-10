import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, FileText, Plus, Receipt, Wallet } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/** Formats the high-level budget metrics without decimal fractions. */
function formatShort(value: string): string {
  const whole = value.split('.')[0];
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/** Sums decimal strings as kopecks so dashboard totals retain precision. */
function sumAmounts(values: string[]): string {
  const kopecks = values.reduce((total, value) => {
    const [whole, fraction = '0'] = value.split('.');
    return total + BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
  }, 0n);
  return (kopecks / 100n).toString();
}

interface ModuleCardProps {
  icon: typeof Wallet;
  title: string;
  description: string;
  count: number | undefined;
  isLoading: boolean;
  to: string;
  primaryAction?: { to: string; label: string };
}

function ModuleCard({
  icon: Icon,
  title,
  description,
  count,
  isLoading,
  to,
  primaryAction,
}: ModuleCardProps) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-5 w-5 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="mt-auto flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs text-muted-foreground">Всего</p>
          {isLoading ? (
            <Skeleton className="mt-1 h-8 w-12" />
          ) : (
            <p className="mt-1 text-2xl font-semibold tabular-nums">{count ?? '—'}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to={to}>Открыть</Link>
          </Button>
          {primaryAction && (
            <Button asChild size="sm">
              <Link to={primaryAction.to}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {primaryAction.label}
              </Link>
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

const ContractsOverview = () => {
  const { data: budgets, isLoading: budgetsLoading } = useQuery({
    queryKey: ['contracts', 'budgets'],
    queryFn: () => contractsApi.listBudgets().then((response) => response.data),
  });
  const { data: counterparties, isLoading: counterpartiesLoading } = useQuery({
    queryKey: ['contracts', 'counterparties', ''],
    queryFn: () => contractsApi.listCounterparties().then((response) => response.data),
  });
  const { data: agreements, isLoading: agreementsLoading } = useQuery({
    queryKey: ['contracts', 'agreements'],
    queryFn: () => contractsApi.listAgreements().then((response) => response.data),
  });
  const { data: invoices, isLoading: invoicesLoading } = useQuery({
    queryKey: ['contracts', 'invoices'],
    queryFn: () => contractsApi.listInvoices().then((response) => response.data),
  });
  const { data: advancePayments, isLoading: advancePaymentsLoading } = useQuery({
    queryKey: ['contracts', 'advance-payments'],
    queryFn: () => contractsApi.listAdvancePayments().then((response) => response.data),
  });
  const { data: contractPayments, isLoading: contractPaymentsLoading } = useQuery({
    queryKey: ['contracts', 'contract-payments'],
    queryFn: () => contractsApi.listContractPayments().then((response) => response.data),
  });
  const { data: completionActs, isLoading: completionActsLoading } = useQuery({
    queryKey: ['contracts', 'completion-acts'],
    queryFn: () => contractsApi.listCompletionActs().then((response) => response.data),
  });

  // Totals are only meaningful within one currency; the overview deliberately
  // refuses to merge different currencies into a misleading single figure.
  const currency = budgets?.[0]?.currency ?? 'KZT';
  const sameCurrencyBudgets = (budgets ?? []).filter((budget) => budget.currency === currency);
  const allocated = sumAmounts(sameCurrencyBudgets.map((budget) => budget.allocated));
  const remaining = sumAmounts(sameCurrencyBudgets.map((budget) => budget.remaining));
  const mixedCurrencies = (budgets ?? []).length !== sameCurrencyBudgets.length;
  const awaitingAccounting = [
    ...(advancePayments ?? []),
    ...(contractPayments ?? []),
    ...(completionActs ?? []),
  ].filter((payment) => payment.status === 'awaiting_accounting').length;
  const paymentsLoading = advancePaymentsLoading || contractPaymentsLoading || completionActsLoading;

  return (
    <ContractsShell>
      <div className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold">Договоры и платежи</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Рабочее место для бюджета, договоров, прямых счетов и проведения оплат.
        </p>
      </div>

      <div className="mb-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Wallet className="h-4 w-4" />
              Свободно в бюджетах
            </CardDescription>
          </CardHeader>
          <CardContent>
            {budgetsLoading ? (
              <Skeleton className="h-8 w-32" />
            ) : (
              <>
                <p className="text-3xl font-bold tabular-nums">
                  {formatShort(remaining)}{' '}
                  <span className="text-base font-normal text-muted-foreground">{currency}</span>
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  из {formatShort(allocated)} {currency}
                  {mixedCurrencies && ` · только ${currency}`}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Договоров
            </CardDescription>
          </CardHeader>
          <CardContent>
            {agreementsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <p className="text-3xl font-bold tabular-nums">{agreements?.length ?? 0}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Wallet className="h-4 w-4" />
              Ожидают бухгалтерию
            </CardDescription>
          </CardHeader>
          <CardContent>
            {paymentsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <p className="text-3xl font-bold tabular-nums">{awaitingAccounting}</p>
            )}
          </CardContent>
        </Card>
      </div>

      <section className="mb-10">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Бюджет и закупки</h2>
          <p className="text-sm text-muted-foreground">
            Подготовьте источник денег и контрагента, затем оформите договор или прямой счёт.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <ModuleCard
            icon={Wallet}
            title="Бюджеты"
            description="Бюджетные строки по программам, их лимиты и остатки."
            count={budgets?.length}
            isLoading={budgetsLoading}
            to="/contracts/budgets"
            primaryAction={{ to: '/contracts/budgets/new', label: 'Создать' }}
          />
          <ModuleCard
            icon={Building2}
            title="Контрагенты"
            description="Реестр организаций и ИП, с которыми оформляются документы."
            count={counterparties?.length}
            isLoading={counterpartiesLoading}
            to="/contracts/counterparties"
            primaryAction={{ to: '/contracts/counterparties/new', label: 'Добавить' }}
          />
          <ModuleCard
            icon={Receipt}
            title="Счета без договора"
            description="Прямые счета на оплату по бюджетной строке, без договора."
            count={invoices?.length}
            isLoading={invoicesLoading}
            to="/contracts/invoices"
            primaryAction={{ to: '/contracts/invoices/new', label: 'Создать' }}
          />
        </div>
      </section>

      <section>
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Договор и исполнение</h2>
          <p className="text-sm text-muted-foreground">
            Оформите договор, затем отслеживайте авансы, оплаты и акты выполненных работ.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-4">
          <ModuleCard
            icon={FileText}
            title="Договоры"
            description="Договоры с привязкой к бюджету, контрагенту и программе."
            count={agreements?.length}
            isLoading={agreementsLoading}
            to="/contracts/agreements"
            primaryAction={{ to: '/contracts/agreements/new', label: 'Создать' }}
          />
          <ModuleCard
            icon={Wallet}
            title="Предоплаты"
            description="Авансы по согласованным договорам и их проведение бухгалтерией."
            count={advancePayments?.length}
            isLoading={advancePaymentsLoading}
            to="/contracts/advance-payments"
            primaryAction={{ to: '/contracts/advance-payments/new', label: 'Создать' }}
          />
          <ModuleCard
            icon={Wallet}
            title="Оплаты по договорам"
            description="Оплаты со счётом, согласованием и платёжным поручением."
            count={contractPayments?.length}
            isLoading={contractPaymentsLoading}
            to="/contracts/contract-payments"
            primaryAction={{ to: '/contracts/contract-payments/new', label: 'Создать' }}
          />
          <ModuleCard
            icon={FileText}
            title="Акты выполненных работ"
            description="АВР с согласованием и последующим проведением бухгалтерией."
            count={completionActs?.length}
            isLoading={completionActsLoading}
            to="/contracts/completion-acts"
            primaryAction={{ to: '/contracts/completion-acts/new', label: 'Создать' }}
          />
        </div>
      </section>
    </ContractsShell>
  );
};

export default ContractsOverview;
