import { useQuery } from '@tanstack/react-query';
import { FileCheck2 } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props { id: number; embedded?: boolean; }

const statusLabel: Record<string, string> = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает оплаты бухгалтерией', awaiting_advance_report: 'Ожидает авансовый отчёт' };

/** Read-only card for an accountable-funds request in a Signoff process. */
export default function AccountableFundsRequestDetailView({ id }: Props) {
  const { data: request, isLoading, isError } = useQuery({ queryKey: ['contracts', 'accountable-funds-request', id], queryFn: () => contractsApi.getAccountableFundsRequest(id).then((r) => r.data), enabled: Number.isFinite(id) });
  if (isLoading) return <DetailSkeleton />;
  if (isError || !request) return <p className="text-sm text-destructive">Заявка не найдена или недоступна.</p>;
  return <Card><CardHeader className="pb-3"><CardTitle className="flex flex-wrap items-center gap-2 text-base"><FileCheck2 className="h-4 w-4" />Заявка на подотчётные средства<Badge variant={request.accounting_paid ? 'default' : 'secondary'}>{statusLabel[request.status]}</Badge></CardTitle></CardHeader><CardContent className="space-y-5"><section className="rounded-lg border bg-muted/30 p-4"><p className="text-sm text-muted-foreground">Сумма</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{formatAmount(request.amount)} {request.currency}</p></section><dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Администратор">{request.administrator_name}</Field><Field label="Программа">{request.program_name} ({request.period_year})</Field><Field label="Цель" className="sm:col-span-2">{request.goal}</Field><Field label="Создана">{formatMoment(request.created_at)}</Field><Field label="Оплата бухгалтерией">{request.accounting_paid ? 'Оплачено' : 'Не оплачено'}</Field></dl></CardContent></Card>;
}
