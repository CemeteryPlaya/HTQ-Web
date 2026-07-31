import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Plus, Trash2, Wallet } from 'lucide-react';
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
import type { BudgetFullCreatePayload, BudgetProgramLine } from '@/types/contracts';

/**
 * Заявка на бюджет — одна форма на всё.
 *
 * Заполняющий вводит и сами бюджеты, и справочники, от которых те зависят:
 * администратора (проект + страна) и программы (название, статья
 * расходов). Уходить в три отдельных экрана справочников и возвращаться не
 * нужно — в этом весь смысл страницы.
 *
 * Программ в заявке НЕСКОЛЬКО, у каждой своя сумма и своё примечание:
 * бюджет проекта на год так и устроен — программы в нём финансируются по
 * отдельности, и общая сумма на всех всё равно делилась бы обратно. Год,
 * валюта и администратор при этом общие: бюджет — это «бюджет такого-то
 * проекта на такой-то год», и итог по нему складывается в одно число.
 *
 * На бэкенде получается ОДИН `Budget` со строками `BudgetLine` — по одной
 * на программу. Согласуется он целиком: утвердить половину списка программ
 * нельзя.
 *
 * Ничего не создаётся, пока форму не отправили: комбобоксы держат выбор в
 * состоянии, а на submit уходит ОДИН запрос (POST /budgets/full), который
 * бэкенд разбирает в одной транзакции. Брошенная на полпути заявка не
 * оставляет за собой полупустых записей в справочниках, а упавшая на одной
 * из программ откатывает и бюджет, и остальные строки, и заведённые по пути
 * страну/программы — полубюджетов не бывает.
 */

const CURRENCIES = ['KZT', 'USD', 'EUR', 'RUB'];

/** Сумма: целое или с двумя знаками. Без разделителей разрядов. */
const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

/**
 * Колонка `BudgetLine.amount` — `DecimalField(18, 2)`, то есть 16 знаков до
 * запятой. Проверяем здесь, чтобы не отправлять заведомо отбиваемое.
 */
const AMOUNT_MAX_INT_DIGITS = 16;

type Errors = Record<string, string>;

/** Строка заявки: одна программа со своей суммой. */
interface ProgramRow {
  /** Стабильный ключ списка — по индексу нельзя, строки удаляются из середины. */
  key: string;
  program: ReferenceValue;
  expenseItem: string;
  programCode: string;
  amount: string;
  note: string;
}

