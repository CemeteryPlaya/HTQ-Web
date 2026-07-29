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
import { contractsApi } from '@/api/contracts';
import type { Budget } from '@/types/contracts';

/**
 * Список бюджетных строк.
 *
 * «Законтрактовано» и «Остаток» приходят с бэкенда уже посчитанными — в БД
 * таких колонок нет, они выводятся из договоров. Складывать их здесь не
 * нужно и нельзя: фронтенд не видит договоров в неучитываемых статусах и
 * получил бы своё, неверное число.
 */

/** 5000000.00 → «5 000 000,00». Intl не подходит: суммы приходят строками
 *  (Decimal), и прогон через Number терял бы копейки на больших числах. */
function formatAmount(value: string): string {
  const [whole, fraction = '00'] = value.split('.');
  const spaced = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${spaced},${fraction}`;
}

function remainingTone(budget: Budget): string {
  const remaining = Number(budget.remaining);
  const total = Number(budget.amount);
  if (!Number.isFinite(remaining) || !Number.isFinite(total) || total === 0) return '';
  if (remaining <= 0) return 'text-destructive font-medium';
  if (remaining / total < 0.15) return 'text-amber-600 dark:text-amber-500 font-medium';
  return '';
}

const BudgetList = () => {
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
              <h1 className="text-3xl font-bold">Бюджеты</h1>
            </div>
            <Button asChild>
              <Link to="/contracts/budgets/new">
                <Plus className="mr-2 h-4 w-4" />
                Заявка на бюджет
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
              Не удалось загрузить бюджеты.
            </p>
          ) : budgets.length === 0 ? (
            <div className="p-10 text-center">
              <p className="text-muted-foreground mb-4">Бюджетов пока нет.</p>
              <Button asChild variant="outline">
                <Link to="/contracts/budgets/new">Создать первый</Link>
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Администратор</TableHead>
                  <TableHead>Программа / статья</TableHead>
                  <TableHead className="text-right">Год</TableHead>
                  <TableHead className="text-right">Выделено</TableHead>
                  <TableHead className="text-right">Законтрактовано</TableHead>
                  <TableHead className="text-right">Остаток</TableHead>
                  <TableHead>Статус</TableHead>
                  {/* Согласование — ОТДЕЛЬНАЯ ось от статуса: закрытый
                      бюджет и отклонённый бюджет — разные вещи, и колонка
                      у них поэтому тоже разная. */}
                  <TableHead className="text-right">Согласование</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {budgets.map((budget) => (
                  <TableRow key={budget.id}>
                    <TableCell className="font-medium">
                      {budget.administrator_name}
                    </TableCell>
                    <TableCell>
                      <div>{budget.program_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {budget.expense_item}
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {budget.period_year}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(budget.amount)} {budget.currency}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(budget.committed)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${remainingTone(budget)}`}
                    >
                      {formatAmount(budget.remaining)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={budget.status === 'active' ? 'secondary' : 'outline'}
                      >
                        {budget.status === 'active' ? 'Активен' : 'Закрыт'}
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
