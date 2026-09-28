/**
 * Реестр L-08 «Контрагенты» (ТЗ §18, §19): поиск по наименованию и номеру,
 * фильтры «страна» и «статус», 50 строк на странице из 25/50/100 — всё
 * считает сервер (`GET bpp/v1/counterparties`), экран лишь показывает.
 *
 * «Создать» — по узлу `bpp.counterparties` `create`: его несут ФД, БУХ, СН и
 * ПМ (ТЗ §05 п.9). Кнопку прячем без права, но судья — сервер (403).
 *
 * Экспорт в xlsx — той же ручкой реестра (`?format=xlsx`, `exportRegistry`);
 * пока сервер не отвечает выгрузкой, кнопка есть, но зовёт понятную ошибку
 * (`ExportNotSupportedError`), а не молчит и не ведёт в JSON.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { usePermissions } from '@/hooks/usePermissions';

import { BppRegistry } from '../core/BppRegistry';
import { statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';

import {
  COUNTERPARTIES_BASE, COUNTERPARTIES_ENDPOINT, COUNTRIES_KEY, counterpartyApi,
  type CounterpartyRow,
} from './api';
import { kindLabel, STATUS_OPTIONS } from './labels';
import { VerifiedMark } from './VerifiedMark';

export function CounterpartiesPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canCreate = permissions.can('bpp.counterparties', 'create');

  const countries = useQuery({
    queryKey: COUNTRIES_KEY,
    queryFn: counterpartyApi.countries,
    staleTime: 10 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<CounterpartyRow>[]>(() => [
    {
      key: 'name',
      title: t('bpp.counterparties.name', 'Наименование'),
      required: true,
      sortable: true,
      render: (row) => (
        <div className="leading-tight">
          <div className="font-medium">{row.short_name || row.name}</div>
          {row.short_name && row.short_name !== row.name && (
            <div className="text-xs text-muted-foreground">{row.name}</div>
          )}
        </div>
      ),
    },
    {
      key: 'reg_number',
      title: t('bpp.counterparties.regNumberShort', 'БИН/ИИН / рег. номер'),
      sortable: true,
      render: (row) => <span className="font-mono">{row.reg_number}</span>,
    },
    { key: 'country_code', title: t('bpp.counterparties.country', 'Страна'), sortable: true },
    {
      key: 'kind',
      title: t('bpp.counterparties.kindTitle', 'Тип'),
      render: (row) => kindLabel(t, row.kind),
    },
    statusColumn<CounterpartyRow>(t, 'counterparty'),
    {
      key: 'is_verified',
      title: t('bpp.counterparties.verifiedTitle', 'Метка'),
      render: (row) => <VerifiedMark isVerified={row.is_verified} override={row.verified_override} />,
    },
    {
      key: 'is_vat_payer',
      title: t('bpp.counterparties.vatPayer', 'Плательщик НДС'),
      render: (row) => (row.is_vat_payer
        ? t('bpp.common.yes', 'Да')
        : t('bpp.common.no', 'Нет')),
    },
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'country',
      label: t('bpp.counterparties.country', 'Страна'),
      kind: 'select',
      options: (countries.data ?? []).map((country) => ({
        value: country.code,
        label: `${country.code} — ${country.name}`,
      })),
    },
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_OPTIONS).map(([value, [key, label]]) => ({
        value,
        label: t(key, label),
      })),
    },
  ], [countries.data, t]);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.counterparties.title', 'Контрагенты')}
      </h2>
      <BppRegistry<CounterpartyRow>
        registryKey="counterparties"
        endpoint={COUNTERPARTIES_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="counterparties"
        searchParam="q"
        searchPlaceholder={t('bpp.counterparties.search', 'Поиск по наименованию и номеру')}
        defaultSort={{ field: 'name', desc: false }}
        defaultHidden={['is_vat_payer']}
        rowHref={(row) => `${COUNTERPARTIES_BASE}/${row.id}`}
        rowLabel={(row) => row.short_name || row.name}
        toolbarExtra={canCreate ? (
          <Button asChild size="sm">
            <Link to={`${COUNTERPARTIES_BASE}/new`}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('bpp.counterparties.create', 'Создать')}
            </Link>
          </Button>
        ) : null}
      />
    </div>
  );
}

export default CounterpartiesPage;
