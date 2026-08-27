import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { formatMoment, formatMoney } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props { id: number; embedded?: boolean; }
const approvalLabel: Record<string, string> = { draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано', rejected: 'Отклонено', rework: 'На доработке' };
const statusLabel: Record<string, string> = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает бухгалтерию', closed: 'Закрыт' };

export default function CompletionActDetailView({ id }: Props) {
  const { data: act, isLoading, isError } = useQuery({ queryKey: ['contracts', 'completion-act', id], queryFn: () => contractsApi.getCompletionAct(id).then(response => response.data), enabled: Number.isFinite(id) });
  if (isLoading) return <DetailSkeleton />;
  if (isError || !act) return <p className="text-sm text-destructive">Акт не найден или недоступен.</p>;
  return <Card><CardHeader className="pb-3"><CardTitle className="flex flex-wrap items-center gap-2 text-base"><FileText className="h-4 w-4" />Акт выполненных работ<Badge variant={act.status === 'closed' ? 'default' : 'secondary'}>{statusLabel[act.status] ?? act.status}</Badge></CardTitle></CardHeader><CardContent className="space-y-6">
    <section className="rounded-lg border bg-muted/30 p-4"><p className="text-sm text-muted-foreground">Сумма по акту</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{formatMoney(act.amount, act.currency)}</p></section>
    <section><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">По договору</p><dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Администратор">{act.administrator_name}</Field><Field label="Договор">{act.agreement_number} — {act.agreement_name}</Field><Field label="Контрагент">{act.counterparty_name}</Field></dl></section>
    <section className="border-t pt-5"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Сведения о записи</p><dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Согласование">{approvalLabel[act.approval_state] ?? act.approval_state}</Field><Field label="Создан">{formatMoment(act.created_at)}</Field></dl></section>
  </CardContent></Card>;
}
