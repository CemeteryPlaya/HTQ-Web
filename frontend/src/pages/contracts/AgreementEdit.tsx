import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, FileText, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { DateInput } from '@/components/ui/date-input';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
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
import { fetchEmployees } from '@/api/hr';
import { reportApiError } from '@/lib/apiError';
import { isPlatformAdmin } from '@/lib/auth/roles';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import type {
  Agreement,
  AgreementDirection,
  AgreementKind,
  AgreementType,
  BudgetLineFlat,
  ContractsEnums,
  Counterparty,
  PaymentType,
} from '@/types/contracts';

/**
 * Правка договора со всеми реквизитами корпоративной СЭД.
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
  const { activeProfile } = useActiveProfile();
  const canEdit = isPlatformAdmin(activeProfile);
  const loading =
    isLoading || !agreement || linesLoading || counterpartiesLoading || !enums;

  return (
    <ContractsShell>
      <div className="max-w-4xl">
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
        ) : !canEdit ? (
          <PrerequisiteNotice
            title="Править эту карточку нельзя:"
            items={[{
              when: true,
              text: 'Правка, удаление и смена статуса — за администратором,',
              to: backTo,
              linkText: 'вернуться к карточке',
            }]}
          />
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

/** Тело формы редактирования */
const AgreementEditForm = ({ agreement, lines, counterparties, enums }: FormProps) => {
  const agreementId = agreement.id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: employees = [] } = useQuery({
    queryKey: ['hr', 'employees', 'all'],
    queryFn: () => fetchEmployees(),
  });

  // Финансирование
  const [administratorId, setAdministratorId] = useState(String(agreement.administrator_id));
  const [programId, setProgramId] = useState(String(agreement.program_id));
  const [lineId, setLineId] = useState(String(agreement.budget_line_id));
  const [counterpartyId, setCounterpartyId] = useState(String(agreement.counterparty_id));

  // Общие реквизиты СЭД
  const [direction, setDirection] = useState<AgreementDirection>(agreement.direction ?? 'expense');
  const [kind, setKind] = useState<AgreementKind>(agreement.kind ?? 'works_services');
  const [contractType, setContractType] = useState<AgreementType>(agreement.contract_type ?? 'standard');
  const [number, setNumber] = useState(agreement.number);
  const [sedNumber, setSedNumber] = useState(agreement.sed_number ?? '');
  const [name, setName] = useState(agreement.name);
  const [subject, setSubject] = useState(agreement.subject ?? '');
  const [managerName, setManagerName] = useState(agreement.manager_name ?? '');
  const [managerUserId, setManagerUserId] = useState<number | null>(agreement.manager_user_id ?? null);

  // Финансы и НДС
  const [hasVat, setHasVat] = useState<boolean>(agreement.has_vat ?? true);
  const [vatRate, setVatRate] = useState<string>(agreement.vat_rate ?? '12');
  const [amountWithoutVat, setAmountWithoutVat] = useState(agreement.amount_without_vat ?? '');
  const [vatAmount, setVatAmount] = useState(agreement.vat_amount ?? '');
  const [amount, setAmount] = useState(agreement.amount);

  // Аванс и удержание
  const [hasAdvance, setHasAdvance] = useState<boolean>(agreement.has_advance ?? false);
  const [advancePercentage, setAdvancePercentage] = useState(agreement.advance_percentage ?? '');
  const [advanceAmountPlanned, setAdvanceAmountPlanned] = useState(agreement.advance_amount_planned ?? '');
  const [retentionRate, setRetentionRate] = useState(agreement.retention_rate ?? '0');
  const [retentionAmount, setRetentionAmount] = useState(agreement.retention_amount ?? '');

  // Сроки и тип оплаты
  const [paymentType, setPaymentType] = useState<PaymentType>(agreement.payment_type);
  const [signedDate, setSignedDate] = useState(agreement.signed_date ?? '');
  const [startDate, setStartDate] = useState(agreement.start_date ?? '');
  const [endDate, setEndDate] = useState(agreement.end_date ?? '');
  const [termComment, setTermComment] = useState(agreement.term_comment ?? '');

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

  // Занимает ли договор бюджет СВОЕЙ СУММОЙ в текущем статусе. Статус на этой
  // форме не меняется, поэтому берётся как есть. Открытый договор суммой
  // бюджет не занимает никогда — его расход считается оплатами (как и в
  // `budget_calc` на бэкенде), — поэтому ни «своей суммы в законтрактованном»,
  // ни проверки суммы против остатка у него нет.
  const committingStatuses = enums.committing_statuses;
  const willCommit =
    committingStatuses.includes(agreement.status) && agreement.contract_type !== 'framework';

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
    direction === 'expense' &&
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
          start_date: startDate || null,
          end_date: endDate || null,
          term_comment: termComment.trim(),
          currency: selectedLine!.currency,
          signed_date: signedDate || null,
        })
        .then((r) => r.data),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(`Договор ${row.number} сохранён`);
      navigate(`/contracts/agreements/${agreementId}`);
    },
    onError: (err) => reportApiError(err, 'Не удалось сохранить договор'),
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
      {/* ─── 1. Источник финансирования ─────────────────────────────── */}
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
            <div className="rounded-md border bg-muted/40 p-4 text-sm space-y-2">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pb-2 border-b text-xs">
                <div>
                  <span className="text-muted-foreground">Код статьи: </span>
                  <span className="font-medium">{selectedLine.program_name}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Статья бюджета: </span>
                  <span className="font-medium">{selectedLine.expense_item}</span>
                </div>
              </div>
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

      {/* ─── 2. Договор и реквизиты СЭД ───────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Договор</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <Label htmlFor="direction">Направление</Label>
              <Select
                value={direction}
                onValueChange={(val) => setDirection(val as AgreementDirection)}
              >
                <SelectTrigger id="direction">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="expense">Расход (списание с бюджета)</SelectItem>
                  <SelectItem value="income">Поступление</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="kind">Вид договора</Label>
              <Select
                value={kind}
                onValueChange={(val) => setKind(val as AgreementKind)}
              >
                <SelectTrigger id="kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="works_services">РиУ (Работы и услуги)</SelectItem>
                  <SelectItem value="goods">Товары</SelectItem>
                  <SelectItem value="services">Услуги</SelectItem>
                  <SelectItem value="lease">Аренда</SelectItem>
                  <SelectItem value="other">Прочее</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="contract-type">Тип договора</Label>
              <Select
                value={contractType}
                onValueChange={(val) => setContractType(val as AgreementType)}
              >
                <SelectTrigger id="contract-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="standard">Стандартный</SelectItem>
                  <SelectItem value="non_standard">Нетиповой</SelectItem>
                  <SelectItem value="framework">Рамочный</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
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
              <Label htmlFor="sed-number">№ СЭД</Label>
              <Input
                id="sed-number"
                value={sedNumber}
                onChange={(event) => setSedNumber(event.target.value)}
                placeholder="DOC-00026-20260623"
              />
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

          <div className="grid gap-4 sm:grid-cols-2">
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

            <div>
              <Label htmlFor="manager">Менеджер / Куратор договора</Label>
              <Input
                id="manager"
                list="manager-options-edit"
                value={managerName}
                onChange={(e) => {
                  const val = e.target.value;
                  setManagerName(val);
                  const match = employees.find(
                    (emp) => emp.full_name.toLowerCase() === val.trim().toLowerCase(),
                  );
                  setManagerUserId(match ? match.user_id ?? match.user ?? null : null);
                }}
                placeholder="Куаныш Садиев"
              />
              <datalist id="manager-options-edit">
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.full_name}>
                    {emp.position_title ? `${emp.position_title} (${emp.department_name || ''})` : ''}
                  </option>
                ))}
              </datalist>
            </div>
          </div>

          <div>
            <Label htmlFor="subject">Предмет договора</Label>
            <Textarea
              id="subject"
              rows={3}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Монтаж ограждения, дороги, выравнивание, земляные работы..."
            />
          </div>
        </CardContent>
      </Card>

      {/* ─── 3. Финансовые условия и НДС ────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Финансовые условия и расчёты</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4 p-3 rounded-lg border bg-muted/20">
            <div className="flex items-center space-x-3">
              <Switch
                id="has-vat-edit"
                checked={hasVat}
                onCheckedChange={handleVatToggle}
              />
              <Label htmlFor="has-vat-edit" className="cursor-pointer font-medium">
                {hasVat ? 'С НДС' : 'Без НДС'}
              </Label>
            </div>
            {hasVat && (
              <div className="flex items-center gap-2">
                <Label htmlFor="vat-rate-edit" className="text-sm">
                  Ставка НДС, %
                </Label>
                <Input
                  id="vat-rate-edit"
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
              <Label htmlFor="amount-without-vat">Договор без НДС</Label>
              <Input
                id="amount-without-vat"
                inputMode="decimal"
                value={amountWithoutVat}
                onChange={(e) => handleWithoutVatChange(e.target.value)}
                placeholder="0.00"
              />
            </div>

            <div>
              <Label htmlFor="vat-amount">Договор НДС</Label>
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
              <Label htmlFor="amount" className="font-semibold">Договор всего *</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="amount"
                  inputMode="decimal"
                  value={amount}
                  onChange={(event) => handleTotalAmountChange(event.target.value)}
                  className={errors.amount || overBudget ? 'border-destructive font-semibold' : 'font-semibold'}
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
                Сумма превышает остаток бюджета этой строки. Договор в текущем
                статусе занимает бюджет — сохранение упрётся в лимит на бэкенде.
              </div>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 pt-2 border-t">
            {/* Аванс */}
            <div className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <Label htmlFor="has-advance-edit" className="font-medium cursor-pointer">
                  Предусмотрен аванс
                </Label>
                <Switch
                  id="has-advance-edit"
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
                    <Label htmlFor="advance-pct-edit" className="text-xs">
                      Аванс, %
                    </Label>
                    <Input
                      id="advance-pct-edit"
                      value={advancePercentage}
                      onChange={(e) => {
                        setAdvancePercentage(e.target.value);
                        recalculateAdvance(amount, e.target.value);
                      }}
                      placeholder="30"
                    />
                  </div>
                  <div>
                    <Label htmlFor="advance-amount-edit" className="text-xs">
                      Плановая сумма аванса
                    </Label>
                    <Input
                      id="advance-amount-edit"
                      value={advanceAmountPlanned}
                      onChange={(e) => setAdvanceAmountPlanned(e.target.value)}
                      placeholder="0.00"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Гар. удержание */}
            <div className="space-y-3 rounded-lg border p-3">
              <div className="font-medium text-sm">Гарантийное удержание</div>
              <div className="grid grid-cols-2 gap-3 pt-1">
                <div>
                  <Label htmlFor="retention-rate-edit" className="text-xs">
                    Гар. удержание, %
                  </Label>
                  <Input
                    id="retention-rate-edit"
                    value={retentionRate}
                    onChange={(e) => {
                      setRetentionRate(e.target.value);
                      recalculateRetention(amount, e.target.value);
                    }}
                    placeholder="5"
                  />
                </div>
                <div>
                  <Label htmlFor="retention-amount-edit" className="text-xs">
                    Сумма гар. удержания
                  </Label>
                  <Input
                    id="retention-amount-edit"
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

      {/* ─── 4. Сроки и условия исполнения ─────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Сроки и условия исполнения</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-4">
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
              <DateInput
                id="signed-date"
                value={signedDate}
                onChange={setSignedDate}
              />
            </div>

            <div>
              <Label htmlFor="start-date-edit">Дата начала</Label>
              <DateInput
                id="start-date-edit"
                value={startDate}
                onChange={setStartDate}
              />
            </div>

            <div>
              <Label htmlFor="end-date-edit">Срок исполнения</Label>
              <DateInput
                id="end-date-edit"
                value={endDate}
                onChange={setEndDate}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="term-comment-edit">Срок исполнения (комментарий)</Label>
            <Input
              id="term-comment-edit"
              value={termComment}
              onChange={(e) => setTermComment(e.target.value)}
              placeholder="например, уточнить"
            />
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
  );
};

export default AgreementEdit;
