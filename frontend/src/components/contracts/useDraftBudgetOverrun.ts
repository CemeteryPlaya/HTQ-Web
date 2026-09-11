import { useQuery } from '@tanstack/react-query';

import { contractsApi } from '@/api/contracts';
import type { Agreement } from '@/types/contracts';

// Отдельно от `BudgetOverrunNotice.tsx`: файл с компонентом должен
// экспортировать только компоненты, иначе ломается fast refresh.

const MONEY_RE = /^\d+([.,]\d{1,2})?$/;

/** Денежная строка → целые копейки, со знаком: остаток программы бывает отрицательным. */
function toKopecks(value: string): bigint {
  const text = value.trim().replace(',', '.');
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = text.replace(/^[-+]/, '').split('.');
  const abs = BigInt(whole || '0') * 100n + BigInt(`${fraction}00`.slice(0, 2));
  return negative ? -abs : abs;
}

/** Положительные копейки → «1234.50». */
function fromKopecks(kopecks: bigint): string {
  const digits = kopecks.toString().padStart(3, '0');
  return `${digits.slice(0, -2)}.${digits.slice(-2)}`;
}

/**
 * Перерасход, который даст ещё НЕ сохранённая оплата `amount` по договору
 * `agreement` (см. `BudgetOverrunNotice`). `null` — не выходит за лимит,
 * договор не открытый или сумма ещё не введена. Новая оплата в остатке
 * программы не сидит, поэтому сравнивается с остатком целиком.
 */
export function useDraftBudgetOverrun(
  agreement: Pick<Agreement, 'contract_type' | 'budget_line_id'> | undefined,
  amount: string,
): string | null {
  const isOpen = agreement?.contract_type === 'framework';
  // Тот же ключ, что у карточки договора, — строка бюджета берётся из кэша.
  const { data: line } = useQuery({
    queryKey: ['contracts', 'budget-line', agreement?.budget_line_id],
    queryFn: () => contractsApi.getBudgetLine(agreement!.budget_line_id).then((r) => r.data),
    enabled: isOpen,
  });
  if (!isOpen || !line || !MONEY_RE.test(amount.trim())) return null;
  const over = toKopecks(amount) - toKopecks(line.remaining);
  return over > 0n ? fromKopecks(over) : null;
}
