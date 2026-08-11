import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, Plus, Search } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import {
  CollectionPageHeader,
  CollectionPagination,
  CollectionTable,
} from '@/components/contracts/CollectionPage';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { contractsApi } from '@/api/contracts';
import type { CounterpartyStatus } from '@/types/contracts';

/**
 * Реестр контрагентов — карточки организаций и ИП, с которыми заключаются
 * договоры.
 *
 * Поиск идёт на бэкенде (`?search=`) и покрывает и наименование, и БИН/ИИН
 * одним полем: человек вбивает либо название, либо номер, и заставлять его
 * выбирать, куда именно вводить, незачем.
 */

const STATUS_LABELS: Record<CounterpartyStatus, string> = {
  active: 'Активен',
  inactive: 'Неактивен',
  blocked: 'Заблокирован',
};

const STATUS_VARIANTS: Record<CounterpartyStatus, 'secondary' | 'outline' | 'destructive'> = {
  active: 'secondary',
  inactive: 'outline',
  blocked: 'destructive',
};

const CounterpartyList = () => {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  // Отдельное «применённое» значение: запрос уходит по Enter/кнопке, а не на
  // каждое нажатие клавиши — иначе поиск по БИН слал бы 12 запросов подряд.
  const [applied, setApplied] = useState('');

  const { data, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'counterparties', { page, applied }],
    queryFn: () =>
      contractsApi
        .listCounterpartiesPage({ page, page_size: 25, search: applied || undefined })
        .then((r) => r.data),
  });
  const rows = data?.items ?? [];
  const pagination = data?.pagination;

  return (
    <ContractsShell>
        <CollectionPageHeader
          icon={Building2}
          title="Реестр контрагентов"
          actions={
            <Button asChild>
              <Link to="/contracts/counterparties/new">
                <Plus className="mr-2 h-4 w-4" />
                Новый контрагент
              </Link>
            </Button>
          }
        >
          <form
            className="flex gap-2 max-w-md"
            onSubmit={(event) => {
              event.preventDefault();
              setApplied(search.trim());
              setPage(1);
            }}
          >
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Наименование или БИН/ИИН"
            />
            <Button type="submit" variant="outline">
              <Search className="h-4 w-4" />
            </Button>
          </form>
        </CollectionPageHeader>

        <CollectionTable
          isLoading={isLoading}
          isError={isError}
          isEmpty={rows.length === 0}
          errorMessage="Не удалось загрузить реестр."
          emptyMessage={applied ? 'Ничего не найдено.' : 'Реестр пока пуст.'}
          emptyAction={
            !applied ? (
              <Button asChild variant="outline">
                <Link to="/contracts/counterparties/new">Добавить первого</Link>
              </Button>
            ) : undefined
          }
        >
          <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Наименование</TableHead>
                  <TableHead>БИН / ИИН</TableHead>
                  <TableHead>НДС</TableHead>
                  <TableHead>Адрес</TableHead>
                  <TableHead>Статус контрагента</TableHead>
                  {/* Ось согласования — отдельная от статуса: «заблокирован»
                      и «отклонён» говорят о разном. */}
                  <TableHead className="text-right">Статус согласования</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      <Link
                        to={`/contracts/counterparties/${row.id}`}
                        className="hover:underline underline-offset-2"
                      >
                        {row.name}
                      </Link>
                      {/* Склейка трёх контактных полей приходит с бэкенда
                          (Counterparty.contact_summary) — в строку реестра
                          помещается только она. */}
                      {row.contact_summary && (
                        <div className="text-xs text-muted-foreground">
                          {row.contact_summary}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">{row.bin_iin}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {row.vat_label}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-sm text-muted-foreground" title={row.address || '—'}>
                      {row.address || '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANTS[row.status]}>
                        {STATUS_LABELS[row.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <SubmitForApproval
                        subjectType="contracts.counterparty"
                        subjectId={row.id}
                        state={row.approval_state}
                        submit={contractsApi.submitCounterparty}
                        invalidate={[['contracts', 'counterparties']]}
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

export default CounterpartyList;
