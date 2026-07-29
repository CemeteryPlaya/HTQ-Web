import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Wallet } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  ReferenceCombobox,
  type ReferenceValue,
} from '@/components/contracts/ReferenceCombobox';
import { contractsApi } from '@/api/contracts';
import type { BudgetFullCreatePayload } from '@/types/contracts';

/**
 * Заявка на бюджет — одна форма на всё.
 *
 * Заполняющий вводит и сам бюджет, и справочники, от которых тот зависит:
 * администратора (проект + страна) и программу (название, статья
 * расходов). Уходить в три отдельных экрана справочников и возвращаться не
 * нужно — в этом весь смысл страницы.
 *
 * Ничего не создаётся, пока форму не отправили: комбобоксы держат выбор в
 * состоянии, а на submit уходит ОДИН запрос (POST /budgets/full), который
 * бэкенд разбирает в одной транзакции. Брошенная на полпути заявка не
 * оставляет за собой полупустых записей в справочниках, а упавшее
 * создание бюджета откатывает и заведённые по пути страну/программу.
 *
 * Согласование заявок — отдельная, более поздняя задача; сейчас
 * отправленная форма сразу создаёт бюджетную строку.
 */

const CURRENCIES = ['KZT', 'USD', 'EUR', 'RUB'];

/** Сумма: целое или с двумя знаками. Без разделителей разрядов. */
const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

type Errors = Record<string, string>;

