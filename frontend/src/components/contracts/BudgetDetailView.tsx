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
import { Pencil, Wallet } from 'lucide-react';

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
import { Button } from '@/components/ui/button';
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
import { usePermissions } from '@/hooks/usePermissions';
import type { AgreementStatus } from '@/types/contracts';
import { isEditableState } from '@/types/signoff';


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
  const enabled = Number.isFinite(budgetId);

  const permissions = usePermissions();
  const isAdmin = permissions.atLeast('contracts', 'admin');

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

  const { data: invoices = [] } = useQuery({
    queryKey: ['contracts', 'invoices', { budgetId }],
    queryFn: () => contractsApi.listInvoices({ budget_id: budgetId }).then((r) => r.data),
    enabled,
  });

  const { data: accountableRequests = [] } = useQuery({
    queryKey: ['contracts', 'accountable-funds-requests', { budgetId }],
    queryFn: () => contractsApi.listAccountableFundsRequests({ budget_id: budgetId }).then((r) => r.data),
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
  const invoiceStatusLabel = (value: string) =>
    enums?.invoice_status.find((option) => option.value === value)?.label ?? value;

  /** Занимает ли договор бюджет — множество приходит с бэкенда
   *  (`budget_calc.COMMITTING_STATUSES`), здесь его копии нет. */
  const isCommitting = (status: AgreementStatus) =>
    enums?.committing_statuses.includes(status) ?? false;
  const isInvoiceCommitting = (status: string) => status === 'approved' || status === 'paid';
  const isAccountableCommitting = (status: string) => status !== 'draft';

  if (isLoading) return <DetailSkeleton />;
  if (isError || !budget) {
    return (
      <p className="text-sm text-destructive">Бюджет не найден или недоступен.</p>
    );
  }

  // Правка шапки бюджета — админская (`BudgetDetailView.patch` — admin=True) и
  // только пока бюджет редактируем по оси согласования (`assert_editable`),
  // иначе сохранение упрётся в 409. Гасим кнопку заранее.
  const canEdit = isAdmin && isEditableState(budget.approval_state);

  // На странице процесса `h1` уже занят самим согласованием.
  const Heading = embedded ? 'h2' : 'h1';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <Wallet className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold">
              Бюджет {budget.period_year}
            </Heading>
            <Badge variant={budget.status === 'active' ? 'secondary' : 'outline'}>
              {budgetStatusLabel(budget.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {budget.administrator_name} · {budget.lines.length}{' '}
            {budget.lines.length === 1
              ? 'программа'
              : budget.lines.length < 5
                ? 'программы'
                : 'программ'}
          </p>
        </div>

        {!embedded && (
          <div className="flex flex-wrap items-center gap-2">
            {canEdit && (
              <Button asChild variant="outline">
                <Link to={`/contracts/budgets/${budget.id}/edit`}>
                  <Pencil className="mr-1.5 h-4 w-4" />
                  Редактировать
                </Link>
              </Button>
            )}
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
          </div>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Деньги</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FieldGrid>
            <Field label="Выделено" hint="Сумма по всем программам бюджета">
              <span className="text-lg font-semibold tabular-nums">
                {formatMoney(budget.allocated, budget.currency)}
              </span>
            </Field>
            <Field
              label="Законтрактовано"
              hint="Сумма договоров бюджета в статусах, занимающих его"
            >
              <span className="text-lg font-semibold tabular-nums">
                {formatAmount(budget.committed)}
              </span>
            </Field>
            <Field label="Остаток" hint="Выделено минус законтрактовано">
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
            Программы
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
                  <TableHead>Программа</TableHead>
                  <TableHead>Статья расходов</TableHead>
                  <TableHead className="text-right">Выделено</TableHead>
                  <TableHead className="text-right">Законтрактовано</TableHead>
                  <TableHead className="text-right">Остаток</TableHead>
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
                  <TableCell colSpan={2}>Итого</TableCell>
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
          <CardTitle className="text-base">Сведения о бюджете</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <section>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Параметры
            </p>
            <div className="mt-3">
              <FieldGrid>
                <Field label="Администратор">{budget.administrator_name}</Field>
                <Field label="Год">
                  <span className="tabular-nums">{budget.period_year}</span>
                </Field>
                <Field label="Валюта">{budget.currency}</Field>
                <Field label="Примечание" className="sm:col-span-2">
                  {budget.note || '—'}
                </Field>
              </FieldGrid>
            </div>
          </section>
          <section className="border-t pt-5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Сведения о записи
            </p>
            <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label="Создан">{formatMoment(budget.created_at)}</Field>
              <Field label="Изменён">{formatMoment(budget.updated_at)}</Field>
            </dl>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Договоры бюджета
            <span className="ml-2 font-normal text-muted-foreground">
              {agreements.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {agreements.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              К программам этого бюджета ещё не привязан ни один договор.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Номер</TableHead>
                    <TableHead>Наименование</TableHead>
                    <TableHead>Программа</TableHead>
                    <TableHead>Контрагент</TableHead>
                    <TableHead className="text-right">Сумма</TableHead>
                    <TableHead>Статус</TableHead>
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
                            title="Договор в этом статусе бюджет не занимает"
                          >
                            вне остатка
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

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Счета без договора
            <span className="ml-2 font-normal text-muted-foreground">{invoices.length}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {invoices.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">По этому бюджету счетов без договора пока нет.</p>
          ) : <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Наименование</TableHead><TableHead>Программа</TableHead><TableHead>Контрагент</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Статус</TableHead></TableRow></TableHeader><TableBody>
            {invoices.map((invoice) => <TableRow key={invoice.id}><TableCell className="font-medium"><Link to={`/contracts/invoices/${invoice.id}`} className="hover:underline underline-offset-2">{invoice.name}</Link></TableCell><TableCell>{invoice.program_name}</TableCell><TableCell>{invoice.counterparty_name}</TableCell><TableCell className="text-right tabular-nums whitespace-nowrap">{formatAmount(invoice.amount)} {!isInvoiceCommitting(invoice.status) && <span className="ml-1.5 text-xs text-muted-foreground" title="Счёт в этом статусе бюджет не занимает">вне остатка</span>}</TableCell><TableCell><Badge variant="outline">{invoiceStatusLabel(invoice.status)}</Badge></TableCell></TableRow>)}
          </TableBody></Table></div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Подотчётные средства
            <span className="ml-2 font-normal text-muted-foreground">{accountableRequests.length}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {accountableRequests.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">По этому бюджету заявок на подотчётные средства пока нет.</p>
          ) : <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Цель</TableHead><TableHead>Программа</TableHead><TableHead>Инициатор</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead className="text-right">Подтверждено</TableHead><TableHead>Статус</TableHead></TableRow></TableHeader><TableBody>
            {accountableRequests.map((request) => <TableRow key={request.id}><TableCell className="font-medium"><Link to={`/contracts/accountable-funds-requests/${request.id}`} className="hover:underline underline-offset-2">{request.goal}</Link></TableCell><TableCell>{request.program_name}</TableCell><TableCell>Пользователь #{request.accountable_user_id}</TableCell><TableCell className="text-right tabular-nums whitespace-nowrap">{formatAmount(request.amount)} {!isAccountableCommitting(request.status) && <span className="ml-1.5 text-xs text-muted-foreground" title="Черновик бюджет не занимает">вне остатка</span>}</TableCell><TableCell className="text-right tabular-nums whitespace-nowrap">{formatAmount(request.advance_reported_amount)}</TableCell><TableCell><Badge variant={request.status === 'closed' ? 'default' : 'outline'}>{request.status === 'draft' ? 'Черновик' : request.status === 'on_review' ? 'На согласовании' : request.status === 'awaiting_accounting' ? 'Ожидает оплаты' : request.status === 'awaiting_advance_report' ? 'Ожидает отчёт' : 'Закрыта'}</Badge></TableCell></TableRow>)}
          </TableBody></Table></div>}
        </CardContent>
      </Card>

      {!embedded && (
        <SubjectProcesses subjectType="contracts.budget" subjectId={budget.id} />
      )}
    </div>
  );
};

export default BudgetDetailView;
