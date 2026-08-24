import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Wallet } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { formatAmount, remainingTone } from '@/components/contracts/format';
import { contractsApi } from '@/api/contracts';
import { useTranslation } from 'react-i18next';

/**
 * Список бюджетных строк.
 *
 * «Законтрактовано» и «Остаток» приходят с бэкенда уже посчитанными — в БД
 * таких колонок нет, они выводятся из договоров. Складывать их здесь не
 * нужно и нельзя: фронтенд не видит договоров в неучитываемых статусах и
 * получил бы своё, неверное число.
 */

const BudgetList = () => {
  const { t } = useTranslation();
  const { data: budgets = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'budgets'],
    queryFn: () => contractsApi.listBudgets().then((r) => r.data),
  });

  return (
    <ContractsShell>
        <div className="mb-6 flex flex-col gap-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <Wallet className="h-7 w-7 text-muted-foreground" />
              <h1 className="text-3xl font-bold">{t('contracts.nav.budgets')}</h1>
            </div>
            <Button asChild>
              <Link to="/contracts/budgets/new">
                <Plus className="mr-2 h-4 w-4" />
                {t('contracts.budgetRequest')}
              </Link>
            </Button>
          </div>
        </div>

        <div className="bg-card rounded-lg border overflow-x-auto">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-10 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="p-6 text-sm text-destructive">
              {t('contracts.budgets.loadError')}
            </p>
          ) : budgets.length === 0 ? (
            <div className="p-10 text-center">
              <p className="text-muted-foreground mb-4">{t('contracts.budgets.empty')}</p>
              <Button asChild variant="outline">
                <Link to="/contracts/budgets/new">{t('contracts.budgets.createFirst')}</Link>
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('contracts.columns.administrator')}</TableHead>
                  <TableHead>{t('contracts.budget.programmes')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.year')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.allocated')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.contracted')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.remaining')}</TableHead>
                  <TableHead>{t('contracts.columns.status')}</TableHead>
                  {/* Согласование — ОТДЕЛЬНАЯ ось от статуса: закрытый
                      бюджет и отклонённый бюджет — разные вещи, и колонка
                      у них поэтому тоже разная. */}
                  <TableHead className="text-right">{t('contracts.columns.approval')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {budgets.map((budget) => (
                  <TableRow key={budget.id}>
                    <TableCell className="font-medium">
                      <Link
                        to={`/contracts/budgets/${budget.id}`}
                        className="hover:underline underline-offset-2"
                      >
                        {budget.administrator_name}
                      </Link>
                    </TableCell>
                    {/* Бюджет — контейнер: программ в нём несколько, и в
                        списке показывается их число с перечислением, а не
                        одна строка. Полная таблица — на карточке. */}
                    <TableCell>
                      <div>
                        {t('contracts.budget.programmeCount', { count: budget.lines.length })}
                      </div>
                      <div className="text-xs text-muted-foreground truncate max-w-xs">
                        {budget.lines.map((row) => row.program_name).join(', ') || '—'}
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {budget.period_year}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(budget.allocated)} {budget.currency}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(budget.committed)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${remainingTone(
                        budget.remaining,
                        budget.allocated,
                      )}`}
                    >
                      {formatAmount(budget.remaining)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={budget.status === 'active' ? 'secondary' : 'outline'}
                      >
                        {budget.status === 'active' ? t('contracts.status.active') : t('contracts.status.closed')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <SubmitForApproval
                        subjectType="contracts.budget"
                        subjectId={budget.id}
                        state={budget.approval_state}
                        submit={contractsApi.submitBudget}
                        invalidate={[['contracts', 'budgets']]}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
    </ContractsShell>
  );
};

export default BudgetList;
