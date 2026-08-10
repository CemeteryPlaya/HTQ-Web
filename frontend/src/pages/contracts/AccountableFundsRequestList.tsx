import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Wallet } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { CollectionPageHeader, CollectionTable } from '@/components/contracts/CollectionPage';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const approvalLabel: Record<string, string> = { draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано', rejected: 'Отклонено', rework: 'На доработке' };
const statusLabel: Record<string, string> = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает оплаты бухгалтерией', awaiting_advance_report: 'Ожидает авансовый отчёт' };

export default function AccountableFundsRequestList() {
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'accountable-funds-requests'],
    queryFn: () => contractsApi.listAccountableFundsRequests().then((r) => r.data),
  });
  return <ContractsShell>
    <CollectionPageHeader icon={Wallet} title="Подотчётные средства" description="Заявки, которые остаются за инициатором до авансового отчёта" actions={<Button asChild><Link to="/contracts/accountable-funds-requests/new"><Plus className="mr-2 h-4 w-4" />Новая заявка</Link></Button>} />
    <CollectionTable isLoading={isLoading} isError={isError} isEmpty={rows.length === 0} errorMessage="Не удалось загрузить заявки." emptyMessage="Заявок на подотчётные средства пока нет.">
      <Table><TableHeader><TableRow><TableHead>Администратор</TableHead><TableHead>Программа</TableHead><TableHead>Цель</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Согласование</TableHead><TableHead>Статус</TableHead><TableHead /></TableRow></TableHeader><TableBody>
        {rows.map((row) => <TableRow key={row.id}><TableCell>{row.administrator_name}</TableCell><TableCell><Link className="hover:underline underline-offset-2" to={`/contracts/accountable-funds-requests/${row.id}`}>{row.program_name}</Link><div className="text-xs text-muted-foreground">{row.expense_item}, {row.period_year}</div></TableCell><TableCell className="max-w-64 truncate">{row.goal}</TableCell><TableCell className="text-right tabular-nums">{formatAmount(row.amount)} {row.currency}</TableCell><TableCell><Badge variant={row.approval_state === 'approved' ? 'default' : 'secondary'}>{approvalLabel[row.approval_state] ?? row.approval_state}</Badge></TableCell><TableCell><Badge variant={row.accounting_paid ? 'default' : 'secondary'}>{statusLabel[row.status] ?? row.status}</Badge></TableCell><TableCell className="text-right"><SubmitForApproval subjectType="contracts.accountable_funds_request" subjectId={row.id} state={row.approval_state} submit={contractsApi.submitAccountableFundsRequest} invalidate={[["contracts", "accountable-funds-requests"]]} showState={false} /></TableCell></TableRow>)}
      </TableBody></Table>
    </CollectionTable>
  </ContractsShell>;
}
