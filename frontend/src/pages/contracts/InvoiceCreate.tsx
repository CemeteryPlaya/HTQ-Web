import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Paperclip, Receipt } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { formatAmount } from '@/components/contracts/format';
import { contractsApi } from '@/api/contracts';
import type { BudgetLineFlat, InvoiceStatus } from '@/types/contracts';

/**
 * Выписка счёта на оплату (без договора).
 *
 * Источник финансирования выбирается тем же каскадом «администратор →
 * программа → год», что и в форме договора, и на бэкенд уходит один
 * `budget_line_id`: строка бюджета и есть «программа такого-то проекта».
 *
 * Отличия от формы договора:
 * - нет номера, типа оплаты и даты подписания;
 * - валюту не вводят — её снимает бэкенд со строки бюджета (показываем её
 *   рядом с суммой справочно);
 * - остаток строки показывается как контекст, но БЕЗ предупреждения о
 *   превышении: счёт бюджет не занимает, и бэкенд не проверяет лимит (первая
 *   фаза, см. модель Invoice). Поэтому сумму больше остатка форма не
 *   блокирует.
 *
 * Список строк НЕ фильтруется по согласованности (в отличие от договоров):
 * согласование бюджета — отдельный контур, и пока маршрутов нет, все бюджеты
 * в состоянии `draft`; фильтр по `approved` оставил бы список пустым. Если
 * маршрут бюджета всё же настроен, несогласованный источник отобьёт бэкенд
 * понятным 409.
 */

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

type Errors = Record<string, string>;

