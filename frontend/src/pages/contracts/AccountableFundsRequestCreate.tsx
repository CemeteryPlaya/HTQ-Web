import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Loader2, Wallet } from 'lucide-react';
import { toast } from 'sonner';

import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { BudgetLineFlat } from '@/types/contracts';

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

export default function AccountableFundsRequestCreate() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [administratorId, setAdministratorId] = useState('');
  const [budgetLineId, setBudgetLineId] = useState('');
  const [amount, setAmount] = useState('');
  const [goal, setGoal] = useState('');
  const { data: lines = [] } = useQuery({
    queryKey: ['contracts', 'budget-lines', 'accountable-funds'],
    queryFn: () => contractsApi.listBudgetLines().then((r) => r.data),
  });
  const administrators = useMemo(() => {
    const seen = new Map<number, string>();
    lines.forEach((line) => seen.set(line.administrator_id, line.administrator_name));
    return [...seen].map(([id, label]) => ({ id, label }));
  }, [lines]);
  const programLines = useMemo(() => lines.filter((line) =>
    String(line.administrator_id) === administratorId && line.budget_status === 'active',
  ), [lines, administratorId]);
  const selectedLine = lines.find((line) => String(line.id) === budgetLineId);
  const invalidAmount = !AMOUNT_RE.test(amount.trim()) || Number(amount.replace(',', '.')) <= 0
    || (selectedLine != null && Number(amount.replace(',', '.')) > Number(selectedLine.remaining));
  const create = useMutation({
    mutationFn: () => contractsApi.createAccountableFundsRequest({
      budget_line_id: Number(budgetLineId),
      amount: amount.replace(',', '.'), goal: goal.trim(),
    }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success('Заявка на подотчётные средства создана');
      navigate('/contracts/accountable-funds-requests');
    },
    onError: (error: any) => toast.error(error?.response?.data?.detail ?? 'Не удалось создать заявку'),
  });

  return <ContractsShell><div className="max-w-2xl">
    <Link to="/contracts/accountable-funds-requests" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />К заявкам</Link>
    <div className="mb-6 flex items-center gap-3"><Wallet className="h-7 w-7 text-muted-foreground" /><div><h1 className="text-3xl font-bold">Заявка на подотчётные средства</h1><p className="text-sm text-muted-foreground">Средства будут закреплены за вами до добавления авансовых отчётов.</p></div></div>
    <form onSubmit={(event) => { event.preventDefault(); if (!administratorId || !budgetLineId || invalidAmount || !goal.trim()) { toast.error('Заполните все поля и проверьте сумму'); return; } create.mutate(); }}>
      <Card><CardHeader><CardTitle>Основание и сумма</CardTitle><CardDescription>После сохранения заявку можно отправить в Signoff. Отметка бухгалтера появится только после согласования.</CardDescription></CardHeader><CardContent className="space-y-5">
        <div><Label htmlFor="administrator">Администратор</Label><Select value={administratorId} onValueChange={(value) => { setAdministratorId(value); setBudgetLineId(''); }}><SelectTrigger id="administrator"><SelectValue placeholder="Выберите администратора" /></SelectTrigger><SelectContent>{administrators.map((administrator) => <SelectItem key={administrator.id} value={String(administrator.id)}>{administrator.label}</SelectItem>)}</SelectContent></Select></div>
        <div><Label htmlFor="program">Программа</Label><Select value={budgetLineId} onValueChange={setBudgetLineId} disabled={!administratorId}><SelectTrigger id="program"><SelectValue placeholder="Сначала выберите администратора" /></SelectTrigger><SelectContent>{programLines.map((line: BudgetLineFlat) => <SelectItem key={line.id} value={String(line.id)}>{line.program_name} — {line.period_year}, {line.currency}</SelectItem>)}</SelectContent></Select></div>
        {selectedLine && <p className="rounded-md border bg-muted/40 p-3 text-sm">Доступно по программе: <strong>{selectedLine.remaining}</strong> {selectedLine.currency}</p>}
        <div><Label htmlFor="amount">Сумма</Label><div className="flex items-center gap-2"><Input id="amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="100000.00" /><span className="text-sm text-muted-foreground">{selectedLine?.currency ?? ''}</span></div></div>
        <div><Label htmlFor="goal">Цель</Label><Textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="На что необходимы средства" /></div>
      </CardContent></Card>
      <div className="mt-6 flex gap-3"><Button disabled={create.isPending}>{create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Создать</Button><Button type="button" variant="outline" onClick={() => navigate('/contracts/accountable-funds-requests')}>Отмена</Button></div>
    </form>
  </div></ContractsShell>;
}
