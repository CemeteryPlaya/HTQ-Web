/**
 * Карточка контрагента («Реестр контрактов» в терминах заказчика).
 *
 * Куда ведут ссылки signoff'а на `contracts.counterparty` — колбэк
 * `approval_hooks._describe_counterparty` строит именно этот путь.
 *
 * «НДС» и «Контакты» показываются свободным текстом, потому что таковыми и
 * приходят: заказчик не уточнил, значит ли «НДС» признак плательщика или
 * ставку, и бэкенд намеренно не стал угадывать структуру
 * (см. докстринг модели `Counterparty`).
 */

import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2 } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import {
  BackLink,
  DetailSkeleton,
  Field,
  FieldGrid,
} from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { contractsApi } from '@/api/contracts';
import type { AgreementStatus, CounterpartyStatus } from '@/types/contracts';

const STATUS_VARIANTS: Record<
  CounterpartyStatus,
  'secondary' | 'outline' | 'destructive'
> = {
  active: 'secondary',
  inactive: 'outline',
  blocked: 'destructive',
};

const CounterpartyDetail = () => {
  const { id } = useParams<{ id: string }>();
  const counterpartyId = Number(id);
  const enabled = Number.isFinite(counterpartyId);

  const {
    data: counterparty,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['contracts', 'counterparty', counterpartyId],
    queryFn: () => contractsApi.getCounterparty(counterpartyId).then((r) => r.data),
    enabled,
  });

  const { data: agreements = [] } = useQuery({
    queryKey: ['contracts', 'agreements', { counterparty_id: counterpartyId }],
    queryFn: () =>
      contractsApi
        .listAgreements({ counterparty_id: counterpartyId })
        .then((r) => r.data),
    enabled,
  });

  // Страна приходит идентификатором — карточка показывает название, поэтому
  // тянет справочник целиком. Он короткий и кэшируется на весь раздел.
  const { data: countries = [] } = useQuery({
    queryKey: ['contracts', 'countries'],
    queryFn: () => contractsApi.listCountries().then((r) => r.data),
  });

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  const statusLabel = (value: CounterpartyStatus) =>
    enums?.counterparty_status.find((option) => option.value === value)?.label
    ?? value;
  const agreementStatusLabel = (value: AgreementStatus) =>
    enums?.agreement_status.find((option) => option.value === value)?.label ?? value;

  const countryName =
    countries.find((row) => row.id === counterparty?.country_id)?.name ?? '—';

  return (
    <ContractsShell>
      <BackLink to="/contracts/counterparties">Ко всему реестру</BackLink>

      {isLoading ? (
        <DetailSkeleton />
      ) : isError || !counterparty ? (
        <p className="text-sm text-destructive">
          Контрагент не найден или недоступен.
        </p>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <Building2 className="h-7 w-7 shrink-0 text-muted-foreground" />
                <h1 className="text-3xl font-bold break-words">
                  {counterparty.name}
                </h1>
                <Badge variant={STATUS_VARIANTS[counterparty.status]}>
                  {statusLabel(counterparty.status)}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground tabular-nums">
                БИН / ИИН {counterparty.bin_iin}
              </p>
            </div>

            <SubmitForApproval
              subjectType="contracts.counterparty"
              subjectId={counterparty.id}
              state={counterparty.approval_state}
              submit={contractsApi.submitCounterparty}
              invalidate={[
                ['contracts', 'counterparties'],
                ['contracts', 'counterparty', counterpartyId],
              ]}
              size="default"
            />
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Реквизиты</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldGrid>
                <Field label="БИН / ИИН">
                  <span className="tabular-nums">{counterparty.bin_iin}</span>
                </Field>
                <Field label="Страна">{countryName}</Field>
                <Field label="НДС">{counterparty.vat_label}</Field>
                <Field label="Контакты">{counterparty.contacts || '—'}</Field>
                <Field label="Адрес" className="sm:col-span-2">
                  {counterparty.address || '—'}
                </Field>
                <Field label="Заведён">{formatMoment(counterparty.created_at)}</Field>
                <Field label="Изменён">{formatMoment(counterparty.updated_at)}</Field>
              </FieldGrid>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">
                Договоры с контрагентом
                <span className="ml-2 font-normal text-muted-foreground">
                  {agreements.length}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="px-0 pb-0">
              {agreements.length === 0 ? (
                <p className="px-6 pb-6 text-sm text-muted-foreground">
                  С этим контрагентом договоров пока нет.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Номер</TableHead>
                        <TableHead>Наименование</TableHead>
                        <TableHead>Бюджет</TableHead>
                        <TableHead className="text-right">Сумма</TableHead>
                        <TableHead>Статус</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {agreements.map((row) => (
                        <TableRow key={row.id}>
                          <TableCell className="font-medium whitespace-nowrap">
                            <Link
                              to={`/contracts/agreements/${row.id}`}
                              className="hover:underline underline-offset-2"
                            >
                              {row.number}
                            </Link>
                          </TableCell>
                          <TableCell>{row.name}</TableCell>
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
                            <Badge variant="outline">
                              {agreementStatusLabel(row.status)}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          <SubjectProcesses
            subjectType="contracts.counterparty"
            subjectId={counterparty.id}
          />
        </div>
      )}
    </ContractsShell>
  );
};

export default CounterpartyDetail;
