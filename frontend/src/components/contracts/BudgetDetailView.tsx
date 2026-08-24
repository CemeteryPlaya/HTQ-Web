/**
 * Тело карточки бюджета — проект, год и таблица его программ.
 *
 * Отделено от страницы (`pages/contracts/BudgetDetail`), потому что то же
 * тело показывает карточка согласования (`pages/signoff/ProcessDetail`):
 * согласующий должен видеть документ, не выходя из своего раздела и не
 * теряя кнопки решения. Рамку (`ContractsShell`/`SignoffShell`) выбирает
 * тот, кто рисует, — здесь её нет.
 *
 * Бюджет здесь КОНТЕЙНЕР: сумм на нём самом нет, они лежат на строках
 * (`budget.lines`), по строке на программу. «Выделено» — их сумма,
 * «законтрактовано» и «остаток» приходят с бэкенда уже посчитанными: в БД
 * таких колонок нет, они выводятся из договоров каждой строки
 * (`services/budget_calc.py`). Складывать их здесь нельзя — таблица
 * договоров ниже показывает ВСЕ договоры бюджета, включая черновики,
 * которые его не занимают, и сумма по ней не сойдётся с
 * «законтрактовано». Это не расхождение, а разные вопросы: «что привязано»
 * и «что занимает деньги».
 *
 * Согласование — одно на весь бюджет, а не на строку: утвердить половину
 * списка программ нельзя, в этом и смысл контейнера.
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Wallet } from 'lucide-react';

import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import {
  formatAmount,
  formatMoment,
  formatMoney,
  remainingTone,
} from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { contractsApi } from '@/api/contracts';
import type { AgreementStatus } from '@/types/contracts';
import { useTranslation } from 'react-i18next';

/** Доля занятого — только для полоски. Точность здесь не важна, сами суммы
 *  всегда показываются строками. */
