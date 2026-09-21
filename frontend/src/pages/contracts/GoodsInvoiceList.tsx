import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Package, Plus } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { CollectionPageHeader, CollectionPagination, CollectionSearch, CollectionTable } from '@/components/contracts/CollectionPage';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const approvalLabel: Record<string, string> = {
  draft: 'Черновик', pending: 'На согласовании', approved: 'Согласовано',
  rejected: 'Отклонено', rework: 'На доработке',
};
const statusLabel: Record<string, string> = {
  draft: 'Черновик', on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтерию', closed: 'Закрыт',
};

export default function GoodsInvoiceList() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [searchParams] = useSearchParams();
  const agreementId = Number(searchParams.get('agreement_id')) || undefined;
  const { data, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'goods-invoices', { agreementId, page, search }],
    queryFn: () => contractsApi.listGoodsInvoicesPage({
      agreement_id: agreementId, page, page_size: 25, search: search.trim() || undefined,
    }).then((r) => r.data),
  });
  const rows = data?.items ?? [];
  const pagination = data?.pagination;
  const hasSearch = search.trim().length > 0;

  return (
    <ContractsShell>
      <CollectionPageHeader
        icon={Package}
        title="Товарные накладные"
        description={agreementId ? 'Накладные по выбранному договору' : 'Накладная, согласование и проведение'}
        actions={<Button asChild><Link to="/contracts/goods-invoices/new"><Plus className="mr-2 h-4 w-4" />Новая накладная</Link></Button>}
      >
        <CollectionSearch value={search} onValueChange={(value) => { setSearch(value); setPage(1); }} placeholder="Администратор, договор или статус" />
      </CollectionPageHeader>
      <CollectionTable isLoading={isLoading} isError={isError} isEmpty={rows.length === 0}
        errorMessage="Не удалось загрузить накладные." emptyMessage={hasSearch ? 'По запросу ничего не найдено.' : 'Товарных накладных пока нет.'}>
        <Table>
          <TableHeader><TableRow><TableHead>Администратор</TableHead><TableHead>Договор</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Статус согласования</TableHead><TableHead>Статус оплаты</TableHead><TableHead className="text-right">Действия</TableHead></TableRow></TableHeader>
          <TableBody>{rows.map((row) => <TableRow key={row.id}>
            <TableCell>{row.administrator_name}</TableCell>
            <TableCell><Link className="hover:underline underline-offset-2" to={`/contracts/goods-invoices/${row.id}`}>{row.agreement_number}</Link><div className="text-xs text-muted-foreground">{row.agreement_name}</div></TableCell>
            <TableCell className="text-right tabular-nums whitespace-nowrap">{formatAmount(row.amount)} {row.currency}</TableCell>
            <TableCell><Badge>{approvalLabel[row.approval_state] ?? row.approval_state}</Badge></TableCell>
            <TableCell><Badge variant={row.status === 'closed' ? 'default' : 'secondary'}>{statusLabel[row.status] ?? row.status}</Badge></TableCell>
            <TableCell className="text-right"><SubmitForApproval subjectType="contracts.goods_invoice" subjectId={row.id} state={row.approval_state} submit={contractsApi.submitGoodsInvoice} invalidate={[['contracts', 'goods-invoices']]} showState={false} /></TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </CollectionTable>
      <CollectionPagination pagination={pagination} onPageChange={setPage} isLoading={isLoading} />
    </ContractsShell>
  );
}
