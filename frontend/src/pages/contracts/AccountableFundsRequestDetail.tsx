import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FileCheck2, Loader2, Upload } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { contractsApi } from '@/api/contracts';
import { BackLink, DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { reportApiError } from '@/lib/apiError';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { useHRLevel } from '@/hooks/useHRLevel';
import { hasAnyRole } from '@/lib/auth/roles';

const ACCOUNTANT_PERMISSION = 'contracts.accountable_funds_request.mark_paid';
const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;
const statusLabel: Record<string, string> = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает оплаты бухгалтерией', awaiting_advance_report: 'Ожидает авансовый отчёт', closed: 'Закрыта' };
const approvalLabel: Record<string, string> = { draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано', rejected: 'Отклонено', rework: 'На доработке' };

export default function AccountableFundsRequestDetail() {
  const requestId = Number(useParams<{ id: string }>().id);
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile();
  const { hasPerm } = useHRLevel();
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);
  const canMarkPaid = isAdmin || hasPerm(ACCOUNTANT_PERMISSION);
  const [budgetLineId, setBudgetLineId] = useState('');
  const [expenseName, setExpenseName] = useState('');
  const [reportAmount, setReportAmount] = useState('');
  const [reportFile, setReportFile] = useState<File | null>(null);
  const { data: request, isLoading, isError } = useQuery({ queryKey: ['contracts', 'accountable-funds-request', requestId], queryFn: () => contractsApi.getAccountableFundsRequest(requestId).then((r) => r.data), enabled: Number.isFinite(requestId) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['contracts'] });
  const markPaid = useMutation({ mutationFn: () => contractsApi.markAccountableFundsRequestPaid(requestId).then((r) => r.data), onSuccess: () => { refresh(); toast.success('Оплата отмечена бухгалтерией'); }, onError: (error) => reportApiError(error, 'Не удалось отметить оплату') });
  const canAssignBudgetLine = request != null && (isAdmin || Number(activeProfile?.id) === request.accountable_user_id);
  const canManageReports = request != null && (isAdmin || Number(activeProfile?.id) === request.accountable_user_id);
  const { data: reports = [], isLoading: reportsLoading } = useQuery({
    queryKey: ['contracts', 'accountable-funds-request', requestId, 'advance-reports'],
    queryFn: () => contractsApi.listAdvanceReports(requestId).then((r) => r.data),
    enabled: Number.isFinite(requestId),
  });
  const createReport = useMutation({
    mutationFn: () => contractsApi.createAdvanceReport(requestId, expenseName.trim(), reportAmount.replace(',', '.'), reportFile!).then((r) => r.data),
    onSuccess: () => { setExpenseName(''); setReportAmount(''); setReportFile(null); refresh(); toast.success('Авансовый отчёт добавлен'); },
    onError: (error) => reportApiError(error, 'Не удалось добавить авансовый отчёт'),
  });
  const { data: matchingLines = [] } = useQuery({
    queryKey: ['contracts', 'budget-lines', { administratorId: request?.administrator_id, programId: request?.program_id }],
    queryFn: () => contractsApi.listBudgetLines({ administrator_id: request!.administrator_id, program_id: request!.program_id }).then((r) => r.data),
    enabled: request?.budget_line_id == null && canAssignBudgetLine,
  });
  const assignBudgetLine = useMutation({
    mutationFn: () => contractsApi.assignAccountableFundsRequestBudgetLine(requestId, Number(budgetLineId)).then((r) => r.data),
    onSuccess: () => { refresh(); toast.success('Строка бюджета привязана'); },
    onError: (error) => reportApiError(error, 'Не удалось указать строку бюджета'),
  });
  if (isLoading) return <ContractsShell><BackLink to="/contracts/accountable-funds-requests">К заявкам</BackLink><DetailSkeleton /></ContractsShell>;
  if (isError || !request) return <ContractsShell><BackLink to="/contracts/accountable-funds-requests">К заявкам</BackLink><p className="text-destructive">Заявка не найдена или недоступна.</p></ContractsShell>;
  const requestApprovalLabel = approvalLabel[request.approval_state] ?? request.approval_state;
  const openReportFile = (reportId: number) => contractsApi.getAdvanceReportFileUrl(reportId).then((response) => window.open(response.data.url, '_blank', 'noopener,noreferrer'));

  return <ContractsShell><BackLink to="/contracts/accountable-funds-requests">К заявкам</BackLink><div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-center gap-2"><FileCheck2 className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Заявка на подотчётные средства</h1></div><div className="flex gap-2"><Badge variant={request.approval_state === 'approved' ? 'default' : 'secondary'}>{requestApprovalLabel}</Badge><Badge variant={request.status === 'closed' ? 'default' : 'secondary'}>{statusLabel[request.status]}</Badge></div></div>
    <Card><CardHeader><CardTitle>Заявка</CardTitle></CardHeader><CardContent><FieldGrid><Field label="Администратор">{request.administrator_name}</Field><Field label="Программа">{request.program_name}<span className="block text-xs text-muted-foreground">{request.expense_item}, {request.period_year}</span></Field><Field label="Сумма"><span className="tabular-nums">{formatAmount(request.amount)} {request.currency}</span></Field><Field label="Цель" className="sm:col-span-2 lg:col-span-3">{request.goal}</Field><Field label="Инициатор">Пользователь #{request.accountable_user_id}</Field><Field label="Создана">{formatMoment(request.created_at)}</Field></FieldGrid></CardContent></Card>
    {request.budget_line_id == null && <Card><CardHeader><CardTitle>Строка бюджета</CardTitle><CardDescription>Выберите бюджет, с которого должна быть зарезервирована эта заявка. Доступны только строки исходных администратора и программы.</CardDescription></CardHeader><CardContent className="flex flex-wrap items-center gap-3"><Select value={budgetLineId} onValueChange={setBudgetLineId} disabled={!canAssignBudgetLine}><SelectTrigger className="w-full sm:w-96"><SelectValue placeholder="Выберите год и валюту бюджета" /></SelectTrigger><SelectContent>{matchingLines.map((line) => <SelectItem key={line.id} value={String(line.id)}>{line.period_year} — {line.currency}: доступно {formatAmount(line.remaining)}</SelectItem>)}</SelectContent></Select>{canAssignBudgetLine ? <Button disabled={!budgetLineId || assignBudgetLine.isPending} onClick={() => assignBudgetLine.mutate()}>{assignBudgetLine.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Привязать</Button> : <p className="text-sm text-muted-foreground">Привязать строку может инициатор заявки или администратор.</p>}</CardContent></Card>}
    <Card><CardHeader><CardTitle>Оплата бухгалтерией</CardTitle><CardDescription>{request.accounting_paid ? 'Средства выданы инициатору. Заявка остаётся открытой до будущих авансовых отчётов.' : request.approval_state === 'approved' ? 'После согласования бухгалтер подтверждает, что средства выданы.' : 'Поле станет доступно после окончания процесса согласования.'}</CardDescription></CardHeader><CardContent>{request.accounting_paid ? <div className="flex items-center gap-3"><Switch checked disabled aria-label="Бухгалтер оплатил" /><span className="text-sm">Бухгалтер оплатил {request.accounting_paid_at && `— ${formatMoment(request.accounting_paid_at)}`}</span></div> : request.status === 'awaiting_accounting' && canMarkPaid ? <Button disabled={markPaid.isPending} onClick={() => markPaid.mutate()}>{markPaid.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Отметить: бухгалтер оплатил</Button> : <p className="text-sm text-muted-foreground">Ожидается решение по согласованию или действие бухгалтера.</p>}</CardContent></Card>
    {request.accounting_paid && <Card><CardHeader><CardTitle>Авансовые отчёты</CardTitle><CardDescription>Зачитываются только согласованные отчёты. Когда их сумма достигнет выданной суммы, заявка закроется автоматически.</CardDescription></CardHeader><CardContent className="space-y-5"><FieldGrid><Field label="Выдано"><span className="tabular-nums">{formatAmount(request.amount)} {request.currency}</span></Field><Field label="Подтверждено"><span className="tabular-nums">{formatAmount(request.advance_reported_amount)} {request.currency}</span></Field><Field label="Осталось подтвердить"><span className="tabular-nums">{formatAmount(request.remaining_accountable_amount)} {request.currency}</span></Field></FieldGrid>{reportsLoading ? <p className="text-sm text-muted-foreground">Загрузка отчётов…</p> : reports.length === 0 ? <p className="text-sm text-muted-foreground">Авансовых отчётов пока нет.</p> : <div className="space-y-3">{reports.map((report) => <div key={report.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"><div><p className="font-medium">{report.expense_name}</p><p className="text-sm text-muted-foreground tabular-nums">{formatAmount(report.amount)} {report.currency} · {approvalLabel[report.approval_state] ?? report.approval_state}</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => openReportFile(report.id)}><Download className="mr-2 h-4 w-4" />Файл</Button><SubmitForApproval subjectType="contracts.advance_report" subjectId={report.id} state={report.approval_state} submit={contractsApi.submitAdvanceReport} invalidate={[["contracts"]]} showState={false} /></div></div>)}</div>}{request.status === 'awaiting_advance_report' && canManageReports && <div className="border-t pt-5"><p className="mb-4 font-medium">Добавить авансовый отчёт</p><div className="grid max-w-2xl gap-4 sm:grid-cols-2"><div><Label htmlFor="expense-name">Наименование затрат</Label><Input id="expense-name" value={expenseName} onChange={(event) => setExpenseName(event.target.value)} /></div><div><Label htmlFor="report-amount">Сумма</Label><Input id="report-amount" inputMode="decimal" value={reportAmount} onChange={(event) => setReportAmount(event.target.value)} /></div><div className="sm:col-span-2"><Label htmlFor="report-file">Файл</Label><Input id="report-file" type="file" onChange={(event) => setReportFile(event.target.files?.[0] ?? null)} /></div><Button className="w-fit sm:col-span-2" disabled={!expenseName.trim() || !reportAmount.trim() || !reportFile || createReport.isPending} onClick={() => createReport.mutate()}>{createReport.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}Добавить отчёт</Button></div></div>}{request.status === 'awaiting_advance_report' && !canManageReports && <p className="text-sm text-muted-foreground">Добавить отчёт может только инициатор заявки или администратор.</p>}{request.status === 'closed' && <p className="rounded-md bg-muted p-3 text-sm">Все выданные средства подтверждены согласованными авансовыми отчётами. Заявка закрыта.</p>}</CardContent></Card>}
    <SubmitForApproval subjectType="contracts.accountable_funds_request" subjectId={request.id} state={request.approval_state} submit={contractsApi.submitAccountableFundsRequest} invalidate={[["contracts", "accountable-funds-requests"]]} />
    <SubjectProcesses subjectType="contracts.accountable_funds_request" subjectId={request.id} />
  </div></ContractsShell>;
}
