import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

export default function ContractPaymentCreate() {
  const navigate = useNavigate(); const queryClient = useQueryClient();
  const [administratorId, setAdministratorId] = useState(''); const [agreementId, setAgreementId] = useState('');
  const [amount, setAmount] = useState(''); const [invoice, setInvoice] = useState<File | null>(null);
  const { data: administrators = [] } = useQuery({ queryKey: ['contracts', 'administrators'], queryFn: () => contractsApi.listAdministrators({ is_active: true }).then(r => r.data) });
  const { data: agreements = [] } = useQuery({ queryKey: ['contracts', 'agreements'], queryFn: () => contractsApi.listAgreements().then(r => r.data) });
  const eligible = agreements.filter(a => a.approval_state === 'approved' && String(a.administrator_id) === administratorId && !['terminated', 'executed'].includes(a.status));
  const selected = eligible.find(a => String(a.id) === agreementId);
  const invalidAmount = !AMOUNT_RE.test(amount.trim()) || Number(amount.replace(',', '.')) <= 0 || (selected && Number(amount.replace(',', '.')) > Number(selected.remaining_amount));
  const create = useMutation({
    mutationFn: () => contractsApi.createContractPayment(Number(administratorId), Number(agreementId), amount.replace(',', '.'), invoice!).then(r => r.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['contracts'] }); toast.success('Оплата по договору создана'); navigate('/contracts/contract-payments'); },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Не удалось создать оплату'),
  });
  return <ContractsShell><div className="max-w-2xl"><Link to="/contracts/contract-payments" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />К оплатам</Link>
    <div className="mb-6 flex items-center gap-3"><Wallet className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Оплата по договору</h1></div>
    <form onSubmit={e => { e.preventDefault(); if (!administratorId || !agreementId || !invoice || invalidAmount) { toast.error('Заполните все поля и проверьте сумму'); return; } create.mutate(); }}><Card><CardHeader><CardTitle>Основание и сумма</CardTitle></CardHeader><CardContent className="space-y-5">
      <div><Label>Администратор</Label><Select value={administratorId} onValueChange={v => { setAdministratorId(v); setAgreementId(''); }}><SelectTrigger><SelectValue placeholder="Выберите администратора" /></SelectTrigger><SelectContent>{administrators.map(a => <SelectItem key={a.id} value={String(a.id)}>{a.display_name}</SelectItem>)}</SelectContent></Select></div>
      <div><Label>Договор</Label><Select value={agreementId} onValueChange={setAgreementId} disabled={!administratorId}><SelectTrigger><SelectValue placeholder="Выберите договор" /></SelectTrigger><SelectContent>{eligible.map(a => <SelectItem key={a.id} value={String(a.id)}>{a.number} — {a.name}</SelectItem>)}</SelectContent></Select></div>
      {selected && <p className="rounded-md border bg-muted/40 p-3 text-sm">Доступно к оплате: <strong>{formatAmount(selected.remaining_amount)} {selected.currency}</strong></p>}
      <div><Label>Сумма</Label><Input inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} placeholder="100000.00" /></div>
      <div><Label>Счёт</Label><Input type="file" onChange={e => setInvoice(e.target.files?.[0] ?? null)} />{invoice && <p className="mt-1 text-xs text-muted-foreground">{invoice.name}</p>}</div>
    </CardContent></Card><div className="mt-6 flex gap-3"><Button disabled={create.isPending}>{create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Создать</Button><Button type="button" variant="outline" onClick={() => navigate('/contracts/contract-payments')}>Отмена</Button></div></form>
  </div></ContractsShell>;
}
