import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Wallet } from 'lucide-react';
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
import { contractsApi } from '@/api/contracts';
import type { Administrator, Budget, BudgetStatus } from '@/types/contracts';

/**
 * Правка ШАПКИ бюджета: администратор, год, валюта, статус, примечание.
 *
 * Суммы и программы здесь НЕ правятся — они живут на строках (`BudgetLine`)
 * и меняются своими операциями (см. PATCH-схему `BudgetUpdate` на бэкенде),
 * поэтому таблицы программ на этой форме нет.
 *
 * Валюта запирается, если к строкам бюджета уже привязан хоть один договор:
 * бэкенд такую смену отбивает 409-м (`update_budget`), и незачем давать
 * собрать заведомо отклоняемую правку. Операция админская — то же право
 * показывает кнопка «Редактировать» в карточке.
 *
 * Загрузчик и форма разделены, как в `InvoiceEdit`: `<Select>` встаёт с
 * нужным значением, только если оно есть с первого рендера.
 */

const CURRENCIES = ['KZT', 'USD', 'EUR', 'RUB'];

type Errors = Record<string, string>;

const BudgetEdit = () => {
  const { id } = useParams<{ id: string }>();
  const budgetId = Number(id);

  const { data: budget, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'budget', budgetId],
    queryFn: () => contractsApi.getBudget(budgetId).then((r) => r.data),
    enabled: Number.isFinite(budgetId),
  });
  const { data: administrators = [], isLoading: administratorsLoading } = useQuery({
    queryKey: ['contracts', 'administrators'],
    queryFn: () => contractsApi.listAdministrators({ is_active: true }).then((r) => r.data),
  });
  // Есть ли у бюджета договоры — от этого зависит, можно ли менять валюту.
  const { data: agreements = [], isLoading: agreementsLoading } = useQuery({
    queryKey: ['contracts', 'budget', budgetId, 'agreements'],
    queryFn: () => contractsApi.listBudgetAgreements(budgetId).then((r) => r.data),
    enabled: Number.isFinite(budgetId),
  });

  const backTo = `/contracts/budgets/${budgetId}`;
  const loading = isLoading || !budget || administratorsLoading || agreementsLoading;

  return (
    <ContractsShell>
      <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to={backTo}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К карточке бюджета
          </Link>
          <div className="flex items-center gap-3">
            <Wallet className="h-7 w-7 text-muted-foreground" />
            <h1 className="text-3xl font-bold">Правка бюджета</h1>
          </div>
        </div>

        {isError ? (
          <p className="text-sm text-destructive">Бюджет не найден или недоступен.</p>
        ) : loading ? (
          <div className="space-y-4">
            <Skeleton className="h-64 w-full" />
          </div>
        ) : (
          <BudgetEditForm
            budget={budget}
            administrators={administrators}
            hasAgreements={agreements.length > 0}
          />
        )}
      </div>
    </ContractsShell>
  );
};

interface FormProps {
  budget: Budget;
  administrators: Administrator[];
  hasAgreements: boolean;
}

/** Тело формы. Монтируется только с готовыми данными — состояние
 *  инициализируется прямо из них (см. докстринг загрузчика). */
const BudgetEditForm = ({ budget, administrators, hasAgreements }: FormProps) => {
  const budgetId = budget.id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  const [administratorId, setAdministratorId] = useState(String(budget.administrator_id));
  const [periodYear, setPeriodYear] = useState(String(budget.period_year));
  const [currency, setCurrency] = useState(budget.currency);
  const [status, setStatus] = useState<BudgetStatus>(budget.status);
  const [note, setNote] = useState(budget.note);
  const [errors, setErrors] = useState<Errors>({});

  const administratorOptions = useMemo(
    () =>
      administrators.map((row) => ({
        id: row.id,
        label: row.project_name,
        hint: row.country_name,
      })),
    [administrators],
  );

  // Текущего администратора могло не быть в списке активных — добавляем его,
  // чтобы `<Select>` показал подпись, а не пустой плейсхолдер.
  const administratorMissing =
    administrators.every((row) => String(row.id) !== administratorId);

  const statusOptions = enums?.budget_status ?? [
    { value: 'active', label: 'Активен' },
    { value: 'closed', label: 'Закрыт' },
  ];

  // Валюта — только из фиксированного набора; если у бюджета валюта вне его
  // (маловероятно, но данные бывают), добавляем её, чтобы не потерять выбор.
  const currencyOptions = CURRENCIES.includes(currency)
    ? CURRENCIES
    : [currency, ...CURRENCIES];

  const validate = (): Errors => {
    const next: Errors = {};
    if (!administratorId) next.administrator = 'Выберите администратора бюджета';
    const year = Number(periodYear);
    if (!Number.isInteger(year) || year < 2000 || year > 2100) {
      next.periodYear = 'Год в диапазоне 2000–2100';
    }
    return next;
  };

  const mutation = useMutation({
    mutationFn: () =>
      contractsApi
        .updateBudget(budgetId, {
          administrator_id: Number(administratorId),
          period_year: Number(periodYear),
          currency,
          status,
          note: note.trim(),
        })
        .then((r) => r.data),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(`Бюджет ${row.period_year} сохранён`);
      navigate(`/contracts/budgets/${budgetId}`);
    },
    onError: (error: unknown) => {
      const err = error as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const httpStatus = err.response?.status;
      const detail = err.response?.data?.detail;
      // 409 — дубль «администратор × год × валюта», запертый согласованием
      // бюджет либо смена валюты при живых договорах; 403 — правит не
      // администратор.
      if ((httpStatus === 409 || httpStatus === 403) && typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item) => (item as { msg?: string }).msg).join('; '));
        return;
      }
      toast.error('Не удалось сохранить бюджет');
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

  const backTo = `/contracts/budgets/${budgetId}`;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Шапка бюджета</CardTitle>
          <CardDescription>
            Суммы и программы правятся на карточке — здесь только общие
            свойства бюджета.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="administrator">Администратор бюджета</Label>
            <Select value={administratorId} onValueChange={setAdministratorId}>
              <SelectTrigger
                id="administrator"
                className={errors.administrator ? 'border-destructive' : undefined}
              >
                <SelectValue placeholder="Выберите" />
              </SelectTrigger>
              <SelectContent>
                {administratorMissing && (
                  <SelectItem value={administratorId}>
                    {budget.administrator_name}
                  </SelectItem>
                )}
                {administratorOptions.map((row) => (
                  <SelectItem key={row.id} value={String(row.id)}>
                    {row.label} — {row.hint}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {fieldError('administrator')}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
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
              <Select value={currency} onValueChange={setCurrency} disabled={hasAgreements}>
                <SelectTrigger id="currency">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {currencyOptions.map((code) => (
                    <SelectItem key={code} value={code}>
                      {code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {hasAgreements && (
                <p className="text-xs text-muted-foreground mt-1">
                  К строкам бюджета привязаны договоры — валюту сменить нельзя.
                </p>
              )}
            </div>

            <div>
              <Label htmlFor="status">Статус</Label>
              <Select
                value={status}
                onValueChange={(value) => setStatus(value as BudgetStatus)}
              >
                <SelectTrigger id="status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {statusOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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

export default BudgetEdit;
