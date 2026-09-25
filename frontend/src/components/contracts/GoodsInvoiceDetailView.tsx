import { useQuery } from '@tanstack/react-query';
import { Package } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { BudgetOverrunNotice } from '@/components/contracts/BudgetOverrunNotice';
import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { formatMoment, formatMoney } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props { id: number; embedded?: boolean; }
const approvalLabel: Record<string, string> = { draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано', rejected: 'Отклонено', rework: 'На доработке' };
const statusLabel: Record<string, string> = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает бухгалтерию', closed: 'Закрыт' };

export default function GoodsInvoiceDetailView({ id }: Props) {
  const { data: invoice, isLoading, isError } = useQuery({ queryKey: ['contracts', 'goods-invoice', id], queryFn: () => contractsApi.getGoodsInvoice(id).then(response => response.data), enabled: Number.isFinite(id) });
  if (isLoading) return <DetailSkeleton />;
  if (isError || !invoice) return <p className="text-sm text-destructive">Накладная не найдена или недоступна.</p>;
  return <Card><CardHeader className="pb-3"><CardTitle className="flex flex-wrap items-center gap-2 text-base"><Package className="h-4 w-4" />Товарная накладная<Badge variant={invoice.status === 'closed' ? 'default' : 'secondary'}>{statusLabel[invoice.status] ?? invoice.status}</Badge></CardTitle></CardHeader><CardContent className="space-y-6">
    <section className="rounded-lg border bg-muted/30 p-4"><p className="text-sm text-muted-foreground">Сумма по накладной</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{formatMoney(invoice.amount, invoice.currency)}</p></section>
    <BudgetOverrunNotice overrun={invoice.budget_overrun} currency={invoice.currency} />
    <section><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">По договору</p><dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Администратор">{invoice.administrator_name}</Field><Field label="Договор">{invoice.agreement_number} — {invoice.agreement_name}</Field><Field label="Контрагент">{invoice.counterparty_name}</Field></dl></section>
    <section className="border-t pt-5"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Сведения о записи</p><dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Согласование">{approvalLabel[invoice.approval_state] ?? invoice.approval_state}</Field><Field label="Создан">{formatMoment(invoice.created_at)}</Field></dl></section>
  </CardContent></Card>;
}
