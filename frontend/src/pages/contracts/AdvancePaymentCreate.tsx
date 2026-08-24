import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Wallet } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { contractsApi } from '@/api/contracts';

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

const AdvancePaymentCreate = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [agreementId, setAgreementId] = useState('');
  const [amount, setAmount] = useState('');
  const { data: agreements = [], isLoading } = useQuery({
    queryKey: ['contracts', 'agreements', 'approved'],
    queryFn: () => contractsApi.listAgreements().then((r) => r.data),
  });
  const approved = agreements.filter((agreement) => agreement.approval_state === 'approved');
  const selected = approved.find((agreement) => String(agreement.id) === agreementId);
  const invalidAmount = !amount.trim() || !AMOUNT_RE.test(amount.trim()) || Number(amount.replace(',', '.')) <= 0;

  const create = useMutation({
    mutationFn: () => contractsApi.createAdvancePayment({ agreement_id: Number(agreementId), amount: amount.replace(',', '.') }).then((r) => r.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['contracts'] }); toast.success('Предоплата создана'); navigate('/contracts/advance-payments'); },
    onError: (error: any) => toast.error(error?.response?.data?.detail ?? 'Не удалось создать предоплату'),
  });

  return <ContractsShell><div className="max-w-2xl">
    <Link to="/contracts/advance-payments" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />К предоплатам</Link>
    <div className="mb-6 flex items-center gap-3"><Wallet className="h-7 w-7 text-muted-foreground" /><div><h1 className="text-3xl font-bold">Новая предоплата</h1><p className="text-sm text-muted-foreground">Создаётся только по договору, согласованному в Signoff.</p></div></div>
    <form onSubmit={(event) => { event.preventDefault(); if (!agreementId || invalidAmount) { toast.error('Заполните договор и сумму'); return; } create.mutate(); }}>
      <Card><CardHeader><CardTitle>Основание и сумма</CardTitle><CardDescription>После сохранения документ можно отправить на отдельное согласование.</CardDescription></CardHeader><CardContent className="space-y-5">
        <div><Label htmlFor="agreement">Согласованный договор</Label><Select value={agreementId} onValueChange={setAgreementId} disabled={isLoading || approved.length === 0}><SelectTrigger id="agreement"><SelectValue placeholder={isLoading ? 'Загрузка…' : 'Выберите договор'} /></SelectTrigger><SelectContent>{approved.map((agreement) => <SelectItem key={agreement.id} value={String(agreement.id)}>{agreement.number} — {agreement.name}</SelectItem>)}</SelectContent></Select></div>
        {selected && <div className="rounded-md border bg-muted/40 p-4 text-sm"><div className="flex justify-between gap-4"><span className="text-muted-foreground">Контрагент</span><span>{selected.counterparty_name}</span></div><div className="mt-2 flex justify-between gap-4"><span className="text-muted-foreground">Сумма договора</span><span className="tabular-nums">{formatAmount(selected.amount)} {selected.currency}</span></div></div>}
        <div><Label htmlFor="amount">Сумма предоплаты</Label><div className="mt-1 flex items-center gap-2"><Input id="amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="400000.00" /><span className="text-sm text-muted-foreground">{selected?.currency ?? ''}</span></div></div>
      </CardContent></Card>
      <div className="mt-6 flex gap-3"><Button type="submit" disabled={create.isPending || !agreementId || invalidAmount}>{create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Создать</Button><Button type="button" variant="outline" onClick={() => navigate('/contracts/advance-payments')}>Отмена</Button></div>
    </form>
  </div></ContractsShell>;
};

export default AdvancePaymentCreate;
