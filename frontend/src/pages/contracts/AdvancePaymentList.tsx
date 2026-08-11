import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Paperclip, Plus, Wallet } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import {
  CollectionPageHeader,
  CollectionSearch,
  CollectionTable,
} from '@/components/contracts/CollectionPage';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const approvalLabel: Record<string, string> = {
  draft: 'Черновик',
  pending: 'На согласовании',
  approved: 'Согласовано',
  rejected: 'Отклонено',
  rework: 'На доработке',
};

const documentStatusLabel: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтера',
  closed: 'Закрыт',
};

const AdvancePaymentList = () => {
  const [search, setSearch] = useState('');
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'advance-payments'],
    queryFn: () => contractsApi.listAdvancePayments().then((r) => r.data),
  });
  const normalizedSearch = search.trim().toLowerCase();
  const filteredRows = normalizedSearch
    ? rows.filter((row) => [
        row.agreement_number, row.agreement_name, row.counterparty_name,
        approvalLabel[row.approval_state] ?? row.approval_state,
        documentStatusLabel[row.status] ?? row.status, row.posting_number,
      ].join(' ').toLowerCase().includes(normalizedSearch))
    : rows;

  return (
    <ContractsShell>
      <CollectionPageHeader
        icon={Wallet}
        title="Предоплаты"
        description="На основании согласованных договоров"
        actions={
          <Button asChild>
            <Link to="/contracts/advance-payments/new">
              <Plus className="mr-2 h-4 w-4" />
              Новая предоплата
            </Link>
          </Button>
        }
      >
        <CollectionSearch
          value={search}
          onValueChange={setSearch}
          placeholder="Договор, контрагент, проведение или статус"
        />
      </CollectionPageHeader>

      <CollectionTable
        isLoading={isLoading}
        isError={isError}
        isEmpty={filteredRows.length === 0}
        errorMessage="Не удалось загрузить предоплаты."
        emptyMessage={normalizedSearch ? 'По запросу ничего не найдено.' : 'Предоплат пока нет.'}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Договор</TableHead>
              <TableHead>Контрагент</TableHead>
              <TableHead className="text-right">Сумма</TableHead>
              <TableHead>Статус согласования</TableHead>
              <TableHead>Статус оплаты</TableHead>
              <TableHead>Реквизиты проведения</TableHead>
              <TableHead className="text-right">Действие</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredRows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">
                  <Link
                    className="hover:underline underline-offset-2"
                    to={`/contracts/advance-payments/${row.id}`}
                  >
                    {row.agreement_number}
                  </Link>
                  <div className="text-xs text-muted-foreground">{row.agreement_name}</div>
                </TableCell>
                <TableCell>{row.counterparty_name}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">
                  {formatAmount(row.amount)} {row.currency}
                </TableCell>
                <TableCell>
                  <Badge variant={row.approval_state === 'approved' ? 'default' : 'secondary'}>
                    {approvalLabel[row.approval_state] ?? row.approval_state}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={row.status === 'closed' ? 'default' : 'secondary'}>
                    {documentStatusLabel[row.status] ?? row.status}
                  </Badge>
                </TableCell>
                <TableCell>
                  {row.payment_order_file_id ? (
                    <span className="inline-flex items-center gap-1 text-sm">
                      <Paperclip className="h-3.5 w-3.5" />
                      {row.posting_number}
                    </span>
                  ) : (
                    <span className="text-sm text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <SubmitForApproval
                    subjectType="contracts.advance_payment"
                    subjectId={row.id}
                    state={row.approval_state}
                    submit={contractsApi.submitAdvancePayment}
                    invalidate={[['contracts', 'advance-payments']]}
                    showState={false}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CollectionTable>
    </ContractsShell>
  );
};

export default AdvancePaymentList;
