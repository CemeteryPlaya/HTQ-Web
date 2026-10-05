/**
 * Раздел БЗО на экране «Сводка группы» (`/holding`, A8.1, D-S7-8).
 *
 * Свой запрос и своё состояние, не часть общего: у ручки свой замок — узел
 * `bpp.holding` (ФД, ГД). Без узла запрос не уходит вовсе (иначе каждый
 * посетитель `/holding` получал бы 403 и попытку обновить токен); 403/404 от
 * сервера (не тот поддомен, нет модуля у компании) — раздела просто нет, а не
 * ошибка на всю страницу. 503 — «сейчас недоступна»: это и пересборка сводок,
 * и выключенный модуль (код ответа `api/client.ts` у 5xx не сохраняет, а о
 * выключенном сервисе уже говорит общий диалог). Деньги — строки сервера
 * через `formatMoney`.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus } from '@/lib/apiError';

import { formatMoney } from '../format';
import { bppHoldingApi, type CountAmount } from './api';

function CountMoney({ value }: { value: CountAmount }) {
  return (
    <div className="text-right tabular-nums">
      <div>{formatMoney(value.amount_kzt, 'KZT')}</div>
      <div className="text-xs text-muted-foreground">{value.count}</div>
    </div>
  );
}

export function BppGroupSection() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const allowed = permissions.can('bpp.holding', 'view');
  const query = useQuery({
    queryKey: ['holding', 'bpp-summary'],
    queryFn: async () => (await bppHoldingApi.summary()).data,
    enabled: allowed,
    retry: false,
  });

  if (!allowed) return null;
  if (query.isLoading) {
    return <Skeleton data-testid="bpp-holding-skeleton" className="h-40 w-full rounded-xl" />;
  }
  const status = query.error ? errorStatus(query.error) : null;
  if (status === 403 || status === 404) return null;
  if (status === 503) {
    return (
      <p data-testid="bpp-holding-unavailable" className="text-sm text-muted-foreground">
        {t('bpp.holding.unavailable', 'Сводка по БЗО сейчас недоступна, повторите позже.')}
      </p>
    );
  }
  if (query.error || !query.data) {
    return (
      <p data-testid="bpp-holding-error" className="text-sm text-destructive">
        {t('bpp.holding.error', 'Не удалось загрузить сводку по БЗО.')}
      </p>
    );
  }

  const { companies, totals } = query.data;
  return (
    <Card data-testid="bpp-holding-section">
      <CardHeader>
        <CardTitle className="text-lg">
          {t('bpp.holding.title', 'Бюджет, закупки и оплаты по группе')}
        </CardTitle>
        <CardDescription>
          {t('bpp.holding.hint',
            'Лимит утверждённых бюджетов в тенге, счета и действующие договоры по каждой компании. «Задействовано» в сводку не входит.')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('bpp.holding.company', 'Компания')}</TableHead>
              <TableHead className="text-right">{t('bpp.holding.budgets', 'Утверждённых бюджетов')}</TableHead>
              <TableHead className="text-right">{t('bpp.holding.limit', 'Лимит (KZT)')}</TableHead>
              <TableHead className="text-right">{t('bpp.holding.toPay', 'К оплате')}</TableHead>
              <TableHead className="text-right">{t('bpp.holding.paid', 'Оплачено')}</TableHead>
              <TableHead className="text-right">{t('bpp.holding.agreements', 'Договоров действует')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {companies.map((row) => (
              <TableRow key={row.company_slug}>
                <TableCell className="font-medium">{row.company_name}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.budgets}
                  {row.budgets_other_currency > 0 && (
                    <div className="text-xs text-muted-foreground">
                      {t('bpp.holding.otherCurrency', '+ {{count}} в другой валюте (не в сумме)',
                        { count: row.budgets_other_currency })}
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(row.limit_kzt, 'KZT')}</TableCell>
                <TableCell><CountMoney value={row.invoices_to_pay} /></TableCell>
                <TableCell><CountMoney value={row.invoices_paid} /></TableCell>
                <TableCell className="text-right tabular-nums">{row.agreements_active}</TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell className="font-semibold">{t('bpp.holding.totals', 'Итого по группе')}</TableCell>
              <TableCell className="text-right font-semibold tabular-nums">{totals.budgets}</TableCell>
              <TableCell className="text-right font-semibold tabular-nums">
                {formatMoney(totals.limit_kzt, 'KZT')}
              </TableCell>
              <TableCell><CountMoney value={totals.invoices_to_pay} /></TableCell>
              <TableCell><CountMoney value={totals.invoices_paid} /></TableCell>
              <TableCell className="text-right font-semibold tabular-nums">{totals.agreements_active}</TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </CardContent>
    </Card>
  );
}
