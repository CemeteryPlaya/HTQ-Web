import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, FileText, Loader2, Paperclip } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { contractsApi } from '@/api/contracts';
import type { AgreementStatus, BudgetLineFlat, PaymentType } from '@/types/contracts';
import { useTranslation } from 'react-i18next';

/**
 * Оформление договора.
 *
 * Ключевая механика — выбор источника финансирования. В спецификации у
 * договора отдельные поля «администратор» и «программа», и форма их так и
 * показывает (два каскадных списка), но на бэкенд уходит ОДИН
 * `budget_line_id`: строка бюджета и есть «программа такого-то проекта за
 * такой-то год». Хранить на договоре и администратора, и программу значило
 * бы завести две версии правды о том, из какого кармана взяты деньги.
 *
 * Списки строятся из ПЛОСКОГО списка строк (`GET /budget-lines`), а не из
 * вложенных `lines` внутри бюджетов: каскад перебирает программы всех
 * бюджетов сразу, и разворачивать для этого вложенную структуру на клиенте
 * значило бы переложить сюда же и фильтр по согласованности.
 *
 * Остаток выбранной строки показывается сразу и пересчитывается при вводе
 * суммы — чтобы превышение было видно до отправки, а не прилетало 409-ым
 * после. Финальную проверку всё равно делает бэкенд: остаток мог измениться
 * между загрузкой страницы и отправкой, и верить фронтенду в вопросах денег
 * нельзя.
 */

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

type Errors = Record<string, string>;

/** «5000000.00» → «5 000 000,00». Через Number нельзя — потеряются копейки. */
function formatAmount(value: string): string {
  const [whole, fraction = '00'] = value.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')},${fraction}`;
}

/** Сравнение денежных строк без float: в целых копейках. */
function toKopecks(value: string): bigint {
  const [whole, fraction = '0'] = value.replace(',', '.').split('.');
  return BigInt(whole || '0') * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
}

