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
import { Button } from '@/components/ui/button'; import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'; import { Input } from '@/components/ui/input'; import { Label } from '@/components/ui/label';
import { useActiveProfile } from '@/hooks/useActiveProfile'; import { useHRLevel } from '@/hooks/useHRLevel'; import { hasAnyRole } from '@/lib/auth/roles';

const PERMISSION = 'contracts.contract_payment.record_payment';
export default function ContractPaymentDetail() {
  const { id } = useParams<{ id: string }>(); const paymentId = Number(id); const queryClient = useQueryClient(); const [postingNumber, setPostingNumber] = useState(''); const [file, setFile] = useState<File | null>(null); const fileInput = useRef<HTMLInputElement>(null);
  const { activeProfile } = useActiveProfile(); const { hasPerm } = useHRLevel(); const canRecord = hasAnyRole(activeProfile?.roles ?? [], ['admin', 'superuser', 'staff']) || hasPerm(PERMISSION);
  const { data: payment, isLoading, isError } = useQuery({ queryKey: ['contracts', 'contract-payment', paymentId], queryFn: () => contractsApi.getContractPayment(paymentId).then(r => r.data), enabled: Number.isFinite(paymentId) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['contracts'] });
  const record = useMutation({ mutationFn: () => contractsApi.recordContractPayment(paymentId, postingNumber.trim(), file!).then(r => r.data), onSuccess: () => { refresh(); toast.success('Платёж проведён'); }, onError: e => reportApiError(e, 'Не удалось оформить платёж') });
  const open = (which: 'invoice' | 'order') => (which === 'invoice' ? contractsApi.getContractPaymentInvoiceUrl(paymentId) : contractsApi.getContractPaymentOrderUrl(paymentId)).then(r => window.open(r.data.url, '_blank', 'noopener,noreferrer'));
  if (isLoading) return <ContractsShell><BackLink to="/contracts/contract-payments">К оплатам</BackLink><DetailSkeleton /></ContractsShell>;
  if (isError || !payment) return <ContractsShell><BackLink to="/contracts/contract-payments">К оплатам</BackLink><p className="text-destructive">Оплата не найдена или недоступна.</p></ContractsShell>;
  const closed = payment.status === 'closed';
  return <ContractsShell><BackLink to="/contracts/contract-payments">К оплатам</BackLink><div className="space-y-6"><div className="flex items-center gap-2"><FileCheck2 className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Оплата по договору</h1></div>
    <Card><CardHeader><CardTitle>Основание</CardTitle></CardHeader><CardContent><FieldGrid><Field label="Администратор">{payment.administrator_name}</Field><Field label="Договор"><Link className="hover:underline" to={`/contracts/agreements/${payment.agreement_id}`}>{payment.agreement_number} — {payment.agreement_name}</Link></Field><Field label="Контрагент">{payment.counterparty_name}</Field><Field label="Сумма">{formatAmount(payment.amount)} {payment.currency}</Field><Field label="Создана">{formatMoment(payment.created_at)}</Field></FieldGrid><Button className="mt-5" variant="outline" onClick={() => open('invoice')}><Download className="mr-2 h-4 w-4" />Открыть счёт</Button></CardContent></Card>
    <Card><CardHeader><CardTitle>Оформление бухгалтерией</CardTitle><CardDescription>{closed ? 'Платёж проведён.' : payment.status === 'awaiting_accounting' ? 'Укажите проводку и приложите платёжное поручение.' : 'Станет доступно после согласования.'}</CardDescription></CardHeader><CardContent>{closed ? <div className="flex gap-3"><span className="text-sm">Проводка: <strong>{payment.posting_number}</strong></span><Button variant="outline" onClick={() => open('order')}><Download className="mr-2 h-4 w-4" />Платёжное поручение</Button></div> : payment.status === 'awaiting_accounting' && canRecord ? <div className="grid max-w-xl gap-4"><div><Label>Номер проводки</Label><Input value={postingNumber} onChange={e => setPostingNumber(e.target.value)} /></div><div><Label>Платёжное поручение</Label><Input ref={fileInput} type="file" onChange={e => setFile(e.target.files?.[0] ?? null)} /></div><Button className="w-fit" disabled={!file || !postingNumber.trim() || record.isPending} onClick={() => record.mutate()}>{record.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}Оформить платёж</Button></div> : <p className="text-sm text-muted-foreground">Ожидается решение по согласованию или оформление бухгалтерией.</p>}</CardContent></Card>
    <SubmitForApproval subjectType="contracts.contract_payment" subjectId={payment.id} state={payment.approval_state} submit={contractsApi.submitContractPayment} invalidate={[["contracts", "contract-payments"]]} /><SubjectProcesses subjectType="contracts.contract_payment" subjectId={payment.id} />
  </div></ContractsShell>;
}
