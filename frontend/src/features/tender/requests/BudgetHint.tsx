/**
 * Подсказка остатка статьи бюджета в форме заявки на тендер (план §3.5):
 * лимит, задействовано и доступный остаток статьи в бюджете проекта
 * (`requests/budget` → `bpp.budget_available`) и остаток после плановой
 * суммы заявки по этой статье. Это подсказка, а не запрет: резервирует
 * бюджет и проверяет остаток ЗЗ модуля БЗО при отправке.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Skeleton } from '@/components/ui/skeleton';
import { lessThan, subMoney } from '@/features/bpp/budgets/cents';
import { formatMoney } from '@/features/bpp/format';

import { tenderRequestKeys, tenderRequestsApi, type InitiatorRole } from './api';

interface Props {
  projectId: string;
  articleId: string;
  /** Роль заявки: остаток считается в правах этой роли. */
  role: InitiatorRole;
  articleLabel: string;
  /** Плановая сумма заявки по статье (позиции, доставка, СМР). */
  plan: string;
}

export function BudgetHint({ projectId, articleId, role, articleLabel, plan }: Props) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useQuery({
    queryKey: tenderRequestKeys.budget(projectId, articleId, role),
    queryFn: () => tenderRequestsApi.budget(projectId, articleId, role),
  });

  const after = data ? subMoney(data.available, plan) : null;
  const over = after !== null && lessThan(after, 0);
  const money = (value: string) => formatMoney(value, data?.currency_code);

  return (
    <div data-testid={`budget-hint-${articleId}`} className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="font-medium">{articleLabel}</div>
      {isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : isError || !data ? (
        <p className="text-xs text-muted-foreground">
          {t('tender.requests.budgetUnavailable', 'Остаток статьи сейчас не получить — его проверят при отправке.')}
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-5">
            {([
              [t('tender.requests.budgetLimit', 'Лимит статьи'), money(data.limit)],
              [t('tender.requests.budgetCommitted', 'Задействовано'), money(data.committed)],
              [t('tender.requests.budgetAvailable', 'Доступно'), money(data.available)],
              [t('tender.requests.budgetPlan', 'План по заявке'), money(plan)],
              [t('tender.requests.budgetAfter', 'Остаток после заявки'), money(after as string)],
            ] as [string, string][]).map(([label, value], index) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className={index === 4 && over ? 'font-medium text-destructive' : 'font-medium'}>{value}</dd>
              </div>
            ))}
          </dl>
          {over && (
            <p role="alert" className="text-xs text-destructive">
              {t('tender.requests.budgetOver',
                'Плановая сумма больше доступного остатка статьи — ЗЗ по ней не пройдёт проверку бюджета.')}
            </p>
          )}
        </>
      )}
    </div>
  );
}