const InvoiceCreate = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: lines = [], isLoading: budgetsLoading } = useQuery({
    queryKey: ['contracts', 'budget-lines', 'all'],
    queryFn: () => contractsApi.listBudgetLines().then((r) => r.data),
  });
  const { data: counterparties = [], isLoading: counterpartiesLoading } = useQuery({
    queryKey: ['contracts', 'counterparties', ''],
    queryFn: () => contractsApi.listCounterparties().then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  const [administratorId, setAdministratorId] = useState<string>('');
  const [programId, setProgramId] = useState<string>('');
  const [lineId, setLineId] = useState<string>('');
  const [counterpartyId, setCounterpartyId] = useState<string>('');
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [amount, setAmount] = useState('');
  const [status, setStatus] = useState<InvoiceStatus>('draft');
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Errors>({});

  // Каскадные списки строятся из строк бюджета: выбирать можно только те
  // администратора и программу, под которые бюджет реально заведён.
  const administrators = useMemo(() => {
    const seen = new Map<number, string>();
    lines.forEach((row) => seen.set(row.administrator_id, row.administrator_name));
    return [...seen].map(([id, label]) => ({ id, label }));
  }, [lines]);

  const programs = useMemo(() => {
    if (!administratorId) return [];
    const seen = new Map<number, BudgetLineFlat>();
    lines
      .filter((row) => String(row.administrator_id) === administratorId)
      .forEach((row) => seen.set(row.program_id, row));
    return [...seen].map(([id, row]) => ({
      id,
      label: row.program_name,
      hint: row.expense_item,
    }));
  }, [lines, administratorId]);

  const yearOptions = useMemo(() => {
    if (!administratorId || !programId) return [];
    return lines
      .filter(
        (row) =>
          String(row.administrator_id) === administratorId &&
          String(row.program_id) === programId,
      )
      .sort((a, b) => b.period_year - a.period_year);
  }, [lines, administratorId, programId]);

  const selectedLine = lines.find((row) => String(row.id) === lineId);

  const chooseAdministrator = (value: string) => {
    setAdministratorId(value);
    setProgramId('');
    setLineId('');
  };

  const chooseProgram = (value: string) => {
    setProgramId(value);
    const matching = lines
      .filter(
        (row) =>
          String(row.administrator_id) === administratorId &&
          String(row.program_id) === value,
      )
      .sort((a, b) => b.period_year - a.period_year);
    setLineId(matching.length === 1 ? String(matching[0].id) : '');
  };

  const validate = (): Errors => {
    const next: Errors = {};
    if (!administratorId) next.administrator = 'Выберите администратора бюджета';
    else if (!programId) next.program = 'Выберите программу';
    else if (!lineId) next.budget = 'Выберите бюджетный год';
    if (!counterpartyId) next.counterparty = 'Выберите поставщика';
    if (!name.trim()) next.name = 'Укажите наименование';
    if (!amount.trim()) next.amount = 'Укажите сумму счёта';
    else if (!AMOUNT_RE.test(amount.trim())) {
      next.amount = 'Сумма — число, максимум два знака после запятой';
    } else if (amount.trim().replace(/[.,]/g, '').replace(/^0+/, '') === '') {
      next.amount = 'Сумма должна быть больше нуля';
    }
    return next;
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const invoice = await contractsApi
        .createInvoice({
          name: name.trim(),
          note: note.trim(),
          budget_line_id: Number(lineId),
          counterparty_id: Number(counterpartyId),
          amount: amount.trim().replace(',', '.'),
          status,
        })
        .then((r) => r.data);

      // Файл — вторым запросом на отдельный multipart-эндпоинт. Сбой на
      // файле НЕ откатывает счёт: он уже создан, скан можно приложить из
      // карточки позже.
      if (file) {
        try {
          await contractsApi.uploadInvoiceFile(invoice.id, file);
        } catch {
          toast.warning(
            `Счёт «${invoice.name}» создан, но файл приложить не удалось — попробуйте ещё раз из карточки.`,
          );
        }
      }
      return invoice;
    },
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(`Счёт «${invoice.name}» выписан`);
      navigate('/contracts/invoices');
    },
    onError: (error: unknown) => {
      const err = error as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const httpStatus = err.response?.status;
      const detail = err.response?.data?.detail;
      if (httpStatus === 409 && typeof detail === 'string') {
        // Закрытый бюджет, заблокированный/несогласованный контрагент —
        // тексты с бэкенда осмысленные.
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(
          detail.map((item) => (item as { msg?: string }).msg).join('; '),
        );
        return;
      }
      toast.error('Не удалось выписать счёт');
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error('Проверьте заполнение формы');
      return;
    }
    mutation.mutate();
  };

  const fieldError = (key: string) =>
    errors[key] ? <p className="text-sm text-destructive mt-1">{errors[key]}</p> : null;

  const noBudgets = !budgetsLoading && lines.length === 0;
  const noCounterparties = !counterpartiesLoading && counterparties.length === 0;

  return (
    <ContractsShell>
      <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to="/contracts/invoices"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К списку счетов
          </Link>
          <div className="flex items-center gap-3">
            <Receipt className="h-7 w-7 text-muted-foreground" />
            <div>
              <h1 className="text-3xl font-bold">Новый счёт на оплату</h1>
              <p className="text-muted-foreground text-sm mt-1">
                Прямая закупка без договора — оплата по одной бюджетной строке.
              </p>
            </div>
          </div>
        </div>

        {(noBudgets || noCounterparties) && (
          <Card className="mb-6 border-amber-500/50">
            <CardContent className="pt-6 text-sm">
              <p className="font-medium mb-2">Сначала нужны справочники:</p>
              <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
                {noBudgets && (
                  <li>
                    Нет ни одного бюджета —{' '}
                    <Link to="/contracts/budgets/new" className="underline">
                      создайте бюджетную строку
                    </Link>
                    .
                  </li>
                )}
                {noCounterparties && (
                  <li>
                    Реестр контрагентов пуст —{' '}
                    <Link to="/contracts/counterparties/new" className="underline">
                      добавьте поставщика
                    </Link>
                    .
                  </li>
                )}
              </ul>
            </CardContent>
          </Card>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* ─── Источник финансирования ───────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Источник финансирования</CardTitle>
              <CardDescription>
                Администратор и программа вместе определяют бюджетную строку, из
                которой оплачивается счёт.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="administrator">Администратор бюджета</Label>
                  <Select
                    value={administratorId}
                    onValueChange={chooseAdministrator}
                    disabled={budgetsLoading || administrators.length === 0}
                  >
                    <SelectTrigger
                      id="administrator"
                      className={errors.administrator ? 'border-destructive' : undefined}
                    >
                      <SelectValue placeholder="Выберите" />
                    </SelectTrigger>
                    <SelectContent>
                      {administrators.map((row) => (
                        <SelectItem key={row.id} value={String(row.id)}>
                          {row.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {fieldError('administrator')}
                </div>

                <div>
                  <Label htmlFor="program">Программа</Label>
                  <Select
                    value={programId}
                    onValueChange={chooseProgram}
                    disabled={!administratorId}
                  >
                    <SelectTrigger
                      id="program"
                      className={errors.program ? 'border-destructive' : undefined}
                    >
                      <SelectValue
                        placeholder={
                          administratorId ? 'Выберите' : 'Сначала администратор'
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {programs.map((row) => (
                        <SelectItem key={row.id} value={String(row.id)}>
                          {row.label} — {row.hint}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {fieldError('program')}
                </div>
              </div>

              {yearOptions.length > 1 && (
                <div className="sm:w-48">
                  <Label htmlFor="budget-year">Бюджетный год</Label>
                  <Select value={lineId} onValueChange={setLineId}>
                    <SelectTrigger
                      id="budget-year"
                      className={errors.budget ? 'border-destructive' : undefined}
                    >
                      <SelectValue placeholder="Выберите" />
                    </SelectTrigger>
                    <SelectContent>
                      {yearOptions.map((row) => (
                        <SelectItem key={row.id} value={String(row.id)}>
                          {row.period_year}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {fieldError('budget')}
                </div>
              )}

              {selectedLine && (
                <div className="rounded-md border bg-muted/40 p-4 text-sm">
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="text-muted-foreground">Выделено на программу</span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.amount)} {selectedLine.currency}
                    </span>
                  </div>
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="text-muted-foreground">
                      Законтрактовано (договоры)
                    </span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.committed)}
                    </span>
                  </div>
                  <div className="flex flex-wrap justify-between gap-2 font-medium mt-1 pt-1 border-t">
                    <span>Остаток строки</span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.remaining)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-2">
                    Счёт без договора остаток не уменьшает — показан для справки.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ─── Счёт ──────────────────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Счёт</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="counterparty">Поставщик</Label>
                <Select
                  value={counterpartyId}
                  onValueChange={setCounterpartyId}
                  disabled={counterpartiesLoading || counterparties.length === 0}
                >
                  <SelectTrigger
                    id="counterparty"
                    className={errors.counterparty ? 'border-destructive' : undefined}
                  >
                    <SelectValue placeholder="Выберите из реестра" />
                  </SelectTrigger>
                  <SelectContent>
                    {counterparties.map((row) => (
                      <SelectItem key={row.id} value={String(row.id)}>
                        {row.name} — {row.bin_iin}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {fieldError('counterparty')}
              </div>

              <div>
                <Label htmlFor="name">Наименование</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Канцелярские товары"
                  className={errors.name ? 'border-destructive' : undefined}
                />
                {fieldError('name')}
              </div>

              <div>
                <Label htmlFor="note">Пояснение</Label>
                <Textarea
                  id="note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Что и для чего закупается"
                  rows={3}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="amount">Сумма счёта</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="400000.00"
                      className={errors.amount ? 'border-destructive' : undefined}
                    />
                    {selectedLine && (
                      <span className="text-sm text-muted-foreground">
                        {selectedLine.currency}
                      </span>
                    )}
                  </div>
                  {fieldError('amount')}
                </div>

                <div>
                  <Label htmlFor="status">Статус</Label>
                  <Select
                    value={status}
                    onValueChange={(value) => setStatus(value as InvoiceStatus)}
                  >
                    <SelectTrigger id="status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {/* «Оплачен»/«Отменён» при создании не предлагаем — это
                          состояния уже прожитого счёта. */}
                      {(enums?.invoice_status ?? [])
                        .filter(
                          (option) => !['paid', 'cancelled'].includes(option.value),
                        )
                        .map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label htmlFor="file">Скан счёта на оплату</Label>
                <Input
                  id="file"
                  type="file"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                {file && (
                  <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                    <Paperclip className="h-3 w-3" />
                    {file.name}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-3">
            <Button type="submit" disabled={mutation.isPending || noBudgets}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Выписать счёт
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate('/contracts/invoices')}
              disabled={mutation.isPending}
            >
              Отмена
            </Button>
          </div>
        </form>
      </div>
    </ContractsShell>
  );
};

export default InvoiceCreate;
