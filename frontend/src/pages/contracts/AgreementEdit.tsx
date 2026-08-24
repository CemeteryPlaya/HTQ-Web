import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, FileText, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
import type {
  Agreement,
  BudgetLineFlat,
  ContractsEnums,
  Counterparty,
  PaymentType,
} from '@/types/contracts';

/**
 * Правка договора.
 *
 * Тот же каскад «администратор → программа → год» и те же поля, что в форме
 * оформления, но БЕЗ статуса и файла: статус двигают своей кнопкой в карточке
 * (через таблицу переходов), скан там же меняется. PATCH-схема
 * `AgreementUpdate` статус намеренно не принимает.
 *
 * Строки берутся ПЛОСКИМ списком целиком (не только согласованные, как в
 * форме создания): у правящегося договора уже есть строка-источник, и её
 * нужно показать в каскаде, даже если её бюджет с тех пор перестал попадать
 * в фильтр. Финальную проверку остатка и статусов всё равно делает бэкенд.
 *
 * Загрузчик и форма разделены, как в `InvoiceEdit`: `<Select>` встаёт с
 * нужным значением, только если оно есть с первого рендера.
 */

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

/** Сравнение денежных строк без float — в целых копейках. */
function toKopecks(value: string): bigint {
  const [whole, fraction = '0'] = value.replace(',', '.').split('.');
  return BigInt(whole || '0') * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
}

type Errors = Record<string, string>;