const BudgetCreate = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ─── Справочники ───────────────────────────────────────────────────────
  const { data: countries = [], isLoading: countriesLoading } = useQuery({
    queryKey: ['contracts', 'countries'],
    queryFn: () => contractsApi.listCountries().then((r) => r.data),
  });
  const { data: programs = [], isLoading: programsLoading } = useQuery({
    queryKey: ['contracts', 'programs'],
    queryFn: () => contractsApi.listPrograms({ is_active: true }).then((r) => r.data),
  });
  const { data: administrators = [], isLoading: administratorsLoading } = useQuery({
    queryKey: ['contracts', 'administrators'],
    queryFn: () => contractsApi.listAdministrators({ is_active: true }).then((r) => r.data),
  });

  // ─── Состояние формы ───────────────────────────────────────────────────
  // Комбобокс администратора ДЕРЖИТ название проекта: после снятия ФИО
  // подпись записи — это «проект страна», и отдельное поле «название
  // проекта» рядом с ним было бы вторым вводом одного и того же значения.
  const [administrator, setAdministrator] = useState<ReferenceValue>(null);
  const [country, setCountry] = useState<ReferenceValue>(null);
  const [isoCode, setIsoCode] = useState('');

  const [program, setProgram] = useState<ReferenceValue>(null);
  const [expenseItem, setExpenseItem] = useState('');
  // Код программы — отдельное поле, а НЕ часть вводимого названия: подпись
  // существующих программ в списке — «код название», и без своего поля
  // заполняющий вписывал бы код в название, чтобы получить такую же строку.
  const [programCode, setProgramCode] = useState('');

  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('KZT');
  const [periodYear, setPeriodYear] = useState(String(new Date().getFullYear()));
  const [note, setNote] = useState('');

  const [errors, setErrors] = useState<Errors>({});

  // Выбран существующий администратор — проект и страна принадлежат ЕМУ,
  // и правка их здесь означала бы правку чужой записи справочника, а не
  // заполнение заявки. Поэтому поля показываются заполненными и закрытыми.
  const existingAdministrator =
    administrator?.kind === 'existing'
      ? administrators.find((row) => row.id === administrator.id)
      : undefined;
  const existingProgram =
    program?.kind === 'existing'
      ? programs.find((row) => row.id === program.id)
      : undefined;

  const administratorLocked = Boolean(existingAdministrator);
  const programLocked = Boolean(existingProgram);

  const effectiveExpenseItem = existingProgram?.expense_item ?? expenseItem;
  const effectiveProgramCode = existingProgram?.code ?? programCode;
  // У существующей записи страна приходит с ней самой (`country_name`) —
  // искать её в справочнике по id больше не нужно.
  const effectiveCountryName = existingAdministrator
    ? existingAdministrator.country_name
    : country?.label ?? '';

  const administratorOptions = useMemo(
    () =>
      administrators.map((row) => ({
        id: row.id,
        label: row.project_name,
        hint: row.country_name,
      })),
    [administrators],
  );
  const programOptions = useMemo(
    () =>
      programs.map((row) => ({
        id: row.id,
        label: row.display_name,
        hint: row.expense_item,
      })),
    [programs],
  );
  const countryOptions = useMemo(
    () => countries.map((row) => ({ id: row.id, label: row.name, hint: row.iso_code })),
    [countries],
  );

  // ─── Проверка ──────────────────────────────────────────────────────────
  const validate = (): Errors => {
    const next: Errors = {};

    if (!administrator) {
      next.administrator = 'Выберите проект или впишите новый';
    } else if (administrator.kind === 'new' && !country) {
      next.country = 'Выберите страну или впишите новую';
    }

    if (!program) {
      next.program = 'Выберите программу или впишите новую';
    } else if (program.kind === 'new' && !expenseItem.trim()) {
      next.expenseItem = 'Укажите статью расходов';
    }

    if (!amount.trim()) {
      next.amount = 'Укажите сумму бюджета';
    } else if (!AMOUNT_RE.test(amount.trim())) {
      next.amount = 'Сумма — число, максимум два знака после запятой';
    }

    const year = Number(periodYear);
    if (!Number.isInteger(year) || year < 2000 || year > 2100) {
      next.periodYear = 'Год в диапазоне 2000–2100';
    }

    return next;
  };

  const buildPayload = (): BudgetFullCreatePayload => ({
    administrator:
      administrator!.kind === 'existing'
        ? { id: administrator!.id }
        : {
            project_name: administrator!.label.trim(),
            country:
              country!.kind === 'existing'
                ? { id: country!.id }
                : { name: country!.label, iso_code: isoCode.trim().toUpperCase() },
          },
    program:
      program!.kind === 'existing'
        ? { id: program!.id }
        : {
            name: program!.label.trim(),
            expense_item: expenseItem.trim(),
            code: programCode.trim(),
          },
    // Запятую в сумме бэкенд не примет — Decimal ждёт точку.
    amount: amount.trim().replace(',', '.'),
    period_year: Number(periodYear),
    currency,
    note: note.trim(),
  });

  const mutation = useMutation({
    mutationFn: () => contractsApi.createBudgetFull(buildPayload()).then((r) => r.data),
    onSuccess: (budget) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(
        `Бюджет создан: ${budget.program_name} — ${budget.amount} ${budget.currency}`,
      );
      navigate('/contracts/budgets');
    },
    onError: (error: any) => {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;

      // 409 — заявка корректна по форме, но противоречит данным (такая
      // связка уже есть). Текст осмысленный, показываем как есть.
      if (status === 409 && typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      // 422 — нарушение схемы; бэкенд отдаёт список ошибок по полям.
      if (status === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item: any) => item.msg).join('; '));
        return;
      }
      toast.error('Не удалось создать бюджет');
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

  return (
    <ContractsShell>
    <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to="/contracts/budgets"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К списку бюджетов
          </Link>
          <div className="flex items-center gap-3">
            <Wallet className="h-7 w-7 text-muted-foreground" />
            <div>
              <h1 className="text-3xl font-bold">Заявка на бюджет</h1>
              <p className="text-muted-foreground text-sm mt-1">
                Заполните целиком — справочники можно завести прямо здесь,
                отдельно ходить никуда не нужно.
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* ─── Администратор бюджета ─────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Администратор бюджета</CardTitle>
              <CardDescription>
                Держатель бюджетной строки — проект в стране. Денег на самой
                записи нет: суммы живут на бюджетах, и у одного проекта их
                может быть несколько под разные программы.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="administrator">Название проекта</Label>
                  <ReferenceCombobox
                    id="administrator"
                    options={administratorOptions}
                    value={administrator}
                    onChange={(next) => {
                      setAdministrator(next);
                      // Сброс на смену: страна относится к прежнему выбору.
                      if (next?.kind !== 'new') {
                        setCountry(null);
                        setIsoCode('');
                      }
                    }}
                    placeholder="Выберите или впишите новый"
                    searchPlaceholder="Поиск по проекту или стране…"
                    createLabel={(input) => `Создать проект «${input}»`}
                    loading={administratorsLoading}
                    invalid={Boolean(errors.administrator)}
                  />
                  {fieldError('administrator')}
                </div>

                <div>
                  <Label htmlFor="country">Страна</Label>
                  {administratorLocked ? (
                    <Input value={effectiveCountryName} disabled />
                  ) : (
                    <ReferenceCombobox
                      id="country"
                      options={countryOptions}
                      value={country}
                      onChange={(next) => {
                        setCountry(next);
                        if (next?.kind !== 'new') setIsoCode('');
                      }}
                      placeholder="Выберите или впишите новую"
                      createLabel={(input) => `Создать страну «${input}»`}
                      disabled={!administrator}
                      loading={countriesLoading}
                      invalid={Boolean(errors.country)}
                    />
                  )}
                  {fieldError('country')}
                </div>
              </div>

              {country?.kind === 'new' && !administratorLocked && (
                <div className="sm:w-40">
                  <Label htmlFor="iso-code">Код ISO (необязательно)</Label>
                  <Input
                    id="iso-code"
                    value={isoCode}
                    onChange={(event) => setIsoCode(event.target.value)}
                    placeholder="KZ"
                    maxLength={3}
                  />
                </div>
              )}

              {administratorLocked && (
                <p className="text-xs text-muted-foreground">
                  Страна принадлежит выбранной записи справочника — чтобы
                  изменить её, правьте самого администратора, а не заявку.
                </p>
              )}
            </CardContent>
          </Card>

          {/* ─── Программа ─────────────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Программа</CardTitle>
              <CardDescription>
                Программа и статья расходов — одна запись справочника. Вместе с
                администратором и годом они образуют уникальную бюджетную
                строку. В списках программа подписана как «код название».
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="program">Название программы</Label>
                <ReferenceCombobox
                  id="program"
                  options={programOptions}
                  value={program}
                  onChange={(next) => {
                    setProgram(next);
                    if (next?.kind !== 'new') {
                      setExpenseItem('');
                      setProgramCode('');
                    }
                  }}
                  placeholder="Выберите или впишите новую"
                  searchPlaceholder="Поиск по программе или статье…"
                  createLabel={(input) => `Создать программу «${input}»`}
                  loading={programsLoading}
                  invalid={Boolean(errors.program)}
                />
                {fieldError('program')}
              </div>

              <div>
                <Label htmlFor="expense-item">Статья расходов</Label>
                <Input
                  id="expense-item"
                  value={effectiveExpenseItem}
                  onChange={(event) => setExpenseItem(event.target.value)}
                  disabled={programLocked || !program}
                  placeholder="Оборудование"
                  className={errors.expenseItem ? 'border-destructive' : undefined}
                />
                {fieldError('expenseItem')}
              </div>

              <div className="sm:w-40">
                <Label htmlFor="program-code">Код (необязательно)</Label>
                <Input
                  id="program-code"
                  value={effectiveProgramCode}
                  onChange={(event) => setProgramCode(event.target.value)}
                  disabled={programLocked || !program}
                  placeholder="EDU-01"
                  maxLength={50}
                />
              </div>
            </CardContent>
          </Card>

          {/* ─── Бюджет ────────────────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Бюджет</CardTitle>
              <CardDescription>
                Выделяемая сумма. Остаток по ней будет считаться сам, из
                договоров — вручную его никто не правит.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="sm:col-span-1">
                  <Label htmlFor="amount">Сумма</Label>
                  <Input
                    id="amount"
                    inputMode="decimal"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    placeholder="5000000.00"
                    className={errors.amount ? 'border-destructive' : undefined}
                  />
                  {fieldError('amount')}
                </div>

                <div>
                  <Label htmlFor="currency">Валюта</Label>
                  <Select value={currency} onValueChange={setCurrency}>
                    <SelectTrigger id="currency">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CURRENCIES.map((code) => (
                        <SelectItem key={code} value={code}>
                          {code}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="period-year">Бюджетный год</Label>
                  <Input
                    id="period-year"
                    inputMode="numeric"
                    value={periodYear}
                    onChange={(event) => setPeriodYear(event.target.value)}
                    className={errors.periodYear ? 'border-destructive' : undefined}
                  />
                  {fieldError('periodYear')}
                </div>
              </div>

              <div>
                <Label htmlFor="note">Примечание</Label>
                <Textarea
                  id="note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={3}
                  placeholder="Необязательно"
                />
              </div>
            </CardContent>
          </Card>

          {/* ─── Что будет создано ─────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Будет создано</CardTitle>
            </CardHeader>
            <CardContent className="text-sm space-y-1">
              {administrator?.kind === 'new' && (
                <p>
                  Администратор бюджета — проект{' '}
                  <strong>{administrator.label}</strong>
                  {country && <> в стране «{country.label}»</>}
                </p>
              )}
              {country?.kind === 'new' && administrator?.kind === 'new' && (
                <p>
                  Страна <strong>{country.label}</strong>
                </p>
              )}
              {program?.kind === 'new' && (
                <p>
                  Программа{' '}
                  <strong>
                    {[programCode.trim(), program.label].filter(Boolean).join(' ')}
                  </strong>
                  {expenseItem && <> — статья «{expenseItem}»</>}
                </p>
              )}
              <Separator className="my-2" />
              <p>
                Бюджетная строка{' '}
                <strong>
                  {amount || '—'} {currency}
                </strong>{' '}
                на {periodYear || '—'} год
                {(existingAdministrator || administrator?.kind === 'new') && (
                  <>
                    {' '}
                    для {existingAdministrator?.display_name ?? administrator?.label}
                  </>
                )}
              </p>
              <p className="text-xs text-muted-foreground pt-1">
                Всё в одной транзакции: если бюджет не пройдёт, справочники
                тоже не заведутся.
              </p>
            </CardContent>
          </Card>

          <div className="flex gap-3">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Создать бюджет
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate('/contracts/budgets')}
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

export default BudgetCreate;
