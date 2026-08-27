import { useQuery } from '@tanstack/react-query';
import { Download, FileText } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { formatMoment, formatMoney } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props { id: number; embedded?: boolean; }
const approvalLabel: Record<string, string> = { draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано', rejected: 'Отклонено', rework: 'На доработке' };

export default function AdvanceReportDetailView({ id }: Props) {
  const { data: report, isLoading, isError } = useQuery({ queryKey: ['contracts', 'advance-report', id], queryFn: () => contractsApi.getAdvanceReport(id).then(response => response.data), enabled: Number.isFinite(id) });
  if (isLoading) return <DetailSkeleton />;
  if (isError || !report) return <p className="text-sm text-destructive">Авансовый отчёт не найден или недоступен.</p>;
  const openFile = () => contractsApi.getAdvanceReportFileUrl(report.id)
    .then(response => window.open(response.data.url, '_blank', 'noopener,noreferrer'));
  return <Card><CardHeader className="pb-3"><CardTitle className="flex flex-wrap items-center gap-2 text-base"><FileText className="h-4 w-4" />Авансовый отчёт<Badge variant={report.approval_state === 'approved' ? 'default' : 'secondary'}>{approvalLabel[report.approval_state] ?? report.approval_state}</Badge></CardTitle></CardHeader><CardContent className="space-y-5"><dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2"><Field label="Наименование затрат">{report.expense_name}</Field><Field label="Сумма">{formatMoney(report.amount, report.currency)}</Field><Field label="Создан">{formatMoment(report.created_at)}</Field></dl><Button variant="outline" onClick={openFile}><Download className="mr-2 h-4 w-4" />Открыть приложенный файл</Button></CardContent></Card>;
}
