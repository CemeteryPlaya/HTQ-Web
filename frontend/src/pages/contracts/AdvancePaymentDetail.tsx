import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FileCheck2, Loader2, Paperclip, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { BackLink, DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { reportApiError } from '@/components/signoff/apiError';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { contractsApi } from '@/api/contracts';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { useHRLevel } from '@/hooks/useHRLevel';
import { hasAnyRole } from '@/lib/auth/roles';

const ACCOUNTANT_PERMISSION = 'contracts.advance_payment.record_payment';
const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

const AdvancePaymentDetail = () => {
  const { id } = useParams<{ id: string }>();
  const paymentId = Number(id);
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile();
  const { hasPerm } = useHRLevel();
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);
  const canRecord = isAdmin || hasPerm(ACCOUNTANT_PERMISSION);
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [postingNumber, setPostingNumber] = useState('');

  const { data: payment, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'advance-payment', paymentId],
    queryFn: () => contractsApi.getAdvancePayment(paymentId).then((r) => r.data),
    enabled: Number.isFinite(paymentId),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['contracts'] });
  const record = useMutation({
    mutationFn: () => contractsApi.recordAdvancePayment(paymentId, postingNumber.trim(), file!).then((r) => r.data),
    onSuccess: () => { refresh(); toast.success('Платёжное поручение и номер проводки сохранены'); },
    onError: (error) => reportApiError(error, 'Не удалось оформить платёж'),
  });
  const download = useMutation({
    mutationFn: () => contractsApi.getAdvancePaymentOrderUrl(paymentId).then((r) => r.data.url),
    onSuccess: (url) => window.open(url, '_blank', 'noopener,noreferrer'),
    onError: (error) => reportApiError(error, 'Не удалось открыть платёжное поручение'),
  });

  if (isLoading) return <ContractsShell><BackLink to="/contracts/advance-payments">К предоплатам</BackLink><DetailSkeleton /></ContractsShell>;
  if (isError || !payment) return <ContractsShell><BackLink to="/contracts/advance-payments">К предоплатам</BackLink><p className="text-destructive">Предоплата не найдена или недоступна.</p></ContractsShell>;
  const completed = Boolean(payment.payment_order_file_id && payment.posting_number);

  return <ContractsShell><BackLink to="/contracts/advance-payments">К предоплатам</BackLink><div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><FileCheck2 className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Предоплата</h1></div><p className="mt-1 text-sm text-muted-foreground">На основании договора {payment.agreement_number}</p></div><Badge variant={payment.approval_state === 'approved' ? 'default' : 'secondary'}>{payment.approval_state === 'approved' ? 'Согласовано' : payment.approval_state === 'pending' ? 'На согласовании' : payment.approval_state === 'draft' ? 'Черновик' : payment.approval_state}</Badge></div>
    <Card><CardHeader><CardTitle>Основание</CardTitle></CardHeader><CardContent><FieldGrid><Field label="Договор"><Link className="hover:underline" to={`/contracts/agreements/${payment.agreement_id}`}>{payment.agreement_number} — {payment.agreement_name}</Link></Field><Field label="Контрагент">{payment.counterparty_name}</Field><Field label="Сумма"><span className="tabular-nums">{formatAmount(payment.amount)} {payment.currency}</span></Field><Field label="Создана">{formatMoment(payment.created_at)}</Field></FieldGrid></CardContent></Card>
    <Card><CardHeader><CardTitle>Оформление бухгалтерией</CardTitle><CardDescription>{completed ? 'Предоплата проведена.' : payment.approval_state === 'approved' ? 'После согласования бухгалтер прикладывает платёжное поручение и указывает номер проводки.' : 'Станет доступно после согласования предоплаты.'}</CardDescription></CardHeader><CardContent>
      {completed ? <div className="flex flex-wrap items-center gap-4"><span className="inline-flex items-center gap-1.5 text-sm"><Paperclip className="h-4 w-4" />Платёжное поручение приложено</span><span className="text-sm">Проводка: <strong>{payment.posting_number}</strong></span><Button variant="outline" disabled={download.isPending} onClick={() => download.mutate()}>{download.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}Открыть файл</Button></div>
        : payment.approval_state !== 'approved' ? <p className="text-sm text-muted-foreground">Ожидается решение по согласованию.</p>
          : canRecord ? <div className="grid gap-4 sm:max-w-xl"><div><Label htmlFor="posting-number">Номер проводки</Label><Input id="posting-number" value={postingNumber} onChange={(event) => setPostingNumber(event.target.value)} /></div><div><Label htmlFor="payment-order">Файл платёжного поручения</Label><Input ref={fileInput} id="payment-order" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />{file && <p className="mt-1 text-xs text-muted-foreground">{file.name}</p>}</div><Button className="w-fit" disabled={!file || !postingNumber.trim() || record.isPending} onClick={() => record.mutate()}>{record.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}Оформить платёж</Button></div>
            : <p className="text-sm text-muted-foreground">Ожидает оформления бухгалтерией.</p>}
    </CardContent></Card>
    <SubmitForApproval subjectType="contracts.advance_payment" subjectId={payment.id} state={payment.approval_state} submit={contractsApi.submitAdvancePayment} invalidate={[["contracts", "advance-payments"]]} />
    <SubjectProcesses subjectType="contracts.advance_payment" subjectId={payment.id} />
  </div></ContractsShell>;
};

export default AdvancePaymentDetail;
