import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, FileText, Loader2, Paperclip } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { LinkedRequestPicker } from '@/components/contracts/LinkedRequestPicker';
import { useLinkedRequest } from '@/components/contracts/useLinkedRequest';
import { DateInput } from '@/components/ui/date-input';
import { contractsApi } from '@/api/contracts';
import { fetchEmployees } from '@/api/hr';
import { reportApiError } from '@/lib/apiError';
import {
  CONTRACT_DATE_AHEAD_DAYS,
  CONTRACT_DATE_MIN,
  INVALID_DATE,
  VALID_UNTIL_BEFORE_DATE,
  contractDateProblem,
  datesOutOfOrder,
  todayIso,
} from '@/lib/validation';
import type {
  AgreementDirection,
  AgreementKind,
  AgreementType,
  BudgetLineFlat,
} from '@/types/contracts';
import { useTranslation } from 'react-i18next';

/**
 * Оформление договора со всеми реквизитами корпоративной СЭД.
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

  const { data: lines = [], isLoading: budgetsLoading } = useQuery({
    queryKey: ['contracts', 'budget-lines', 'approved'],
    queryFn: () =>
      contractsApi.listBudgetLines({ approval_state: 'approved' }).then((r) => r.data),
  });
  const { data: counterparties = [], isLoading: counterpartiesLoading } = useQuery({
    queryKey: ['contracts', 'counterparties', ''],
    queryFn: () => contractsApi.listCounterparties().then((r) => r.data),
  });
  const { data: employees = [] } = useQuery({
    queryKey: ['hr', 'employees', 'all'],
    queryFn: () => fetchEmployees(),
  });

  // Финансирование
  const [administratorId, setAdministratorId] = useState<string>('');
  const [programId, setProgramId] = useState<string>('');
  const [lineId, setLineId] = useState<string>('');
  const [counterpartyId, setCounterpartyId] = useState<string>('');

  // Заявка на закуп: из адреса (?request_id=) или выбранная в форме. Её
  // строка бюджета подставляется в каскад и запирает его — договор по
  // заявке заключается только на неё (бэкенд проверит то же).
  const linkedRequest = useLinkedRequest(lines);
  useEffect(() => {
    const row = linkedRequest.line;
    if (!row) return;
    setAdministratorId(String(row.administrator_id));
    setProgramId(String(row.program_id));
    setLineId(String(row.id));
  }, [linkedRequest.line]);
  const fundingLocked = linkedRequest.linked != null;

  // Общие реквизиты СЭД
  const [direction, setDirection] = useState<AgreementDirection>('expense');
  const [kind, setKind] = useState<AgreementKind>('works_services');
  const [contractType, setContractType] = useState<AgreementType>('standard');
  const [number, setNumber] = useState('');
  const [sedNumber, setSedNumber] = useState('');
  const [name, setName] = useState('');
  const [subject, setSubject] = useState('');
  const [managerName, setManagerName] = useState('');
  const [managerUserId, setManagerUserId] = useState<number | null>(null);

  // «Дата договора» (по документу, обязательна, по умолчанию сегодня) и
  // «Срок действия по» (необязателен, не раньше даты договора; после него
  // новые оплаты по договору не заводятся — BR-036).
  const [contractDate, setContractDate] = useState(() => todayIso());
  const [validUntil, setValidUntil] = useState('');
  const [brokenDates, setBrokenDates] = useState({ contract: false, until: false });
  const validUntilBeforeDate = datesOutOfOrder(contractDate, validUntil);

  // Финансы и НДС
  const [hasVat, setHasVat] = useState<boolean>(true);
  const [vatRate, setVatRate] = useState<string>('12');
  const [amountWithoutVat, setAmountWithoutVat] = useState('');
  const [vatAmount, setVatAmount] = useState('');
  const [amount, setAmount] = useState('');

  // Аванс и удержание
  const [hasAdvance, setHasAdvance] = useState<boolean>(false);
  const [advancePercentage, setAdvancePercentage] = useState('');
  const [advanceAmountPlanned, setAdvanceAmountPlanned] = useState('');
  const [retentionRate, setRetentionRate] = useState('0');
  const [retentionAmount, setRetentionAmount] = useState('');

  // Файл. Статуса, дат и комментария к сроку в форме нет: договор всегда
  // заводится черновиком (дальше его ведёт согласование), а предоплату /
  // постоплату / поэтапно бэкенд выводит из аванса (`payment_type_from_advance`).
  const [file, setFile] = useState<File | null>(null);

  const [errors, setErrors] = useState<Errors>({});

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

  const remainingKopecks = selectedLine ? toKopecks(selectedLine.remaining) : null;
  const amountKopecks =
    amount.trim() && AMOUNT_RE.test(amount.trim()) ? toKopecks(amount.trim()) : null;

  // Черновик бюджет не занимает, но на согласование договор уйдёт только в
  // пределах остатка (переход в `on_review` проверяет лимит) — предупреждаем
  // сразу. Открытый договор суммой бюджет не занимает никогда.
  const overBudget =
    direction === 'expense' &&
    contractType !== 'framework' &&
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
    setLineId(matching.length === 1 ? String(matching[0].id) : '');
  };

  // Пересчет НДС
  const handleWithoutVatChange = (val: string) => {
    setAmountWithoutVat(val);
    const num = parseFloat(val.replace(',', '.')) || 0;
    if (!hasVat) {
      setVatAmount('0.00');
      const totalStr = num ? num.toFixed(2) : '';
      setAmount(totalStr);
      recalculateAdvance(totalStr, advancePercentage);
      recalculateRetention(totalStr, retentionRate);
      return;
    }
    const rate = parseFloat(vatRate.replace(',', '.')) || 0;
    const vat = num * (rate / 100);
    const total = num + vat;
    setVatAmount(vat ? vat.toFixed(2) : '');
    const totalStr = total ? total.toFixed(2) : '';
    setAmount(totalStr);
    recalculateAdvance(totalStr, advancePercentage);
    recalculateRetention(totalStr, retentionRate);
  };

  const handleTotalAmountChange = (val: string) => {
    setAmount(val);
    const num = parseFloat(val.replace(',', '.')) || 0;
    if (!hasVat) {
      setAmountWithoutVat(num ? num.toFixed(2) : '');
      setVatAmount('0.00');
    } else {
      const rate = parseFloat(vatRate.replace(',', '.')) || 0;
      const withoutVat = num / (1 + rate / 100);
      const vat = num - withoutVat;
      setAmountWithoutVat(withoutVat ? withoutVat.toFixed(2) : '');
      setVatAmount(vat ? vat.toFixed(2) : '');
    }
    recalculateAdvance(val, advancePercentage);
    recalculateRetention(val, retentionRate);
  };

  const handleVatRateChange = (newRate: string) => {
    setVatRate(newRate);
    if (!hasVat) return;
    const rateNum = parseFloat(newRate.replace(',', '.')) || 0;
    const withoutVatNum = parseFloat(amountWithoutVat.replace(',', '.')) || 0;
    if (withoutVatNum) {
      const vat = withoutVatNum * (rateNum / 100);
      const total = withoutVatNum + vat;
      setVatAmount(vat.toFixed(2));
      setAmount(total.toFixed(2));
      recalculateAdvance(total.toFixed(2), advancePercentage);
      recalculateRetention(total.toFixed(2), retentionRate);
    }
  };

  const handleVatToggle = (enabled: boolean) => {
    setHasVat(enabled);
    if (!enabled) {
      setVatAmount('0.00');
      if (amount) {
        setAmountWithoutVat(amount);
      }
    } else {
      const rate = parseFloat(vatRate.replace(',', '.')) || 12;
      if (!vatRate || vatRate === '0') setVatRate('12');
      const withoutVatNum = parseFloat(amountWithoutVat.replace(',', '.')) || 0;
      if (withoutVatNum) {
        const vat = withoutVatNum * (rate / 100);
        const total = withoutVatNum + vat;
        setVatAmount(vat.toFixed(2));
        setAmount(total.toFixed(2));
        recalculateAdvance(total.toFixed(2), advancePercentage);
        recalculateRetention(total.toFixed(2), retentionRate);
      }
    }
  };

  const recalculateAdvance = (totalStr: string, pctStr: string) => {
    const totalNum = parseFloat(totalStr.replace(',', '.')) || 0;
    const pctNum = parseFloat(pctStr.replace(',', '.')) || 0;
    if (pctNum > 0 && totalNum > 0) {
      setAdvanceAmountPlanned(((totalNum * pctNum) / 100).toFixed(2));
    }
  };

  const recalculateRetention = (totalStr: string, rateStr: string) => {
    const totalNum = parseFloat(totalStr.replace(',', '.')) || 0;
    const rateNum = parseFloat(rateStr.replace(',', '.')) || 0;
    if (rateNum > 0 && totalNum > 0) {
      setRetentionAmount(((totalNum * rateNum) / 100).toFixed(2));
    }
  };

  const validate = (): Errors => {
    const next: Errors = {};
    if (!administratorId) next.administrator = t('contracts.agreementForm.errors.administrator');
    else if (!programId) next.program = t('contracts.agreementForm.errors.program');
    else if (!lineId) next.budget = t('contracts.agreementForm.errors.budget');
    if (!counterpartyId) next.counterparty = t('contracts.agreementForm.errors.counterparty');
    if (!number.trim()) next.number = t('contracts.agreementForm.errors.number');
    if (brokenDates.contract) next.contractDate = INVALID_DATE;
    else {
      const problem = contractDateProblem(contractDate);
      if (problem) next.contractDate = problem;
    }
    if (brokenDates.until) next.validUntil = INVALID_DATE;
    else if (validUntilBeforeDate) next.validUntil = VALID_UNTIL_BEFORE_DATE;
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
          direction,
          kind,
          contract_type: contractType,
          sed_number: sedNumber.trim(),
          subject: subject.trim(),
          manager_user_id: managerUserId,
          manager_name: managerName.trim(),
          has_vat: hasVat,
          vat_rate: hasVat ? vatRate.trim() || '0' : '0',
          amount_without_vat: amountWithoutVat.trim() ? amountWithoutVat.trim().replace(',', '.') : null,
          vat_amount: vatAmount.trim() ? vatAmount.trim().replace(',', '.') : null,
          has_advance: hasAdvance,
          advance_percentage: hasAdvance && advancePercentage.trim() ? advancePercentage.trim().replace(',', '.') : null,
          advance_amount_planned: hasAdvance && advanceAmountPlanned.trim() ? advanceAmountPlanned.trim().replace(',', '.') : null,
          retention_rate: retentionRate.trim() || '0',
          retention_amount: retentionAmount.trim() ? retentionAmount.trim().replace(',', '.') : null,
          signed_date: contractDate,
          end_date: validUntil || null,
          currency: selectedLine!.currency,
          request_id: linkedRequest.linked?.id ?? null,
        })
        .then((r) => r.data);

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
    onError: (err) => reportApiError(err, t('contracts.agreementForm.createError')),
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
      <div className="max-w-4xl">
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

        <PrerequisiteNotice
          title={t('contracts.agreementForm.needReferences')}
          items={[
            {
              when: noBudgets,
              text: t('contracts.agreementForm.noBudgets'),
              to: '/contracts/budgets/new',
              linkText: t('contracts.agreementForm.createBudgetLine'),
            },
            {
              when: noCounterparties,
              text: t('contracts.agreementForm.noCounterparties'),
              to: '/contracts/counterparties/new',
              linkText: t('contracts.agreementForm.addCounterparty'),
            },
          ]}
        />

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* ─── 1. Источник финансирования и бюджет ──────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.agreementForm.fundingSource')}</CardTitle>
              <CardDescription>
                {t('contracts.agreementForm.fundingHint')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <LinkedRequestPicker
                value={linkedRequest.linked}
                onChange={linkedRequest.setLinked}
                missing={linkedRequest.missing}
                presetFailed={linkedRequest.presetFailed}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="administrator">{t('contracts.budgetAdministrator')}</Label>
                  <Select
                    value={administratorId}
                    onValueChange={chooseAdministrator}
                    disabled={budgetsLoading || administrators.length === 0 || fundingLocked}
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
                    disabled={!administratorId || fundingLocked}
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

              {yearOptions.length > 1 && (
                <div className="sm:w-48">
                  <Label htmlFor="budget-year">{t('contracts.budgetYear')}</Label>
                  <Select value={lineId} onValueChange={setLineId} disabled={fundingLocked}>
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
                <div className="rounded-md border bg-muted/40 p-4 text-sm space-y-2">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pb-2 border-b text-xs">
                    <div>
                      <span className="text-muted-foreground">{t('contracts.agreementForm.codeLabel') || 'Код статьи'}: </span>
                      <span className="font-medium">{selectedLine.program_name}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">{t('contracts.agreementForm.expenseItemLabel') || 'Статья бюджета'}: </span>
                      <span className="font-medium">{selectedLine.expense_item}</span>
                    </div>
                  </div>
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

          {/* ─── 2. Реквизиты договора и СЭД ───────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.agreement.title')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Направление и Вид. Тип («стандартный / открытый») — в блоке
                  «Оплата и файл», под подписью «Тип оплаты»: так его зовёт
                  заказчик. */}
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="direction">{t('contracts.agreementForm.directionLabel')}</Label>
                  <Select
                    value={direction}
                    onValueChange={(val) => setDirection(val as AgreementDirection)}
                  >
                    <SelectTrigger id="direction">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="expense">{t('contracts.agreementForm.directionExpense')}</SelectItem>
                      <SelectItem value="income">{t('contracts.agreementForm.directionIncome')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="kind">{t('contracts.agreementForm.kindLabel')}</Label>
                  <Select
                    value={kind}
                    onValueChange={(val) => setKind(val as AgreementKind)}
                  >
                    <SelectTrigger id="kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="works_services">{t('contracts.agreementForm.kindWorksServices')}</SelectItem>
                      <SelectItem value="goods">{t('contracts.agreementForm.kindGoods')}</SelectItem>
                      <SelectItem value="services">{t('contracts.agreementForm.kindServices')}</SelectItem>
                      <SelectItem value="lease">{t('contracts.agreementForm.kindLease')}</SelectItem>
                      <SelectItem value="other">{t('contracts.agreementForm.kindOther')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Номера и Контрагент */}
              <div className="grid gap-4 sm:grid-cols-3">
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
                  <Label htmlFor="sed-number">{t('contracts.agreementForm.sedNumberLabel')}</Label>
                  <Input
                    id="sed-number"
                    value={sedNumber}
                    onChange={(event) => setSedNumber(event.target.value)}
                    placeholder={t('contracts.agreementForm.sedNumberPlaceholder')}
                  />
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

              {/* Дата договора и срок действия. Дата входит в уникальность
                  договора (контрагент + номер + дата) — бэкенд не даст завести
                  тот же договор второй раз. */}
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="contract-date">{t('contracts.agreementForm.contractDateLabel')}</Label>
                  <DateInput
                    id="contract-date"
                    value={contractDate}
                    onChange={setContractDate}
                    min={CONTRACT_DATE_MIN}
                    max={todayIso(CONTRACT_DATE_AHEAD_DAYS)}
                    invalid={Boolean(errors.contractDate) || brokenDates.contract}
                    onValidityChange={(bad) => setBrokenDates((prev) => ({ ...prev, contract: bad }))}
                  />
                  {fieldError('contractDate') ?? (
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('contracts.agreementForm.contractDateHint')}
                    </p>
                  )}
                </div>

                <div>
                  <Label htmlFor="valid-until">
                    {t('contracts.agreementForm.validUntilLabel')}{' '}
                    <span className="text-muted-foreground">{t('common.optionalParen')}</span>
                  </Label>
                  <DateInput
                    id="valid-until"
                    value={validUntil}
                    onChange={setValidUntil}
                    min={contractDate || undefined}
                    invalid={Boolean(errors.validUntil) || brokenDates.until || validUntilBeforeDate}
                    onValidityChange={(bad) => setBrokenDates((prev) => ({ ...prev, until: bad }))}
                  />
                  {fieldError('validUntil') ?? (
                    validUntilBeforeDate ? (
                      <p className="text-sm text-destructive mt-1">{VALID_UNTIL_BEFORE_DATE}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground mt-1">
                        {t('contracts.agreementForm.validUntilHint')}
                      </p>
                    )
                  )}
                </div>
              </div>

              {/* Наименование и Куратор */}
              <div className="grid gap-4 sm:grid-cols-2">
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

                <div>
                  <Label htmlFor="manager">{t('contracts.agreementForm.managerLabel')}</Label>
                  <Input
                    id="manager"
                    list="manager-options"
                    value={managerName}
                    onChange={(e) => {
                      const val = e.target.value;
                      setManagerName(val);
                      const match = employees.find(
                        (emp) => emp.full_name.toLowerCase() === val.trim().toLowerCase(),
                      );
                      setManagerUserId(match ? match.user_id ?? match.user ?? null : null);
                    }}
                    placeholder={t('contracts.agreementForm.managerPlaceholder')}
                  />
                  <datalist id="manager-options">
                    {employees.map((emp) => (
                      <option key={emp.id} value={emp.full_name}>
                        {emp.position_title ? `${emp.position_title} (${emp.department_name || ''})` : ''}
                      </option>
                    ))}
                  </datalist>
                </div>
              </div>

              {/* Предмет договора */}
              <div>
                <Label htmlFor="subject">{t('contracts.agreementForm.subjectLabel')}</Label>
                <Textarea
                  id="subject"
                  rows={3}
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder={t('contracts.agreementForm.subjectPlaceholder')}
                />
              </div>
            </CardContent>
          </Card>

          {/* ─── 3. Финансовые условия и НДС ────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.agreementForm.financeSectionTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4 p-3 rounded-lg border bg-muted/20">
                <div className="flex items-center space-x-3">
                  <Switch
                    id="has-vat"
                    checked={hasVat}
                    onCheckedChange={handleVatToggle}
                  />
                  <Label htmlFor="has-vat" className="cursor-pointer font-medium">
                    {hasVat ? 'С НДС' : 'Без НДС'}
                  </Label>
                </div>
                {hasVat && (
                  <div className="flex items-center gap-2">
                    <Label htmlFor="vat-rate" className="text-sm">
                      {t('contracts.agreementForm.vatRateLabel')}
                    </Label>
                    <Input
                      id="vat-rate"
                      className="w-24 text-right"
                      value={vatRate}
                      onChange={(e) => handleVatRateChange(e.target.value)}
                      placeholder="12"
                    />
                  </div>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <Label htmlFor="amount-without-vat">
                    {t('contracts.agreementForm.amountWithoutVatLabel')}
                  </Label>
                  <Input
                    id="amount-without-vat"
                    inputMode="decimal"
                    value={amountWithoutVat}
                    onChange={(e) => handleWithoutVatChange(e.target.value)}
                    placeholder="0.00"
                  />
                </div>

                <div>
                  <Label htmlFor="vat-amount">
                    {t('contracts.agreementForm.vatAmountLabel')}
                  </Label>
                  <Input
                    id="vat-amount"
                    readOnly
                    tabIndex={-1}
                    className="bg-muted/50 cursor-not-allowed"
                    value={vatAmount}
                    placeholder="0.00"
                  />
                </div>

                <div>
                  <Label htmlFor="amount" className="font-semibold">
                    {t('contracts.agreementForm.totalAmountLabel')} *
                  </Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => handleTotalAmountChange(event.target.value)}
                      placeholder="0.00"
                      className={
                        errors.amount || overBudget ? 'border-destructive font-semibold' : 'font-semibold'
                      }
                    />
                    {selectedLine && (
                      <span className="text-sm text-muted-foreground font-medium">
                        {selectedLine.currency}
                      </span>
                    )}
                  </div>
                  {fieldError('amount')}
                </div>
              </div>

              {overBudget && selectedLine && (
                <div className="flex gap-2 rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-destructive mt-0.5" />
                  <div>
                    {t('contracts.agreementForm.overBudget', {
                      amount: formatAmount(selectedLine.remaining),
                      currency: selectedLine.currency,
                    })}
                  </div>
                </div>
              )}

              {/* Аванс и гарантийное удержание */}
              <div className="grid gap-4 sm:grid-cols-2 pt-2 border-t">
                {/* Блок аванса */}
                <div className="space-y-3 rounded-lg border p-3">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="has-advance" className="font-medium cursor-pointer">
                      {t('contracts.agreementForm.hasAdvanceLabel')}
                    </Label>
                    <Switch
                      id="has-advance"
                      checked={hasAdvance}
                      onCheckedChange={(checked) => {
                        setHasAdvance(checked);
                        if (!checked) {
                          setAdvancePercentage('');
                          setAdvanceAmountPlanned('');
                        }
                      }}
                    />
                  </div>
                  {hasAdvance && (
                    <div className="grid grid-cols-2 gap-3 pt-1">
                      <div>
                        <Label htmlFor="advance-pct" className="text-xs">
                          {t('contracts.agreementForm.advancePercentageLabel')}
                        </Label>
                        <Input
                          id="advance-pct"
                          value={advancePercentage}
                          onChange={(e) => {
                            setAdvancePercentage(e.target.value);
                            recalculateAdvance(amount, e.target.value);
                          }}
                          placeholder="30"
                        />
                      </div>
                      <div>
                        <Label htmlFor="advance-amount" className="text-xs">
                          {t('contracts.agreementForm.advanceAmountLabel')}
                        </Label>
                        <Input
                          id="advance-amount"
                          value={advanceAmountPlanned}
                          onChange={(e) => setAdvanceAmountPlanned(e.target.value)}
                          placeholder="0.00"
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Блок гарантийного удержания */}
                <div className="space-y-3 rounded-lg border p-3">
                  <div className="font-medium text-sm">{t('contracts.agreementForm.retentionSectionTitle')}</div>
                  <div className="grid grid-cols-2 gap-3 pt-1">
                    <div>
                      <Label htmlFor="retention-rate" className="text-xs">
                        {t('contracts.agreementForm.retentionRateLabel')}
                      </Label>
                      <Input
                        id="retention-rate"
                        value={retentionRate}
                        onChange={(e) => {
                          setRetentionRate(e.target.value);
                          recalculateRetention(amount, e.target.value);
                        }}
                        placeholder="5"
                      />
                    </div>
                    <div>
                      <Label htmlFor="retention-amount" className="text-xs">
                        {t('contracts.agreementForm.retentionAmountLabel')}
                      </Label>
                      <Input
                        id="retention-amount"
                        value={retentionAmount}
                        onChange={(e) => setRetentionAmount(e.target.value)}
                        placeholder="0.00"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ─── 4. Оплата и файл ──────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.agreementForm.termsSectionTitle')}</CardTitle>
              <CardDescription>{t('contracts.agreementForm.draftDoesNot')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {/* «Тип оплаты» — так заказчик зовёт `contract_type`. Только
                    два значения: «нетиповой» остаётся лишь у старых договоров. */}
                <div>
                  <Label htmlFor="contract-type">{t('contracts.columns.paymentType')}</Label>
                  <Select
                    value={contractType}
                    onValueChange={(val) => setContractType(val as AgreementType)}
                  >
                    <SelectTrigger id="contract-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="standard">{t('contracts.agreementForm.contractTypeStandard')}</SelectItem>
                      <SelectItem value="framework">{t('contracts.agreementForm.contractTypeFramework')}</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    {contractType === 'framework'
                      ? t('contracts.agreementForm.contractTypeOpenHint')
                      : t('contracts.agreementForm.contractTypeStandardHint')}
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