const AgreementEdit = () => {
  const { id } = useParams<{ id: string }>();
  const agreementId = Number(id);

  const { data: agreement, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'agreement', agreementId],
    queryFn: () => contractsApi.getAgreement(agreementId).then((r) => r.data),
    enabled: Number.isFinite(agreementId),
  });
  const { data: lines = [], isLoading: linesLoading } = useQuery({
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

  const backTo = `/contracts/agreements/${agreementId}`;
  const loading =
    isLoading || !agreement || linesLoading || counterpartiesLoading || !enums;

  return (
    <ContractsShell>
      <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to={backTo}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К карточке договора
          </Link>
          <div className="flex items-center gap-3">
            <FileText className="h-7 w-7 text-muted-foreground" />
            <h1 className="text-3xl font-bold">Правка договора</h1>
          </div>
        </div>

        {isError ? (
          <p className="text-sm text-destructive">Договор не найден или недоступен.</p>
        ) : loading ? (
          <div className="space-y-4">
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-56 w-full" />
          </div>
        ) : (
          <AgreementEditForm
            agreement={agreement}
            lines={lines}
            counterparties={counterparties}
            enums={enums}
          />
        )}
      </div>
    </ContractsShell>
  );
};

interface FormProps {
  agreement: Agreement;
  lines: BudgetLineFlat[];
  counterparties: Counterparty[];
  enums: ContractsEnums;
}

/** Тело формы. Монтируется только с готовыми данными — состояние
 *  инициализируется прямо из них (см. докстринг загрузчика). */
const AgreementEditForm = ({ agreement, lines, counterparties, enums }: FormProps) => {
  const agreementId = agreement.id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [administratorId, setAdministratorId] = useState(String(agreement.administrator_id));
  const [programId, setProgramId] = useState(String(agreement.program_id));
  const [lineId, setLineId] = useState(String(agreement.budget_line_id));
  const [counterpartyId, setCounterpartyId] = useState(String(agreement.counterparty_id));
  const [number, setNumber] = useState(agreement.number);
  const [name, setName] = useState(agreement.name);
  const [amount, setAmount] = useState(agreement.amount);
  const [paymentType, setPaymentType] = useState<PaymentType>(agreement.payment_type);
  const [signedDate, setSignedDate] = useState(agreement.signed_date ?? '');
  const [errors, setErrors] = useState<Errors>({});

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

  // Занимает ли договор бюджет в своём текущем статусе. Статус на этой форме
  // не меняется, поэтому берётся как есть.
  const committingStatuses = enums.committing_statuses;
  const willCommit = committingStatuses.includes(agreement.status);

  // Собственная старая сумма договора уже сидит в `committed` строки, если он
  // её занимает; чтобы не считать её чужой занятостью (как делает бэкенд через
  // exclude_agreement_id), возвращаем её в остаток при сравнении.
  const ownOnLine =
    willCommit && String(agreement.budget_line_id) === lineId
      ? toKopecks(agreement.amount)
      : 0n;
  const effectiveRemaining = selectedLine
    ? toKopecks(selectedLine.remaining) + ownOnLine
    : null;
  const amountKopecks =
    amount.trim() && AMOUNT_RE.test(amount.trim()) ? toKopecks(amount.trim()) : null;
  const overBudget =
    willCommit &&
    effectiveRemaining !== null &&
    amountKopecks !== null &&
    amountKopecks > effectiveRemaining;

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
    if (!counterpartyId) next.counterparty = 'Выберите контрагента';
    if (!number.trim()) next.number = 'Укажите номер договора';
    if (!name.trim()) next.name = 'Укажите наименование договора';
    if (!amount.trim()) next.amount = 'Укажите сумму договора';
    else if (!AMOUNT_RE.test(amount.trim())) {
      next.amount = 'Сумма — число, максимум два знака после запятой';
    } else if (toKopecks(amount.trim()) === 0n) {
      next.amount = 'Сумма должна быть больше нуля';
    }
    return next;
  };

  const mutation = useMutation({
    mutationFn: () =>
      contractsApi
        .updateAgreement(agreementId, {
          number: number.trim(),
          name: name.trim(),
          budget_line_id: Number(lineId),
          counterparty_id: Number(counterpartyId),
          amount: amount.trim().replace(',', '.'),
          payment_type: paymentType,
          currency: selectedLine!.currency,
          // Пустую дату не шлём: PATCH трактует отсутствие как «не менять», а
          // пустая строка не разберётся в date и вернёт 422.
          signed_date: signedDate || null,
        })
        .then((r) => r.data),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(`Договор ${row.number} сохранён`);
      navigate(`/contracts/agreements/${agreementId}`);
    },
    onError: (error: unknown) => {
      const err = error as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const httpStatus = err.response?.status;
      const detail = err.response?.data?.detail;
      // 409 — дубль номера, превышение остатка, закрытый бюджет, заблокированный
      // контрагент или запертый согласованием договор; 403 — правит не
      // администратор. Тексты с бэкенда осмысленные.
      if ((httpStatus === 409 || httpStatus === 403) && typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item) => (item as { msg?: string }).msg).join('; '));
        return;
      }
      toast.error('Не удалось сохранить договор');
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

  const backTo = `/contracts/agreements/${agreementId}`;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* ─── Источник финансирования ─────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Источник финансирования</CardTitle>
          <CardDescription>
            Администратор и программа вместе определяют бюджетную строку, с
            которой спишется договор.
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
                    placeholder={administratorId ? 'Выберите' : 'Сначала администратор'}
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
                <span className="text-muted-foreground">Выделено</span>
                <span className="tabular-nums">
                  {formatAmount(selectedLine.amount)} {selectedLine.currency}
                </span>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <span className="text-muted-foreground">Законтрактовано</span>
                <span className="tabular-nums">{formatAmount(selectedLine.committed)}</span>
              </div>
              <div className="mt-1 flex flex-wrap justify-between gap-2 border-t pt-1 font-medium">
                <span>Остаток</span>
                <span className="tabular-nums">{formatAmount(selectedLine.remaining)}</span>
              </div>
              {willCommit && ownOnLine > 0n && (
                <p className="text-xs text-muted-foreground mt-2">
                  Текущая сумма этого договора уже учтена в «законтрактовано» —
                  при правке она в остаток не засчитывается дважды.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ─── Договор ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Договор</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="number">Номер договора</Label>
              <Input
                id="number"
                value={number}
                onChange={(event) => setNumber(event.target.value)}
                className={errors.number ? 'border-destructive' : undefined}
              />
              {fieldError('number')}
            </div>
            <div>
              <Label htmlFor="counterparty">Контрагент</Label>
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
          </div>

          <div>
            <Label htmlFor="name">Наименование договора</Label>
            <Input
              id="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className={errors.name ? 'border-destructive' : undefined}
            />
            {fieldError('name')}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <Label htmlFor="amount">Сумма договора</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="amount"
                  inputMode="decimal"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className={errors.amount || overBudget ? 'border-destructive' : undefined}
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
              <Label htmlFor="payment-type">Тип оплаты</Label>
              <Select
                value={paymentType}
                onValueChange={(value) => setPaymentType(value as PaymentType)}
              >
                <SelectTrigger id="payment-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {enums.payment_type.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="signed-date">Дата подписания</Label>
              <Input
                id="signed-date"
                type="date"
                value={signedDate}
                onChange={(event) => setSignedDate(event.target.value)}
              />
            </div>
          </div>

          {overBudget && selectedLine && (
            <div className="flex gap-2 rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm">
              <AlertTriangle className="h-4 w-4 shrink-0 text-destructive mt-0.5" />
              <div>
                Сумма превышает остаток бюджета этой строки. Договор в текущем
                статусе занимает бюджет — сохранение упрётся в лимит на бэкенде.
              </div>
            </div>
          )}
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
  );
};

export default AgreementEdit;
