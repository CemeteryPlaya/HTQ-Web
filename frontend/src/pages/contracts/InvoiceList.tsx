import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Paperclip, Plus, Receipt } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { formatAmount } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { contractsApi } from '@/api/contracts';
import type { InvoiceStatus } from '@/types/contracts';

/**
 * Список счетов на оплату (без договора).
 *
 * Как список договоров, но без колонок «Номер», «Оплата» и «Согласование»:
 * у счёта нет номера, нет типа оплаты, а отправка на согласование первой
 * фазой не подключена. Администратор и программа разворачиваются бэкендом из
 * бюджетной строки — разойтись с бюджетом они не могут.
 */

const STATUS_VARIANTS: Record<
  InvoiceStatus,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  draft: 'outline',
  on_review: 'secondary',
  approved: 'secondary',
  paid: 'default',
  cancelled: 'destructive',
};

const InvoiceList = () => {
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'invoices'],
    queryFn: () => contractsApi.listInvoices().then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Подписи статусов — с бэкенда, чтобы при добавлении статуса список не
  // показывал сырой код.
  const statusLabel = (value: InvoiceStatus) =>
    enums?.invoice_status.find((option) => option.value === value)?.label ?? value;

  return (
    <ContractsShell>
      <div className="mb-6 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Receipt className="h-7 w-7 text-muted-foreground" />
          <h1 className="text-3xl font-bold">Счета на оплату</h1>
        </div>
        <Button asChild>
          <Link to="/contracts/invoices/new">
            <Plus className="mr-2 h-4 w-4" />
            Новый счёт
          </Link>
        </Button>
      </div>

      <div className="bg-card rounded-lg border overflow-x-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-6 text-sm text-destructive">
            Не удалось загрузить счета.
          </p>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-muted-foreground mb-4">Счетов пока нет.</p>
            <Button asChild variant="outline">
              <Link to="/contracts/invoices/new">Выписать первый</Link>
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Наименование</TableHead>
                <TableHead>Контрагент</TableHead>
                <TableHead>Бюджет</TableHead>
                <TableHead className="text-right">Сумма</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead className="text-right">Согласование</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <Link
                        to={`/contracts/invoices/${row.id}`}
                        className="hover:underline underline-offset-2"
                      >
                        {row.name}
                      </Link>
                      {row.file_id && (
                        <Paperclip className="h-3 w-3 text-muted-foreground" />
                      )}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div>{row.counterparty_name}</div>
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {row.counterparty_bin_iin}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div>{row.program_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {row.administrator_name} · {row.period_year}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {formatAmount(row.amount)} {row.currency}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANTS[row.status]}>
                      {statusLabel(row.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <SubmitForApproval
                      subjectType="contracts.invoice"
                      subjectId={row.id}
                      state={row.approval_state}
                      submit={contractsApi.submitInvoice}
                      // На момент отправки счёт ещё не уменьшает остаток;
                      // после решения карточка согласования обновит бюджет.
                      invalidate={[['contracts', 'invoices']]}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </ContractsShell>
  );
};

export default InvoiceList;
