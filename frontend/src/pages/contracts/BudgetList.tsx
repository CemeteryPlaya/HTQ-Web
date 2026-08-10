import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Wallet } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import {
  CollectionPageHeader,
  CollectionTable,
} from '@/components/contracts/CollectionPage';
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
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { formatAmount, remainingTone } from '@/components/contracts/format';
import { contractsApi } from '@/api/contracts';

/**
 * Список бюджетных строк.
 *
 * «Законтрактовано» и «Остаток» приходят с бэкенда уже посчитанными — в БД
 * таких колонок нет, они выводятся из договоров. Складывать их здесь не
 * нужно и нельзя: фронтенд не видит договоров в неучитываемых статусах и
 * получил бы своё, неверное число.
 */

const BudgetList = () => {
  const { data: budgets = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'budgets'],
    queryFn: () => contractsApi.listBudgets().then((r) => r.data),
  });

  return (
    <ContractsShell>
        <CollectionPageHeader
          icon={Wallet}
          title="Бюджеты"
          actions={
            <Button asChild>
              <Link to="/contracts/budgets/new">
                <Plus className="mr-2 h-4 w-4" />
                Заявка на бюджет
              </Link>
            </Button>
          }
        />

        <CollectionTable
          isLoading={isLoading}
          isError={isError}
          isEmpty={budgets.length === 0}
          errorMessage="Не удалось загрузить бюджеты."
          emptyMessage="Бюджетов пока нет."
          emptyAction={
            <Button asChild variant="outline">
              <Link to="/contracts/budgets/new">Создать первый</Link>
            </Button>
          }
        >
          <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Администратор</TableHead>
                  <TableHead>Программы</TableHead>
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
                        {budget.lines.length}{' '}
                        {budget.lines.length === 1
                          ? 'программа'
                          : budget.lines.length < 5
                            ? 'программы'
                            : 'программ'}
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
        </CollectionTable>
    </ContractsShell>
  );
};

export default BudgetList;
