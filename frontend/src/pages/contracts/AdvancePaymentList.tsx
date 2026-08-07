import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Paperclip, Plus, Wallet } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { contractsApi } from '@/api/contracts';

const approvalLabel: Record<string, string> = {
  draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано',
  rejected: 'Отклонено', rework: 'На доработке',
};

const AdvancePaymentList = () => {
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'advance-payments'],
    queryFn: () => contractsApi.listAdvancePayments().then((r) => r.data),
  });

  return (
    <ContractsShell>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Wallet className="h-7 w-7 text-muted-foreground" />
          <div>
            <h1 className="text-3xl font-bold">Предоплаты</h1>
            <p className="text-sm text-muted-foreground">На основании согласованных договоров</p>
          </div>
        </div>
        <Button asChild>
          <Link to="/contracts/advance-payments/new"><Plus className="mr-2 h-4 w-4" />Новая предоплата</Link>
        </Button>
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        {isLoading ? <div className="space-y-3 p-6">{[1, 2, 3].map((n) => <Skeleton key={n} className="h-10 w-full" />)}</div>
          : isError ? <p className="p-6 text-sm text-destructive">Не удалось загрузить предоплаты.</p>
          : rows.length === 0 ? <div className="p-10 text-center text-muted-foreground">Предоплат пока нет.</div>
          : <Table>
            <TableHeader><TableRow><TableHead>Договор</TableHead><TableHead>Контрагент</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Согласование</TableHead><TableHead>Проведение</TableHead><TableHead className="text-right">Действие</TableHead></TableRow></TableHeader>
            <TableBody>{rows.map((row) => <TableRow key={row.id}>
              <TableCell className="font-medium"><Link className="hover:underline" to={`/contracts/advance-payments/${row.id}`}>{row.agreement_number}</Link><div className="text-xs text-muted-foreground">{row.agreement_name}</div></TableCell>
              <TableCell>{row.counterparty_name}</TableCell>
              <TableCell className="text-right tabular-nums">{formatAmount(row.amount)} {row.currency}</TableCell>
              <TableCell><Badge variant={row.approval_state === 'approved' ? 'default' : 'secondary'}>{approvalLabel[row.approval_state] ?? row.approval_state}</Badge></TableCell>
              <TableCell>{row.payment_order_file_id ? <span className="inline-flex items-center gap-1 text-sm"><Paperclip className="h-3.5 w-3.5" />{row.posting_number}</span> : <span className="text-sm text-muted-foreground">{row.approval_state === 'approved' ? 'Ожидает бухгалтера' : '—'}</span>}</TableCell>
              <TableCell className="text-right"><SubmitForApproval subjectType="contracts.advance_payment" subjectId={row.id} state={row.approval_state} submit={contractsApi.submitAdvancePayment} invalidate={[["contracts", "advance-payments"]]} /></TableCell>
            </TableRow>)}</TableBody>
          </Table>}
      </div>
    </ContractsShell>
  );
};

export default AdvancePaymentList;
