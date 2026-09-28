/**
 * Справочник «Страны» (ТЗ §18): код ISO 3166-1 alpha-2, наименование, архив.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { refdataApi, refdataKeys, type Country } from './api';
import { ArchivableTable } from './ArchivableTable';
import type { RefField } from './refFields';
import { useRefdataList } from './useRefdataList';

export default function CountriesTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading } = useRefdataList('countries');

  const fields: RefField<Country>[] = [
    { key: 'code', label: t('bpp.refdata.countries.code', 'Код'), editable: false, maxLength: 2 },
    { key: 'name', label: t('bpp.refdata.countries.name', 'Наименование'), maxLength: 128 },
  ];

  return (
    <ArchivableTable
      title={t('bpp.refdata.countries.title', 'Страны')}
      rows={data}
      isLoading={isLoading}
      fields={fields}
      onCreate={(values) => refdataApi.countries.create({
        code: values.code.trim().toUpperCase(), name: values.name.trim(),
      })}
      onPatch={(id, values) => refdataApi.countries.patch(id, { name: values.name.trim() })}
      onToggleActive={(row, is_active) => refdataApi.countries.patch(row.id, { is_active })}
      onChanged={() => queryClient.invalidateQueries({ queryKey: refdataKeys.collection('countries') })}
    />
  );
}
