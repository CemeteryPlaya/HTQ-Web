import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FileCheck2, Loader2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { BackLink, DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { reportApiError } from '@/lib/apiError';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { usePermissions } from '@/hooks/usePermissions';
import { useHRLevel } from '@/hooks/useHRLevel';

const PERMISSION = 'contracts.contract_payment.record_payment';

export default function CompletionActDetail() {
  const { id } = useParams<{ id: string }>(); const actId = Number(id); const queryClient = useQueryClient();
  const [postingNumber, setPostingNumber] = useState(''); const [file, setFile] = useState<File | null>(null); const fileInput = useRef<HTMLInputElement>(null);
  const permissions = usePermissions(); const { hasPerm } = useHRLevel();
  const canRecord = permissions.atLeast('contracts', 'admin') || hasPerm(PERMISSION);
  const { data: act, isLoading, isError } = useQuery({ queryKey: ['contracts', 'completion-act', actId], queryFn: () => contractsApi.getCompletionAct(actId).then(r => r.data), enabled: Number.isFinite(actId) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['contracts'] });
  const record = useMutation({ mutationFn: () => contractsApi.recordCompletionAct(actId, postingNumber.trim(), file!).then(r => r.data), onSuccess: () => { refresh(); toast.success('Платёж проведён'); }, onError: e => reportApiError(e, 'Не удалось оформить платёж') });
  const open = (which: 'act' | 'order') => (which === 'act' ? contractsApi.getCompletionActUrl(actId) : contractsApi.getCompletionActOrderUrl(actId)).then(r => window.open(r.data.url, '_blank', 'noopener,noreferrer'));
  if (isLoading) return <ContractsShell><BackLink to="/contracts/completion-acts">К актам</BackLink><DetailSkeleton /></ContractsShell>;
  if (isError || !act) return <ContractsShell><BackLink to="/contracts/completion-acts">К актам</BackLink><p className="text-destructive">Акт не найден или недоступен.</p></ContractsShell>;
  const closed = act.status === 'closed';
  return <ContractsShell><BackLink to="/contracts/completion-acts">К актам</BackLink><div className="space-y-6"><div className="flex items-center gap-2"><FileCheck2 className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Акт выполненных работ</h1></div>
    <Card><CardHeader><CardTitle>Основание</CardTitle></CardHeader><CardContent><FieldGrid><Field label="Администратор">{act.administrator_name}</Field><Field label="Договор"><Link className="hover:underline" to={`/contracts/agreements/${act.agreement_id}`}>{act.agreement_number} — {act.agreement_name}</Link></Field><Field label="Контрагент">{act.counterparty_name}</Field><Field label="Сумма">{formatAmount(act.amount)} {act.currency}</Field><Field label="Создан">{formatMoment(act.created_at)}</Field></FieldGrid><Button className="mt-5" variant="outline" onClick={() => open('act')}><Download className="mr-2 h-4 w-4" />Открыть акт</Button></CardContent></Card>
    <Card><CardHeader><CardTitle>Оформление бухгалтерией</CardTitle><CardDescription>{closed ? 'Платёж проведён.' : act.status === 'awaiting_accounting' ? 'Укажите проводку и приложите платёжное поручение.' : 'Станет доступно после согласования.'}</CardDescription></CardHeader><CardContent>{closed ? <div className="flex gap-3"><span className="text-sm">Проводка: <strong>{act.posting_number}</strong></span><Button variant="outline" onClick={() => open('order')}><Download className="mr-2 h-4 w-4" />Платёжное поручение</Button></div> : act.status === 'awaiting_accounting' && canRecord ? <div className="grid max-w-xl gap-4"><div><Label>Номер проводки</Label><Input value={postingNumber} onChange={e => setPostingNumber(e.target.value)} /></div><div><Label>Платёжное поручение</Label><Input ref={fileInput} type="file" onChange={e => setFile(e.target.files?.[0] ?? null)} /></div><Button className="w-fit" disabled={!file || !postingNumber.trim() || record.isPending} onClick={() => record.mutate()}>{record.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}Оформить платёж</Button></div> : <p className="text-sm text-muted-foreground">Ожидается решение по согласованию или оформление бухгалтерией.</p>}</CardContent></Card>
    <SubmitForApproval subjectType="contracts.completion_act" subjectId={act.id} state={act.approval_state} submit={contractsApi.submitCompletionAct} invalidate={[["contracts", "completion-acts"]]} /><SubjectProcesses subjectType="contracts.completion_act" subjectId={act.id} />
  </div></ContractsShell>;
}
