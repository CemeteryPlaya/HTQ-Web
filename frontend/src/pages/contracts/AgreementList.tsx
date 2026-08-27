import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { FileText, Paperclip, Plus } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import {
  CollectionPageHeader,
  CollectionPagination,
  CollectionSearch,
  CollectionTable,
} from '@/components/contracts/CollectionPage';
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
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { formatAmount } from '@/components/contracts/format';
import { contractsApi } from '@/api/contracts';
import type { AgreementStatus } from '@/types/contracts';

/**
 * Список договоров.
 *
 * Администратор и программа показываются, хотя на договоре таких колонок
 * нет — бэкенд разворачивает их из бюджетной строки. Поэтому разойтись с
 * бюджетом они не могут.
 */

const STATUS_VARIANTS: Record<
  AgreementStatus,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  draft: 'outline',
  on_review: 'secondary',
  approved: 'secondary',
  signed: 'default',
  executed: 'default',
  terminated: 'destructive',
};

const AgreementList = () => {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'agreements', { page, search }],
    queryFn: () => contractsApi.listAgreementsPage({
      page, page_size: 25, search: search.trim() || undefined,
    }).then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Подписи статусов берём с бэкенда, а не держим свою копию — иначе при
  // добавлении статуса список молча показывал бы сырой код.
  const statusLabel = (value: AgreementStatus) =>
    enums?.agreement_status.find((option) => option.value === value)?.label ?? value;
  const paymentLabel = (value: string) =>
    enums?.payment_type.find((option) => option.value === value)?.label ?? value;
  const rows = data?.items ?? [];
  const pagination = data?.pagination;
  const hasSearch = search.trim().length > 0;

  return (
    <ContractsShell>
      <CollectionPageHeader
        icon={FileText}
        title="Договоры"
        actions={
          <Button asChild>
            <Link to="/contracts/agreements/new">
              <Plus className="mr-2 h-4 w-4" />
              Новый договор
            </Link>
          </Button>
        }
      >
        <CollectionSearch
          value={search}
          onValueChange={(value) => { setSearch(value); setPage(1); }}
          placeholder="Номер, договор, контрагент, бюджет или статус"
        />
      </CollectionPageHeader>

      <CollectionTable
        isLoading={isLoading}
        isError={isError}
        isEmpty={rows.length === 0}
        errorMessage="Не удалось загрузить договоры."
        emptyMessage={hasSearch ? 'По запросу ничего не найдено.' : 'Договоров пока нет.'}
        emptyAction={
          !hasSearch ? (
            <Button asChild variant="outline">
              <Link to="/contracts/agreements/new">Оформить первый</Link>
            </Button>
          ) : undefined
        }
      >
        <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Номер</TableHead>
                <TableHead>Наименование</TableHead>
                <TableHead>Контрагент</TableHead>
                <TableHead>Бюджет</TableHead>
                <TableHead className="text-right">Сумма</TableHead>
                <TableHead>Оплата</TableHead>
                <TableHead>Статус договора</TableHead>
                {/* Из трёх согласуемых типов только у договора согласование
                    имеет доменное последствие — оно двигает его же `status`.
                    Оси всё равно разные: согласованный по маршруту договор
                    бывает расторгнут по существу. */}
                <TableHead className="text-right">Статус согласования</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <Link
                        to={`/contracts/agreements/${row.id}`}
                        className="hover:underline underline-offset-2"
                      >
                        {row.number}
                      </Link>
                      {row.file_id && (
                        <Paperclip className="h-3 w-3 text-muted-foreground" />
                      )}
                    </span>
                  </TableCell>
                  <TableCell>{row.name}</TableCell>
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
                  <TableCell className="text-sm text-muted-foreground">
                    {paymentLabel(row.payment_type)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANTS[row.status]}>
                      {statusLabel(row.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <SubmitForApproval
                      subjectType="contracts.agreement"
                      subjectId={row.id}
                      state={row.approval_state}
                      submit={contractsApi.submitAgreement}
                      // Отправка переводит договор в on_review, а он уже
                      // занимает бюджет — остаток бюджетных строк меняется
                      // тем же действием.
                      invalidate={[['contracts', 'agreements'], ['contracts', 'budgets']]}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
        </Table>
      </CollectionTable>
      <CollectionPagination pagination={pagination} onPageChange={setPage} isLoading={isLoading} />
    </ContractsShell>
  );
};

export default AgreementList;
