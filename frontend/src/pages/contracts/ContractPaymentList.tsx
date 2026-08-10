import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Wallet } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import {
  CollectionPageHeader,
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

const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтерию',
  closed: 'Закрыт',
};

export default function ContractPaymentList() {
  const [searchParams] = useSearchParams();
  const agreementId = Number(searchParams.get('agreement_id')) || undefined;
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'contract-payments', agreementId],
    queryFn: () =>
      contractsApi.listContractPayments({ agreement_id: agreementId }).then((r) => r.data),
  });

  return (
    <ContractsShell>
      <CollectionPageHeader
        icon={Wallet}
        title="Оплаты по договорам"
        description={
          agreementId
            ? 'Оплаты по выбранному договору'
            : 'Счёт, согласование и проведение'
        }
        actions={
          <Button asChild>
            <Link to="/contracts/contract-payments/new">
              <Plus className="mr-2 h-4 w-4" />
              Новая оплата
            </Link>
          </Button>
        }
      />

      <CollectionTable
        isLoading={isLoading}
        isError={isError}
        isEmpty={rows.length === 0}
        errorMessage="Не удалось загрузить оплаты."
        emptyMessage="Оплат по договорам пока нет."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Администратор</TableHead>
              <TableHead>Договор</TableHead>
              <TableHead className="text-right">Сумма</TableHead>
              <TableHead>Согласование</TableHead>
              <TableHead>Статус</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.administrator_name}</TableCell>
                <TableCell>
                  <Link
                    className="hover:underline underline-offset-2"
                    to={`/contracts/contract-payments/${row.id}`}
                  >
                    {row.agreement_number}
                  </Link>
                  <div className="text-xs text-muted-foreground">{row.agreement_name}</div>
                </TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">
                  {formatAmount(row.amount)} {row.currency}
                </TableCell>
                <TableCell>
                  <Badge>{approvalLabel[row.approval_state] ?? row.approval_state}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={row.status === 'closed' ? 'default' : 'secondary'}>
                    {statusLabel[row.status] ?? row.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <SubmitForApproval
                    subjectType="contracts.contract_payment"
                    subjectId={row.id}
                    state={row.approval_state}
                    submit={contractsApi.submitContractPayment}
                    invalidate={[['contracts', 'contract-payments']]}
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
}
