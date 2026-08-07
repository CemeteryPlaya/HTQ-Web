import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Wallet } from 'lucide-react';
import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const approvalLabel: Record<string, string> = {
  draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано',
  rejected: 'Отклонено', rework: 'На доработке',
};
const statusLabel: Record<string, string> = {
  draft: 'Черновик', on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтерию', closed: 'Закрыт',
};

export default function ContractPaymentList() {
  const [searchParams] = useSearchParams();
  const agreementId = Number(searchParams.get('agreement_id')) || undefined;
  const { data: rows = [], isLoading, isError } = useQuery({ queryKey: ['contracts', 'contract-payments', agreementId], queryFn: () => contractsApi.listContractPayments({ agreement_id: agreementId }).then(r => r.data) });
  return <ContractsShell><div className="mb-6 flex items-center justify-between gap-4"><div className="flex items-center gap-3"><Wallet className="h-7 w-7 text-muted-foreground" /><div><h1 className="text-3xl font-bold">Оплаты по договорам</h1><p className="text-sm text-muted-foreground">Счёт, согласование и проведение</p></div></div><Button asChild><Link to="/contracts/contract-payments/new"><Plus className="mr-2 h-4 w-4" />Новая оплата</Link></Button></div>
    <div className="overflow-x-auto rounded-lg border bg-card">{isLoading ? <p className="p-6">Загрузка…</p> : isError ? <p className="p-6 text-destructive">Не удалось загрузить оплаты.</p> : rows.length === 0 ? <div className="p-10 text-center text-muted-foreground">Оплат по договорам пока нет.</div> : <Table><TableHeader><TableRow><TableHead>Администратор</TableHead><TableHead>Договор</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Согласование</TableHead><TableHead>Статус</TableHead><TableHead /></TableRow></TableHeader><TableBody>{rows.map(row => <TableRow key={row.id}><TableCell>{row.administrator_name}</TableCell><TableCell><Link className="hover:underline" to={`/contracts/contract-payments/${row.id}`}>{row.agreement_number}<div className="text-xs text-muted-foreground">{row.agreement_name}</div></Link></TableCell><TableCell className="text-right">{formatAmount(row.amount)} {row.currency}</TableCell><TableCell><Badge>{approvalLabel[row.approval_state] ?? row.approval_state}</Badge></TableCell><TableCell><Badge variant={row.status === 'closed' ? 'default' : 'secondary'}>{statusLabel[row.status] ?? row.status}</Badge></TableCell><TableCell><SubmitForApproval subjectType="contracts.contract_payment" subjectId={row.id} state={row.approval_state} submit={contractsApi.submitContractPayment} invalidate={[["contracts", "contract-payments"]]} showState={false} /></TableCell></TableRow>)}</TableBody></Table>}</div>
  </ContractsShell>;
}
