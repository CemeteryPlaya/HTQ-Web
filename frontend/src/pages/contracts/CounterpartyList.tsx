import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, Plus, Search } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
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
import { Skeleton } from '@/components/ui/skeleton';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { contractsApi } from '@/api/contracts';
import type { CounterpartyStatus } from '@/types/contracts';

/**
 * Реестр контрактов — карточки организаций и ИП, с которыми заключаются
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
  // Отдельное «применённое» значение: запрос уходит по Enter/кнопке, а не на
  // каждое нажатие клавиши — иначе поиск по БИН слал бы 12 запросов подряд.
  const [applied, setApplied] = useState('');

  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'counterparties', applied],
    queryFn: () =>
      contractsApi
        .listCounterparties(applied ? { search: applied } : undefined)
        .then((r) => r.data),
  });

  return (
    <ContractsShell>
        <div className="mb-6 flex flex-col gap-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <Building2 className="h-7 w-7 text-muted-foreground" />
              <h1 className="text-3xl font-bold">Реестр контрактов</h1>
            </div>
            <Button asChild>
              <Link to="/contracts/counterparties/new">
                <Plus className="mr-2 h-4 w-4" />
                Новый контрагент
              </Link>
            </Button>
          </div>

          <form
            className="flex gap-2 max-w-md"
            onSubmit={(event) => {
              event.preventDefault();
              setApplied(search.trim());
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
              Не удалось загрузить реестр.
            </p>
          ) : rows.length === 0 ? (
            <div className="p-10 text-center">
              <p className="text-muted-foreground mb-4">
                {applied ? 'Ничего не найдено.' : 'Реестр пока пуст.'}
              </p>
              {!applied && (
                <Button asChild variant="outline">
                  <Link to="/contracts/counterparties/new">Добавить первого</Link>
                </Button>
              )}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Наименование</TableHead>
                  <TableHead>БИН / ИИН</TableHead>
                  <TableHead>НДС</TableHead>
                  <TableHead>Адрес</TableHead>
                  <TableHead>Статус</TableHead>
                  {/* Ось согласования — отдельная от статуса: «заблокирован»
                      и «отклонён» говорят о разном. */}
                  <TableHead className="text-right">Согласование</TableHead>
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
                      {row.contacts && (
                        <div className="text-xs text-muted-foreground">
                          {row.contacts}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">{row.bin_iin}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {row.vat || '—'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
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
          )}
        </div>
    </ContractsShell>
  );
};

export default CounterpartyList;