const AgreementCreate = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Только СОГЛАСОВАННЫЕ бюджеты: с несогласованного тратить нельзя, и
  // бэкенд это проверяет сам (`agreement_service._validate_context`).
  // Показывать в списке источник, который гарантированно будет отбит, —
  // значит обещать деньги, которых форма не даст потратить.
  const { data: lines = [], isLoading: budgetsLoading } = useQuery({
    queryKey: ['contracts', 'budget-lines', 'approved'],
    queryFn: () =>
      contractsApi.listBudgetLines({ approval_state: 'approved' }).then((r) => r.data),
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
  const [number, setNumber] = useState('');
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [paymentType, setPaymentType] = useState<PaymentType>('postpayment');
  const [status, setStatus] = useState<AgreementStatus>('draft');
  const [signedDate, setSignedDate] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Errors>({});

  // Списки строятся из строк бюджета, а не из справочников: выбирать можно
  // только тех администраторов и те программы, под которые бюджет реально
  // заведён и согласован. Иначе форма позволяла бы собрать пару, для которой
  // источника денег нет.
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

  // Одна программа у одного администратора может финансироваться за разные
  // годы — это разные бюджеты и разные строки, тогда нужен третий выбор.
  // Если год ровно один, он проставляется сам.
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

  const remainingKopecks = selectedLine ? toKopecks(selectedLine.remaining) : null;
  const amountKopecks =
    amount.trim() && AMOUNT_RE.test(amount.trim()) ? toKopecks(amount.trim()) : null;

  // Черновик бюджет не занимает — предупреждать о превышении для него
  // незачем, бэкенд его тоже пропустит.
  const committingStatuses = enums?.committing_statuses ?? [
    'on_review',
    'approved',
    'signed',
    'executed',
  ];
  const willCommit = committingStatuses.includes(status);
  const overBudget =
    willCommit &&
    remainingKopecks !== null &&
    amountKopecks !== null &&
    amountKopecks > remainingKopecks;

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
    // Единственный год — выбирать нечего, проставляем сразу.
    setLineId(matching.length === 1 ? String(matching[0].id) : '');
  };

  const validate = (): Errors => {
    const next: Errors = {};
    if (!administratorId) next.administrator = t('contracts.agreementForm.errors.administrator');
    else if (!programId) next.program = t('contracts.agreementForm.errors.program');
    else if (!lineId) next.budget = t('contracts.agreementForm.errors.budget');
    if (!counterpartyId) next.counterparty = t('contracts.agreementForm.errors.counterparty');
    if (!number.trim()) next.number = t('contracts.agreementForm.errors.number');
    if (!name.trim()) next.name = t('contracts.agreementForm.errors.name');
    if (!amount.trim()) next.amount = t('contracts.agreementForm.errors.amount');
    else if (!AMOUNT_RE.test(amount.trim())) {
      next.amount = t('contracts.agreementForm.errors.amountFormat');
    } else if (toKopecks(amount.trim()) === 0n) {
      next.amount = t('contracts.agreementForm.errors.amountPositive');
    }
    return next;
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const agreement = await contractsApi
        .createAgreement({
          number: number.trim(),
          name: name.trim(),
          budget_line_id: Number(lineId),
          counterparty_id: Number(counterpartyId),
          amount: amount.trim().replace(',', '.'),
          payment_type: paymentType,
          currency: selectedLine!.currency,
          signed_date: signedDate || null,
          status,
        })
        .then((r) => r.data);

      // Файл грузится вторым запросом — у бэкенда для него отдельный
      // multipart-эндпоинт. Ошибка загрузки НЕ откатывает договор: он уже
      // создан и валиден, скан можно приложить позже, и терять введённое
      // из-за сбоя на файле было бы хуже.
      if (file) {
        try {
          await contractsApi.uploadAgreementFile(agreement.id, file);
        } catch {
          toast.warning(
            t('contracts.agreementForm.createdNoFile', { number: agreement.number }),
          );
        }
      }
      return agreement;
    },
    onSuccess: (agreement) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(t('contracts.agreementForm.created', { number: agreement.number }));
      navigate('/contracts/agreements');
    },
    onError: (error: any) => {
      const httpStatus = error?.response?.status;
      const detail = error?.response?.data?.detail;
      if (httpStatus === 409 && typeof detail === 'string') {
        // Дубль номера, превышение остатка, закрытый бюджет, заблокированный
        // контрагент — тексты с бэкенда осмысленные.
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item: any) => item.msg).join('; '));
        return;
      }
      toast.error(t('contracts.agreementForm.createError'));
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error(t('contracts.formInvalid'));
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
            to="/contracts/agreements"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('contracts.agreementForm.backToList')}
          </Link>
          <div className="flex items-center gap-3">
            <FileText className="h-7 w-7 text-muted-foreground" />
            <div>
              <h1 className="text-3xl font-bold">{t('contracts.newAgreement')}</h1>
              <p className="text-muted-foreground text-sm mt-1">
                {t('contracts.agreementForm.subtitle')}
              </p>
            </div>
          </div>
        </div>

        {(noBudgets || noCounterparties) && (
          <Card className="mb-6 border-amber-500/50">
            <CardContent className="pt-6 text-sm">
              <p className="font-medium mb-2">{t('contracts.agreementForm.needReferences')}</p>
              <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
                {noBudgets && (
                  <li>
                    {t('contracts.agreementForm.noBudgets')}{' '}
                    <Link to="/contracts/budgets/new" className="underline">
                      {t('contracts.agreementForm.createBudgetLine')}
                    </Link>
                    .
                  </li>
                )}
                {noCounterparties && (
                  <li>
                    {t('contracts.agreementForm.noCounterparties')}{' '}
                    <Link to="/contracts/counterparties/new" className="underline">
                      {t('contracts.agreementForm.addCounterparty')}
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
              <CardTitle>{t('contracts.agreementForm.fundingSource')}</CardTitle>
              <CardDescription>
                {t('contracts.agreementForm.fundingHint')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="administrator">{t('contracts.budgetAdministrator')}</Label>
                  <Select
                    value={administratorId}
                    onValueChange={chooseAdministrator}
                    disabled={budgetsLoading || administrators.length === 0}
                  >
                    <SelectTrigger
                      id="administrator"
                      className={errors.administrator ? 'border-destructive' : undefined}
                    >
                      <SelectValue placeholder={t('contracts.pick')} />
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
                  <Label htmlFor="program">{t('contracts.columns.programme')}</Label>
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
                          administratorId ? t('contracts.pick') : t('contracts.agreementForm.administratorFirst')
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

              {/* Год спрашивается, только если строк за разные годы больше одной. */}
              {yearOptions.length > 1 && (
                <div className="sm:w-48">
                  <Label htmlFor="budget-year">{t('contracts.budgetYear')}</Label>
                  <Select value={lineId} onValueChange={setLineId}>
                    <SelectTrigger
                      id="budget-year"
                      className={errors.budget ? 'border-destructive' : undefined}
                    >
                      <SelectValue placeholder={t('contracts.pick')} />
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
                    <span className="text-muted-foreground">{t('contracts.columns.allocated')}</span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.amount)} {selectedLine.currency}
                    </span>
                  </div>
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="text-muted-foreground">{t('contracts.columns.contracted')}</span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.committed)}
                    </span>
                  </div>
                  <div className="flex flex-wrap justify-between gap-2 font-medium mt-1 pt-1 border-t">
                    <span>{t('contracts.columns.remaining')}</span>
                    <span className="tabular-nums">
                      {formatAmount(selectedLine.remaining)}
                    </span>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ─── Договор ───────────────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.agreement.title')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="number">{t('contracts.agreementForm.numberLabel')}</Label>
                  <Input
                    id="number"
                    value={number}
                    onChange={(event) => setNumber(event.target.value)}
                    placeholder={t('contracts.agreementForm.numberPlaceholder')}
                    className={errors.number ? 'border-destructive' : undefined}
                  />
                  {fieldError('number')}
                </div>
                <div>
                  <Label htmlFor="counterparty">{t('contracts.columns.counterparty')}</Label>
                  <Select
                    value={counterpartyId}
                    onValueChange={setCounterpartyId}
                    disabled={counterpartiesLoading || counterparties.length === 0}
                  >
                    <SelectTrigger
                      id="counterparty"
                      className={errors.counterparty ? 'border-destructive' : undefined}
                    >
                      <SelectValue placeholder={t('contracts.agreementForm.pickFromRegistry')} />
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
                <Label htmlFor="name">{t('contracts.agreementForm.nameLabel')}</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t('contracts.agreementForm.namePlaceholder')}
                  className={errors.name ? 'border-destructive' : undefined}
                />
                {fieldError('name')}
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <Label htmlFor="amount">{t('contracts.agreementForm.amountLabel')}</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="400000.00"
                      className={
                        errors.amount || overBudget ? 'border-destructive' : undefined
                      }
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
                  <Label htmlFor="payment-type">{t('contracts.columns.paymentType')}</Label>
                  <Select
                    value={paymentType}
                    onValueChange={(value) => setPaymentType(value as PaymentType)}
                  >
                    <SelectTrigger id="payment-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(enums?.payment_type ?? []).map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="signed-date">{t('contracts.columns.signedAt')}</Label>
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
                    {t('contracts.agreementForm.overBudget', { amount: formatAmount(selectedLine.remaining), currency: selectedLine.currency })}
                  </div>
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="status">{t('contracts.columns.status')}</Label>
                  <Select
                    value={status}
                    onValueChange={(value) => setStatus(value as AgreementStatus)}
                  >
                    <SelectTrigger id="status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {/* «Исполнен»/«Расторгнут» при создании не предлагаем —
                          это состояния уже прожитого договора. */}
                      {(enums?.agreement_status ?? [])
                        .filter(
                          (option) =>
                            !['executed', 'terminated'].includes(option.value),
                        )
                        .map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    {willCommit
                      ? t('contracts.agreementForm.statusConsumes')
                      : t('contracts.agreementForm.draftDoesNot')}
                  </p>
                </div>

                <div>
                  <Label htmlFor="file">{t('contracts.agreementForm.fileLabel')}</Label>
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
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-3">
            <Button type="submit" disabled={mutation.isPending || noBudgets || noCounterparties}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('contracts.agreementForm.submit')}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate('/contracts/agreements')}
              disabled={mutation.isPending}
            >
              {t('common.cancel')}
            </Button>
          </div>
        </form>
      </div>
    </ContractsShell>
  );
};

export default AgreementCreate;
