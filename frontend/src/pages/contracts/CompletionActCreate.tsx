import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FileText, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatDate, formatMoment, formatMoney } from '@/components/contracts/format';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

export default function CompletionActCreate() {
  const navigate = useNavigate(); const queryClient = useQueryClient();
  const [administratorId, setAdministratorId] = useState(''); const [agreementId, setAgreementId] = useState('');
  const [amount, setAmount] = useState(''); const [act, setAct] = useState<File | null>(null);
  const { data: administrators = [] } = useQuery({ queryKey: ['contracts', 'administrators'], queryFn: () => contractsApi.listAdministrators({ is_active: true }).then(r => r.data) });
  const { data: agreements = [] } = useQuery({ queryKey: ['contracts', 'agreements'], queryFn: () => contractsApi.listAgreements().then(r => r.data) });
  const eligible = agreements.filter(a => a.approval_state === 'approved' && String(a.administrator_id) === administratorId && !['terminated', 'executed'].includes(a.status));
  const selectedFromList = eligible.find(a => String(a.id) === agreementId);
  const { data: selectedAgreement, isLoading: isLoadingAgreement } = useQuery({
    queryKey: ['contracts', 'agreement', agreementId],
    queryFn: () => contractsApi.getAgreement(Number(agreementId)).then(r => r.data),
    enabled: Boolean(agreementId),
  });
  const { data: enums } = useQuery({ queryKey: ['contracts', 'enums'], queryFn: () => contractsApi.getEnums().then(r => r.data) });
  const selected = selectedAgreement ?? selectedFromList;
  const invalidAmount = !AMOUNT_RE.test(amount.trim()) || Number(amount.replace(',', '.')) <= 0 || (selected && Number(amount.replace(',', '.')) > Number(selected.remaining_amount));
  const agreementStatusLabel = selected ? enums?.agreement_status.find(option => option.value === selected.status)?.label ?? selected.status : '';
  const paymentTypeLabel = selected ? enums?.payment_type.find(option => option.value === selected.payment_type)?.label ?? selected.payment_type : '';
  const create = useMutation({
    mutationFn: () => contractsApi.createCompletionAct(Number(administratorId), Number(agreementId), amount.replace(',', '.'), act!).then(r => r.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['contracts'] }); toast.success('Акт выполненных работ создан'); navigate('/contracts/completion-acts'); },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Не удалось создать акт'),
  });
  return <ContractsShell><div className="max-w-2xl"><Link to="/contracts/completion-acts" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />К актам</Link>
    <div className="mb-6 flex items-center gap-3"><FileText className="h-7 w-7 text-muted-foreground" /><h1 className="text-3xl font-bold">Акт выполненных работ</h1></div>
    <form onSubmit={e => { e.preventDefault(); if (!administratorId || !agreementId || !act || invalidAmount) { toast.error('Заполните все поля и проверьте сумму'); return; } create.mutate(); }}><Card><CardHeader><CardTitle>Основание и сумма</CardTitle></CardHeader><CardContent className="space-y-5">
      <div><Label>Администратор</Label><Select value={administratorId} onValueChange={v => { setAdministratorId(v); setAgreementId(''); }}><SelectTrigger><SelectValue placeholder="Выберите администратора" /></SelectTrigger><SelectContent>{administrators.map(a => <SelectItem key={a.id} value={String(a.id)}>{a.display_name}</SelectItem>)}</SelectContent></Select></div>
      <div><Label>Договор</Label><Select value={agreementId} onValueChange={setAgreementId} disabled={!administratorId}><SelectTrigger><SelectValue placeholder="Выберите договор" /></SelectTrigger><SelectContent>{eligible.map(a => <SelectItem key={a.id} value={String(a.id)}>{a.number} — {a.name}</SelectItem>)}</SelectContent></Select></div>
      {selected && <section className="rounded-lg border bg-muted/30 p-4 text-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b pb-3">
          <div><p className="font-semibold">{selected.number} — {selected.name}</p><p className="mt-0.5 text-muted-foreground">Договор</p></div>
          <p className="text-muted-foreground">{isLoadingAgreement ? 'Загрузка реквизитов…' : agreementStatusLabel}</p>
        </div>
        <div className="grid gap-x-6 gap-y-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <div><p className="text-xs text-muted-foreground">Сумма договора</p><p className="mt-1 font-medium tabular-nums">{formatMoney(selected.amount, selected.currency)}</p></div>
          <div><p className="text-xs text-muted-foreground">Предоплачено</p><p className="mt-1 tabular-nums">{formatMoney(selected.advance_paid_amount, selected.currency)}</p></div>
          <div><p className="text-xs text-muted-foreground">Оплачено по договору</p><p className="mt-1 tabular-nums">{formatMoney(selected.contract_paid_amount, selected.currency)}</p></div>
          <div><p className="text-xs text-muted-foreground">Доступно к оплате</p><p className="mt-1 font-semibold tabular-nums">{formatMoney(selected.remaining_amount, selected.currency)}</p></div>
        </div>
        <dl className="grid gap-x-6 gap-y-4 border-t pt-4 sm:grid-cols-2">
          <div><dt className="text-xs text-muted-foreground">Администратор</dt><dd className="mt-1">{selected.administrator_name}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Контрагент</dt><dd className="mt-1">{selected.counterparty_name} ({selected.counterparty_bin_iin})</dd></div>
          <div><dt className="text-xs text-muted-foreground">Бюджет / год</dt><dd className="mt-1">Бюджет {selected.period_year}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Программа</dt><dd className="mt-1">{selected.program_name}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Статья расходов</dt><dd className="mt-1">{selected.expense_item}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Тип оплаты</dt><dd className="mt-1">{paymentTypeLabel}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Дата подписания</dt><dd className="mt-1">{formatDate(selected.signed_date)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Согласование</dt><dd className="mt-1">{selected.approval_state}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Предоплата</dt><dd className="mt-1">{selected.advance_payment_id ? 'Оформлена' : 'Не оформлена'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Файл договора</dt><dd className="mt-1">{selected.file_id ? 'Приложен' : 'Не приложен'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Создан</dt><dd className="mt-1">{formatMoment(selected.created_at)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Изменён</dt><dd className="mt-1">{formatMoment(selected.updated_at)}</dd></div>
        </dl>
      </section>}
      <div><Label>Сумма</Label><Input inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} placeholder="100000.00" /></div>
      <div><Label>Акт</Label><Input type="file" onChange={e => setAct(e.target.files?.[0] ?? null)} />{act && <p className="mt-1 text-xs text-muted-foreground">{act.name}</p>}</div>
    </CardContent></Card><div className="mt-6 flex gap-3"><Button disabled={create.isPending}>{create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Создать</Button><Button type="button" variant="outline" onClick={() => navigate('/contracts/completion-acts')}>Отмена</Button></div></form>
  </div></ContractsShell>;
}