let rowSeq = 0;
const emptyRow = (): ProgramRow => ({
  key: `row-${rowSeq++}`,
  program: null,
  expenseItem: '',
  programCode: '',
  amount: '',
  note: '',
});

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

  const [rows, setRows] = useState<ProgramRow[]>([emptyRow()]);

  const [currency, setCurrency] = useState('KZT');
  const [periodYear, setPeriodYear] = useState(String(new Date().getFullYear()));

  const [errors, setErrors] = useState<Errors>({});

  const patchRow = (key: string, patch: Partial<ProgramRow>) =>
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const addRow = () => setRows((prev) => [...prev, emptyRow()]);
  // Последнюю строку не удаляем, а очищаем: заявка без единой программы —
  // это не состояние, из которого форма умеет отправляться.
  const removeRow = (key: string) =>
    setRows((prev) => (prev.length === 1 ? [emptyRow()] : prev.filter((row) => row.key !== key)));

  // Выбран существующий администратор — проект и страна принадлежат ЕМУ,
  // и правка их здесь означала бы правку чужой записи справочника, а не
  // заполнение заявки. Поэтому поля показываются заполненными и закрытыми.
  const existingAdministrator =
    administrator?.kind === 'existing'
      ? administrators.find((row) => row.id === administrator.id)
      : undefined;

  const administratorLocked = Boolean(existingAdministrator);

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
  const countryOptions = useMemo(
    () => countries.map((row) => ({ id: row.id, label: row.name, hint: row.iso_code })),
    [countries],
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

  /** Программа, уже занятая другой строкой, из списка убирается: две строки
   *  на одну программу в одном бюджете — дубль, который бэкенд всё равно
   *  отобьёт (уникальность «бюджет × программа»). Дешевле не дать его
   *  собрать, чем объяснять отказ после отправки. */
  const optionsForRow = (key: string) => {
    const taken = new Set(
      rows
        .filter((row) => row.key !== key && row.program?.kind === 'existing')
        .map((row) => (row.program as { id: number }).id),
    );
    return programOptions.filter((option) => !taken.has(option.id));
  };

  const findProgram = (value: ReferenceValue) =>
    value?.kind === 'existing' ? programs.find((row) => row.id === value.id) : undefined;

  // ─── Итог ──────────────────────────────────────────────────────────────
  // Считается по валидным суммам: пока строка недозаполнена, итог
  // показывает то, что уже введено, а не «—» на всю форму.
  const total = useMemo(
    () =>
      rows.reduce((sum, row) => {
        const raw = row.amount.trim().replace(',', '.');
        return AMOUNT_RE.test(row.amount.trim()) ? sum + Number(raw) : sum;
      }, 0),
    [rows],
  );
  const totalLabel = useMemo(
    () => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(total),
    [total],
  );

  // ─── Проверка ──────────────────────────────────────────────────────────
  const validate = (): Errors => {
    const next: Errors = {};

    if (!administrator) {
      next.administrator = 'Выберите проект или впишите новый';
    } else if (administrator.kind === 'new' && !country) {
      next.country = 'Выберите страну или впишите новую';
    }

    const year = Number(periodYear);
    if (!Number.isInteger(year) || year < 2000 || year > 2100) {
      next.periodYear = 'Год в диапазоне 2000–2100';
    }

    // Дубли среди НОВЫХ программ: существующие уже отфильтрованы из списка,
    // а вписанные вручную сверяются по паре «название + статья», как их
    // схлопнет бэкенд (`_resolve_program`).
    const seenNew = new Set<string>();

    rows.forEach((row) => {
      const at = `rows.${row.key}`;

      if (!row.program) {
        next[`${at}.program`] = 'Выберите программу или впишите новую';
      } else if (row.program.kind === 'new') {
        if (!row.expenseItem.trim()) {
          next[`${at}.expenseItem`] = 'Укажите статью расходов';
        } else {
          const key = `${row.program.label.trim().toLowerCase()}|${row.expenseItem
            .trim()
            .toLowerCase()}`;
          if (seenNew.has(key)) {
            next[`${at}.program`] = 'Эта программа уже есть в заявке';
          }
          seenNew.add(key);
        }
      }

      const amount = row.amount.trim();
      if (!amount) {
        next[`${at}.amount`] = 'Укажите сумму';
      } else if (!AMOUNT_RE.test(amount)) {
        next[`${at}.amount`] = 'Число, максимум два знака после запятой';
      } else if (amount.split(/[.,]/)[0].length > AMOUNT_MAX_INT_DIGITS) {
        next[`${at}.amount`] = 'Сумма слишком большая';
      }
    });

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
                : { name: country!.label.trim(), iso_code: isoCode.trim().toUpperCase() },
          },
    programs: rows.map<BudgetProgramLine>((row) => ({
      program:
        row.program!.kind === 'existing'
          ? { id: row.program!.id }
          : {
              name: row.program!.label.trim(),
              expense_item: row.expenseItem.trim(),
              code: row.programCode.trim(),
            },
      // Запятую в сумме бэкенд не примет — Decimal ждёт точку.
      amount: row.amount.trim().replace(',', '.'),
      note: row.note.trim(),
    })),
    period_year: Number(periodYear),
    currency,
    // Примечание — на строках; у бюджета своё поле есть, но форма его не
    // собирает: заполняющий пишет обоснование против конкретной программы.
    note: '',
  });

  const mutation = useMutation({
    mutationFn: () => contractsApi.createBudgetFull(buildPayload()).then((r) => r.data),
    onSuccess: (budget) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(
        `Бюджет ${budget.period_year} создан: ${budget.lines.length} ` +
          `${budget.lines.length === 1 ? 'программа' : 'программы'}, ` +
          `${budget.allocated} ${budget.currency}`,
      );
      // На карточку, а не в список: заполняющий только что собрал бюджет
      // целиком и первым делом захочет его проверить и отправить на
      // согласование.
      navigate(`/contracts/budgets/${budget.id}`);
    },
    onError: (error: any) => {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;

      // 409 — заявка корректна по форме, но противоречит данным (такая
      // связка уже есть). Текст называет конкретную программу, показываем
      // как есть.
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
                Держатель бюджетных строк — проект в стране. Денег на самой
                записи нет: суммы живут на бюджетах, и у одного проекта их
                несколько — по одному под каждую программу.
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

          {/* ─── Общее для заявки ──────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Год и валюта</CardTitle>
              <CardDescription>
                Общие на всю заявку: она и есть бюджет проекта на год, а в
                одной валюте суммы программ складываются в итог.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
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
            </CardContent>
          </Card>

          {/* ─── Программы ─────────────────────────────────────────────── */}
          <Card>
            <CardHeader>
              <CardTitle>Программы и суммы</CardTitle>
              <CardDescription>
                По строке на программу — у каждой своя сумма. Программа и
                статья расходов вместе образуют одну запись справочника; с
                администратором и годом они дают уникальную бюджетную строку.
                В списках программа подписана как «код название».
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {rows.map((row, index) => {
                const at = `rows.${row.key}`;
                const existing = findProgram(row.program);
                const locked = Boolean(existing);

                return (
                  <div
                    key={row.key}
                    className="rounded-lg border p-4 space-y-4 relative"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-muted-foreground">
                        Программа {index + 1}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => removeRow(row.key)}
                        aria-label={`Убрать программу ${index + 1}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <Label htmlFor={`${row.key}-program`}>Название программы</Label>
                        <ReferenceCombobox
                          id={`${row.key}-program`}
                          options={optionsForRow(row.key)}
                          value={row.program}
                          onChange={(next) =>
                            patchRow(row.key, {
                              program: next,
                              // Статья и код относились к прежнему выбору.
                              ...(next?.kind !== 'new'
                                ? { expenseItem: '', programCode: '' }
                                : {}),
                            })
                          }
                          placeholder="Выберите или впишите новую"
                          searchPlaceholder="Поиск по программе или статье…"
                          createLabel={(input) => `Создать программу «${input}»`}
                          loading={programsLoading}
                          invalid={Boolean(errors[`${at}.program`])}
                        />
                        {fieldError(`${at}.program`)}
                      </div>

                      <div>
                        <Label htmlFor={`${row.key}-expense-item`}>Статья расходов</Label>
                        <Input
                          id={`${row.key}-expense-item`}
                          value={existing?.expense_item ?? row.expenseItem}
                          onChange={(event) =>
                            patchRow(row.key, { expenseItem: event.target.value })
                          }
                          disabled={locked || !row.program}
                          placeholder="Оборудование"
                          className={
                            errors[`${at}.expenseItem`] ? 'border-destructive' : undefined
                          }
                        />
                        {fieldError(`${at}.expenseItem`)}
                      </div>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        {/* Код программы — отдельное поле, а НЕ часть вводимого
                            названия: подпись существующих программ в списке —
                            «код название», и без своего поля заполняющий
                            вписывал бы код в название, чтобы получить такую же
                            строку. */}
                        <Label htmlFor={`${row.key}-code`}>Код (необязательно)</Label>
                        <Input
                          id={`${row.key}-code`}
                          value={existing?.code ?? row.programCode}
                          onChange={(event) =>
                            patchRow(row.key, { programCode: event.target.value })
                          }
                          disabled={locked || !row.program}
                          placeholder="EDU-01"
                          maxLength={50}
                        />
                      </div>

                      <div>
                        <Label htmlFor={`${row.key}-amount`}>Сумма, {currency}</Label>
                        <Input
                          id={`${row.key}-amount`}
                          inputMode="decimal"
                          value={row.amount}
                          onChange={(event) =>
                            patchRow(row.key, { amount: event.target.value })
                          }
                          placeholder="5000000.00"
                          className={
                            errors[`${at}.amount`] ? 'border-destructive' : undefined
                          }
                        />
                        {fieldError(`${at}.amount`)}
                      </div>
                    </div>

                    <div>
                      <Label htmlFor={`${row.key}-note`}>Примечание</Label>
                      <Textarea
                        id={`${row.key}-note`}
                        value={row.note}
                        onChange={(event) => patchRow(row.key, { note: event.target.value })}
                        rows={2}
                        placeholder="Необязательно"
                      />
                    </div>
                  </div>
                );
              })}

              <Button type="button" variant="outline" onClick={addRow} className="w-full">
                <Plus className="mr-2 h-4 w-4" />
                Добавить программу
              </Button>

              <Separator />

              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted-foreground">
                  Итого по заявке ({rows.length}{' '}
                  {rows.length === 1 ? 'строка' : rows.length < 5 ? 'строки' : 'строк'})
                </span>
                <span className="text-lg font-semibold tabular-nums">
                  {totalLabel} {currency}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Остаток по каждой строке будет считаться сам, из договоров —
                вручную его никто не правит.
              </p>
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
              {rows
                .filter((row) => row.program?.kind === 'new')
                .map((row) => (
                  <p key={row.key}>
                    Программа{' '}
                    <strong>
                      {[row.programCode.trim(), row.program!.label].filter(Boolean).join(' ')}
                    </strong>
                    {row.expenseItem && <> — статья «{row.expenseItem}»</>}
                  </p>
                ))}
              <Separator className="my-2" />
              {rows.map((row, index) => (
                <p key={row.key}>
                  Бюджетная строка{' '}
                  <strong>
                    {row.amount || '—'} {currency}
                  </strong>{' '}
                  — {row.program?.label ?? `программа ${index + 1} не выбрана`}
                </p>
              ))}
              <p>
                На {periodYear || '—'} год
                {(existingAdministrator || administrator?.kind === 'new') && (
                  <>
                    {' '}
                    для {existingAdministrator?.display_name ?? administrator?.label}
                  </>
                )}
              </p>
              <p className="text-xs text-muted-foreground pt-1">
                Всё в одной транзакции: если хотя бы одна строка не пройдёт,
                не заведутся ни остальные, ни справочники.
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
