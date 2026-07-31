import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, FileText, Plus, Wallet } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { contractsApi } from '@/api/contracts';

/**
 * Обзор раздела «Договоры».
 *
 * Сводка намеренно скромная: считается по тем же данным, что отдаёт API
 * списков, без отдельного агрегирующего эндпоинта. Как только чисел
 * понадобится больше (по годам, по программам), это должен считать
 * бэкенд — складывать суммы в браузере значит получить своё число,
 * расходящееся с тем, что показывают бюджеты.
 */

/** 5000000.00 → «5 000 000». Дробную часть в сводке не показываем. */
function formatShort(value: string): string {
  const whole = value.split('.')[0];
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/** Сложение сумм-строк без потери копеек: считаем в целых копейках. */
function sumAmounts(values: string[]): string {
  const kopecks = values.reduce((total, value) => {
    const [whole, fraction = '0'] = value.split('.');
    return total + BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
  }, 0n);
  return (kopecks / 100n).toString();
}

const ContractsOverview = () => {
  const { data: budgets, isLoading: budgetsLoading } = useQuery({
    queryKey: ['contracts', 'budgets'],
    queryFn: () => contractsApi.listBudgets().then((r) => r.data),
  });
  const { data: counterparties, isLoading: counterpartiesLoading } = useQuery({
    queryKey: ['contracts', 'counterparties', ''],
    queryFn: () => contractsApi.listCounterparties().then((r) => r.data),
  });

  // Сводка складывается только по одной валюте — смешивать KZT с USD в одно
  // число нельзя. Берём преобладающую и честно подписываем её.
  const currency = budgets?.[0]?.currency ?? 'KZT';
  const sameCurrency = (budgets ?? []).filter((row) => row.currency === currency);
  const allocated = sumAmounts(sameCurrency.map((row) => row.allocated));
  const remaining = sumAmounts(sameCurrency.map((row) => row.remaining));
  const mixedCurrencies = (budgets ?? []).length !== sameCurrency.length;

  return (
    <ContractsShell>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Договоры и бюджеты</h1>
        <p className="text-muted-foreground text-sm mt-1 max-w-2xl">
          Учёт договоров с контролем бюджета: сколько из выделенного уже
          законтрактовано и сколько осталось.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Wallet className="h-4 w-4" />
              Бюджетных строк
            </CardDescription>
          </CardHeader>
          <CardContent>
            {budgetsLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <>
                <p className="text-3xl font-bold tabular-nums">{budgets?.length ?? 0}</p>
                <p className="text-sm text-muted-foreground mt-1">
                  выделено {formatShort(allocated)} {currency}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Свободно по бюджетам</CardDescription>
          </CardHeader>
          <CardContent>
            {budgetsLoading ? (
              <Skeleton className="h-8 w-32" />
            ) : (
              <>
                <p className="text-3xl font-bold tabular-nums">
                  {formatShort(remaining)}{' '}
                  <span className="text-base font-normal text-muted-foreground">
                    {currency}
                  </span>
                </p>
                {mixedCurrencies && (
                  <p className="text-xs text-muted-foreground mt-1">
                    только строки в {currency} — валюты не смешиваются
                  </p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Building2 className="h-4 w-4" />
              Контрагентов в реестре
            </CardDescription>
          </CardHeader>
          <CardContent>
            {counterpartiesLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <p className="text-3xl font-bold tabular-nums">
                {counterparties?.length ?? 0}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <h2 className="text-lg font-semibold mb-3">Что можно сделать</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wallet className="h-5 w-5 text-muted-foreground" />
              Заявка на бюджет
            </CardTitle>
            <CardDescription>
              Администратор, программа и сумма — одной формой. Справочники
              заводятся прямо в ней.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button asChild size="sm">
              <Link to="/contracts/budgets/new">
                <Plus className="mr-2 h-4 w-4" />
                Создать
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to="/contracts/budgets">Все бюджеты</Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              Реестр контрагентов
            </CardTitle>
            <CardDescription>
              Карточки организаций и ИП: БИН/ИИН, НДС, адрес, контакты.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button asChild size="sm">
              <Link to="/contracts/counterparties/new">
                <Plus className="mr-2 h-4 w-4" />
                Добавить
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to="/contracts/counterparties">Весь реестр</Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="sm:col-span-2 opacity-60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-5 w-5 text-muted-foreground" />
              Договоры
            </CardTitle>
            <CardDescription>
              Оформление договора со списанием бюджетной строки. Страница ещё
              не готова — API уже работает, интерфейса пока нет.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </ContractsShell>
  );
};

export default ContractsOverview;
