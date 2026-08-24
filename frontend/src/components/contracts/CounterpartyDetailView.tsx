/**
 * Тело карточки контрагента (раздел «Реестр контрагентов»).
 *
 * Отделено от страницы (`pages/contracts/CounterpartyDetail`) ради карточки
 * согласования: `pages/signoff/ProcessDetail` показывает то же тело, не
 * уводя согласующего из его раздела. Рамку выбирает тот, кто рисует.
 *
 * «НДС» и «Контакты» показываются свободным текстом, потому что таковыми и
 * приходят: заказчик не уточнил, значит ли «НДС» признак плательщика или
 * ставку, и бэкенд намеренно не стал угадывать структуру
 * (см. докстринг модели `Counterparty`).
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2 } from 'lucide-react';

import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
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
import { useTranslation } from 'react-i18next';

const STATUS_VARIANTS: Record<
  CounterpartyStatus,
  'secondary' | 'outline' | 'destructive'
> = {
  active: 'secondary',
  inactive: 'outline',
  blocked: 'destructive',
};

interface Props {
  id: number;
  /** Тело вставлено в карточку согласования — см. `BudgetDetailView`. */
  embedded?: boolean;
}

const CounterpartyDetailView = ({ id: counterpartyId, embedded = false }: Props) => {
  const { t } = useTranslation();
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

  if (isLoading) return <DetailSkeleton />;
  if (isError || !counterparty) {
    return (
      <p className="text-sm text-destructive">{t('contracts.counterparty.notFound')}</p>
    );
  }

  const Heading = embedded ? 'h2' : 'h1';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <Building2 className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold break-words">
              {counterparty.name}
            </Heading>
            <Badge variant={STATUS_VARIANTS[counterparty.status]}>
              {statusLabel(counterparty.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground tabular-nums">
            {t('contracts.counterparty.binValue', { value: counterparty.bin_iin })}
          </p>
        </div>

        {!embedded && (
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
            // Карточка объекта — единственное место, где ссылка на
            // согласование нужна и у решённого объекта: там кнопка
            // «Вернуть на доработку», без которой он заперт навсегда.
            showProcessLink
          />
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('contracts.counterparty.details')}</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGrid>
            <Field label={t('contracts.counterparty.bin')}>
              <span className="tabular-nums">{counterparty.bin_iin}</span>
            </Field>
            <Field label={t('contracts.counterparty.country')}>{countryName}</Field>
            <Field label={t('contracts.counterparty.vat')}>{counterparty.vat_label}</Field>
            <Field label={t('contracts.counterparty.ceo')}>
              {counterparty.contact_name || '—'}
            </Field>
            <Field label={t('profile.phone')}>
              {counterparty.phone ? (
                <a
                  href={`tel:${counterparty.phone.replace(/[^\d+]/g, '')}`}
                  className="hover:underline underline-offset-2"
                >
                  {counterparty.phone}
                </a>
              ) : (
                '—'
              )}
            </Field>
            <Field label="E-mail">
              {counterparty.email ? (
                <a
                  href={`mailto:${counterparty.email}`}
                  className="hover:underline underline-offset-2 break-all"
                >
                  {counterparty.email}
                </a>
              ) : (
                '—'
              )}
            </Field>
            <Field label={t('contracts.counterparty.address')} className="sm:col-span-2">
              {counterparty.address || '—'}
            </Field>
            <Field label={t('contracts.counterparty.createdAt')}>{formatMoment(counterparty.created_at)}</Field>
            <Field label={t('contracts.updatedAt')}>{formatMoment(counterparty.updated_at)}</Field>
          </FieldGrid>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {t('contracts.counterparty.agreements')}
            <span className="ml-2 font-normal text-muted-foreground">
              {agreements.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {agreements.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              {t('contracts.counterparty.noAgreements')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('contracts.columns.number')}</TableHead>
                    <TableHead>{t('contracts.columns.title')}</TableHead>
                    <TableHead>{t('contracts.columns.budget')}</TableHead>
                    <TableHead className="text-right">{t('contracts.columns.amount')}</TableHead>
                    <TableHead>{t('contracts.columns.status')}</TableHead>
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

      {!embedded && (
        <SubjectProcesses
          subjectType="contracts.counterparty"
          subjectId={counterparty.id}
        />
      )}
    </div>
  );
};

export default CounterpartyDetailView;
