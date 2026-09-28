/**
 * Справочник «Единицы измерения» (ТЗ §18): код, краткое и полное имя, архив.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { refdataApi, refdataKeys, type Uom } from './api';
import { ArchivableTable } from './ArchivableTable';
import type { RefField } from './refFields';
import { useRefdataList } from './useRefdataList';

export default function UomsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading } = useRefdataList('uoms');

  const fields: RefField<Uom>[] = [
    { key: 'code', label: t('bpp.refdata.uoms.code', 'Код'), editable: false, maxLength: 16 },
    { key: 'short_name', label: t('bpp.refdata.uoms.shortName', 'Кратко'), maxLength: 16 },
    { key: 'name', label: t('bpp.refdata.uoms.name', 'Наименование'), maxLength: 64 },
  ];

  return (
    <ArchivableTable
      title={t('bpp.refdata.uoms.title', 'Единицы измерения')}
      rows={data}
      isLoading={isLoading}
      fields={fields}
      onCreate={(values) => refdataApi.uoms.create({
        code: values.code.trim(), short_name: values.short_name.trim(), name: values.name.trim(),
      })}
      onPatch={(id, values) => refdataApi.uoms.patch(id, {
        short_name: values.short_name.trim(), name: values.name.trim(),
      })}
      onToggleActive={(row, is_active) => refdataApi.uoms.patch(row.id, { is_active })}
      onChanged={() => queryClient.invalidateQueries({ queryKey: refdataKeys.collection('uoms') })}
    />
  );
}