function committedPercent(committed: string, allocated: string): number {
  const used = Number(committed);
  const total = Number(allocated);
  if (!Number.isFinite(used) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(100, Math.max(0, (used / total) * 100));
}

interface Props {
  id: number;
  /** Тело вставлено в карточку согласования. Убирает то, что там было бы
   *  дублем: кнопку отправки (объект уже на согласовании) и историю
   *  согласований (мы внутри одного из них). */
  embedded?: boolean;
}

const BudgetDetailView = ({ id: budgetId, embedded = false }: Props) => {
  const { t } = useTranslation();
  const enabled = Number.isFinite(budgetId);

  const {
    data: budget,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['contracts', 'budget', budgetId],
    queryFn: () => contractsApi.getBudget(budgetId).then((r) => r.data),
    enabled,
  });

  const { data: agreements = [] } = useQuery({
    queryKey: ['contracts', 'budget', budgetId, 'agreements'],
    queryFn: () => contractsApi.listBudgetAgreements(budgetId).then((r) => r.data),
    enabled,
  });

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Подписи статусов — с бэкенда: свой словарь разошёлся бы с моделью при
  // первом же добавлении статуса.
  const agreementStatusLabel = (value: AgreementStatus) =>
    enums?.agreement_status.find((option) => option.value === value)?.label ?? value;
  const budgetStatusLabel = (value: string) =>
    enums?.budget_status.find((option) => option.value === value)?.label ?? value;

  /** Занимает ли договор бюджет — множество приходит с бэкенда
   *  (`budget_calc.COMMITTING_STATUSES`), здесь его копии нет. */
  const isCommitting = (status: AgreementStatus) =>
    enums?.committing_statuses.includes(status) ?? false;

  if (isLoading) return <DetailSkeleton />;
  if (isError || !budget) {
    return (
      <p className="text-sm text-destructive">{t('contracts.budget.notFound')}</p>
    );
  }

  // На странице процесса `h1` уже занят самим согласованием.
  const Heading = embedded ? 'h2' : 'h1';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <Wallet className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold">
              {t('contracts.budget.titleYear', { year: budget.period_year })}
            </Heading>
            <Badge variant={budget.status === 'active' ? 'secondary' : 'outline'}>
              {budgetStatusLabel(budget.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {budget.administrator_name} ·{' '}
            {t('contracts.budget.programmeCount', { count: budget.lines.length })}
          </p>
        </div>

        {!embedded && (
          <SubmitForApproval
            subjectType="contracts.budget"
            subjectId={budget.id}
            state={budget.approval_state}
            submit={contractsApi.submitBudget}
            invalidate={[
              ['contracts', 'budgets'],
              ['contracts', 'budget', budgetId],
            ]}
            size="default"
            // Карточка объекта — единственное место, где ссылка на
            // согласование нужна и у решённого объекта: там кнопка
            // «Вернуть на доработку», без которой он заперт навсегда.
            showProcessLink
          />
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('contracts.budget.money')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FieldGrid>
            <Field label={t('contracts.columns.allocated')} hint={t('contracts.budget.allocatedHint')}>
              <span className="text-lg font-semibold tabular-nums">
                {formatMoney(budget.allocated, budget.currency)}
              </span>
            </Field>
            <Field
              label={t('contracts.columns.contracted')}
              hint={t('contracts.budget.contractedHint')}
            >
              <span className="text-lg font-semibold tabular-nums">
                {formatAmount(budget.committed)}
              </span>
            </Field>
            <Field label={t('contracts.columns.remaining')} hint={t('contracts.budget.remainingHint')}>
              <span
                className={`text-lg font-semibold tabular-nums ${remainingTone(
                  budget.remaining,
                  budget.allocated,
                )}`}
              >
                {formatAmount(budget.remaining)}
              </span>
            </Field>
          </FieldGrid>
          <Progress value={committedPercent(budget.committed, budget.allocated)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {t('contracts.budget.programmes')}
            <span className="ml-2 font-normal text-muted-foreground">
              {budget.lines.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('contracts.columns.programme')}</TableHead>
                  <TableHead>{t('contracts.columns.expenseItem')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.allocated')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.contracted')}</TableHead>
                  <TableHead className="text-right">{t('contracts.columns.remaining')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {budget.lines.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      {row.program_name}
                      {row.note && (
                        <span className="block text-xs text-muted-foreground">
                          {row.note}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{row.expense_item}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">
                      {formatAmount(row.amount)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">
                      {formatAmount(row.committed)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums whitespace-nowrap ${remainingTone(
                        row.remaining,
                        row.amount,
                      )}`}
                    >
                      {formatAmount(row.remaining)}
                    </TableCell>
                  </TableRow>
                ))}
                {/* Итог повторяет карточку «Деньги» выше, но здесь он на
                    своём месте: колонка сумм должна сходиться под самой
                    колонкой, а не только в шапке страницы. */}
                <TableRow className="border-t-2 font-semibold">
                  <TableCell colSpan={2}>{t('contracts.columns.total')}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {formatAmount(budget.allocated)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {formatAmount(budget.committed)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {formatAmount(budget.remaining)}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('contracts.columns.budget')}</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGrid>
            <Field label={t('contracts.columns.administrator')}>{budget.administrator_name}</Field>
            <Field label={t('contracts.columns.year')}>
              <span className="tabular-nums">{budget.period_year}</span>
            </Field>
            <Field label={t('contracts.columns.currency')}>{budget.currency}</Field>
            <Field label={t('contracts.columns.note')}>{budget.note || '—'}</Field>
            <Field label={t('contracts.createdAt')}>{formatMoment(budget.created_at)}</Field>
            <Field label={t('contracts.updatedAt')}>{formatMoment(budget.updated_at)}</Field>
          </FieldGrid>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {t('contracts.budget.agreements')}
            <span className="ml-2 font-normal text-muted-foreground">
              {agreements.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {agreements.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              {t('contracts.budget.noAgreements')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('contracts.columns.number')}</TableHead>
                    <TableHead>{t('contracts.columns.title')}</TableHead>
                    <TableHead>{t('contracts.columns.programme')}</TableHead>
                    <TableHead>{t('contracts.columns.counterparty')}</TableHead>
                    <TableHead className="text-right">{t('contracts.columns.amount')}</TableHead>
                    <TableHead>{t('contracts.columns.status')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {agreements.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium whitespace-nowrap">
                        <Link
                          to={`/contracts/agreements/${row.id}`}
                          className="hover:underline underline-offset-2"
                        >
                          {row.number}
                        </Link>
                      </TableCell>
                      <TableCell>{row.name}</TableCell>
                      {/* В бюджете несколько программ — без этой колонки
                          непонятно, из какой взяты деньги. */}
                      <TableCell>{row.program_name}</TableCell>
                      <TableCell>{row.counterparty_name}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">
                        {formatAmount(row.amount)}
                        {/* Черновик и расторгнутый договор в остатке не
                            участвуют — без пометки строка выглядела бы
                            как расхождение с «законтрактовано». */}
                        {!isCommitting(row.status) && (
                          <span
                            className="ml-1.5 text-xs text-muted-foreground"
                            title={t('contracts.budget.notConsumingTitle')}
                          >
                            {t('contracts.budget.notConsuming')}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {agreementStatusLabel(row.status)}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {!embedded && (
        <SubjectProcesses subjectType="contracts.budget" subjectId={budget.id} />
      )}
    </div>
  );
};

export default BudgetDetailView;
