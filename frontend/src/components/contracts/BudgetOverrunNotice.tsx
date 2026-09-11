import { AlertTriangle } from 'lucide-react';

import { formatMoney } from '@/components/contracts/format';

/**
 * Перерасход программы оплатой по ОТКРЫТОМУ договору.
 *
 * Только предупреждение, не запрет (так решил заказчик): у стандартного
 * договора бюджет охраняет цепочка «оплата ≤ остаток договора ≤ остаток
 * программы», а у открытого суммы нет — и без этого предупреждения оплата на
 * любую сумму уходила бы в программу молча. Сохранить и согласовать такую
 * оплату можно; её должны увидеть автор, согласующий и бухгалтер.
 *
 * `overrun` приходит из поля `budget_overrun` карточки оплаты (бэкенд:
 * `budget_calc.open_payment_overrun`), а на форме создания — из
 * `useDraftBudgetOverrun`.
 */
export function BudgetOverrunNotice({
  overrun,
  currency,
}: {
  overrun: string | null | undefined;
  currency: string;
}) {
  if (!overrun) return null;
  return (
    <div
      role="alert"
      className="flex gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-500" />
      <div>
        С этой оплатой программа выходит за лимит бюджета на{' '}
        <strong className="tabular-nums">{formatMoney(overrun, currency)}</strong>. Договор
        открытый, суммы договора, которая ограничила бы оплату, у него нет — сверьте с лимитом
        программы.
      </div>
    </div>
  );
}
