import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Receipt } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { formatAmount } from '@/components/contracts/format';
import { contractsApi } from '@/api/contracts';
import type { BudgetLineFlat } from '@/types/contracts';

/**
 * Правка счёта на оплату.
 *
 * Тот же каскад «администратор → программа → год» и те же поля, что в форме
 * выписки, но БЕЗ файла и статуса: скан меняется из карточки, статус — своей
 * кнопкой. Правит автор свой черновик либо администратор — бэкенд проверяет
 * это сам (`views.InvoiceDetailView.patch`), форма лишь показывает то же
 * право кнопкой «Редактировать» в карточке.
 *
 * Файла среди полей нет намеренно: он обязателен при СОЗДАНИИ, а правка — это
 * уже существующий счёт, у которого скан приложен; замена скана живёт в
 * карточке.
 */

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

type Errors = Record<string, string>;

const InvoiceEdit = () => {
  const { id } = useParams<{ id: string }>();
  const invoiceId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: invoice, isLoading: invoiceLoading, isError } = useQuery({
    queryKey: ['contracts', 'invoice', invoiceId],
    queryFn: () => contractsApi.getInvoice(invoiceId).then((r) => r.data),
    enabled: Number.isFinite(invoiceId),
  });
  const { data: lines = [], isLoading: linesLoading } = useQuery({
    queryKey: ['contracts', 'budget-lines', 'all'],
    queryFn: () => contractsApi.listBudgetLines().then((r) => r.data),
  });
  const { data: counterparties = [], isLoading: counterpartiesLoading } = useQuery({
    queryKey: ['contracts', 'counterparties', ''],
    queryFn: () => contractsApi.listCounterparties().then((r) => r.data),
  });

  const [administratorId, setAdministratorId] = useState('');
  const [programId, setProgramId] = useState('');
  const [lineId, setLineId] = useState('');
  const [counterpartyId, setCounterpartyId] = useState('');
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [amount, setAmount] = useState('');
  const [errors, setErrors] = useState<Errors>({});

  // Форма засевается из загруженного счёта ровно ОДИН раз: повторный
  // refetch (например, после инвалидции) не должен затирать уже начатые
  // правки.
  //
  // Ждём ЗАГРУЗКИ справочников (`lines`, `counterparties`), а не только
  // самого счёта: значение <Select> отображается лишь тогда, когда среди
  // отрисованных пунктов есть совпадающий. Засей мы раньше — Radix показал бы
  // плейсхолдер («Выберите»), потому что списка вариантов ещё нет, и поля
  // администратора, программы и поставщика остались бы пустыми на вид.
  const seeded = useRef(false);
  useEffect(() => {
    if (invoice && lines.length > 0 && counterparties.length > 0 && !seeded.current) {
      setAdministratorId(String(invoice.administrator_id));
      setProgramId(String(invoice.program_id));
      setLineId(String(invoice.budget_line_id));
      setCounterpartyId(String(invoice.counterparty_id));
      setName(invoice.name);
      setNote(invoice.note);
      setAmount(invoice.amount);
      seeded.current = true;
    }
  }, [invoice, lines, counterparties]);

  const administrators = useMemo(() => {
    const seen = new Map<number, string>();
    lines.forEach((row) => seen.set(row.administrator_id, row.administrator_name));
    return [...seen].map(([aid, label]) => ({ id: aid, label }));
  }, [lines]);

  const programs = useMemo(() => {
    if (!administratorId) return [];
    const seen = new Map<number, BudgetLineFlat>();
    lines
      .filter((row) => String(row.administrator_id) === administratorId)
      .forEach((row) => seen.set(row.program_id, row));
    return [...seen].map(([pid, row]) => ({
      id: pid,
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
    mutationFn: () =>
      contractsApi
        .updateInvoice(invoiceId, {
          name: name.trim(),
          note: note.trim(),
          budget_line_id: Number(lineId),
          counterparty_id: Number(counterpartyId),
          amount: amount.trim().replace(',', '.'),
        })
        .then((r) => r.data),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(`Счёт «${updated.name}» сохранён`);
      navigate(`/contracts/invoices/${invoiceId}`);
    },
    onError: (error: unknown) => {
      const err = error as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const httpStatus = err.response?.status;
      const detail = err.response?.data?.detail;
      if ((httpStatus === 409 || httpStatus === 403) && typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(
          detail.map((item) => (item as { msg?: string }).msg).join('; '),
        );
        return;
      }
      toast.error('Не удалось сохранить счёт');
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

  const backTo = `/contracts/invoices/${invoiceId}`;

  return (
    <ContractsShell>
      <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to={backTo}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К карточке счёта
          </Link>
          <div className="flex items-center gap-3">
            <Receipt className="h-7 w-7 text-muted-foreground" />
            <h1 className="text-3xl font-bold">Правка счёта</h1>
          </div>
        </div>

        {isError ? (
          <p className="text-sm text-destructive">Счёт не найден или недоступен.</p>
        ) : invoiceLoading || !invoice || linesLoading || counterpartiesLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-56 w-full" />
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* ─── Источник финансирования ─────────────────────────────── */}
            <Card>
              <CardHeader>
                <CardTitle>Источник финансирования</CardTitle>
                <CardDescription>
                  Администратор и программа вместе определяют бюджетную строку,
                  из которой оплачивается счёт.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="administrator">Администратор бюджета</Label>
                    <Select
                      value={administratorId}
                      onValueChange={chooseAdministrator}
                      disabled={administrators.length === 0}
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
                    <div className="flex flex-wrap justify-between gap-2 font-medium">
                      <span>Остаток строки</span>
                      <span className="tabular-nums">
                        {formatAmount(selectedLine.remaining)} {selectedLine.currency}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Счёт без договора остаток не уменьшает — показан для справки.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* ─── Счёт ────────────────────────────────────────────────── */}
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
                    disabled={counterparties.length === 0}
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
                    rows={3}
                  />
                </div>

                <div className="sm:w-1/2">
                  <Label htmlFor="amount">Сумма счёта</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
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
              </CardContent>
            </Card>

            <div className="flex gap-3">
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Сохранить
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(backTo)}
                disabled={mutation.isPending}
              >
                Отмена
              </Button>
            </div>
          </form>
        )}
      </div>
    </ContractsShell>
  );
};

export default InvoiceEdit;
