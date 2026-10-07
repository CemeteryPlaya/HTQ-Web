/**
 * Справочник потенциальных поставщиков (`/tender/prospects`, T2.3; план
 * §4.1, §4.3): поставщики, которых ещё нет среди контрагентов БЗО, — их
 * приглашают в тендер так же, как контрагентов. Создание и правка — по
 * признакам `create`/`edit` узла `tender.prospects`.
 */
import { useDeferredValue, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { usePermissions } from '@/hooks/usePermissions';

import { prospectKeys, prospectsApi, type Prospect } from './api';
import { ProspectDialog } from './ProspectDialog';

export function ProspectsPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const queryClient = useQueryClient();
  const canCreate = permissions.can('tender.prospects', 'create');
  const canEdit = permissions.can('tender.prospects', 'edit');
  const [search, setSearch] = useState('');
  const q = useDeferredValue(search.trim());
  // `undefined` — диалог закрыт, `null` — новый поставщик.
  const [editing, setEditing] = useState<Prospect | null | undefined>(undefined);

  const { data, isLoading, isError } = useQuery({
    queryKey: prospectKeys.list(q),
    queryFn: () => prospectsApi.list(q),
    placeholderData: keepPreviousData,
  });

  const saved = () => {
    setEditing(undefined);
    void queryClient.invalidateQueries({ queryKey: prospectKeys.all });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{t('tender.prospects.title', 'Потенциальные поставщики')}</h2>
        {canCreate && (
          <Button type="button" onClick={() => setEditing(null)}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('tender.prospects.create', 'Добавить поставщика')}
          </Button>
        )}
      </div>

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          type="search" className="pl-8" value={search}
          placeholder={t('tender.prospects.searchHint', 'Наименование, e-mail или рег. номер')}
          aria-label={t('tender.prospects.search', 'Поиск')}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : isError ? (
        <p className="text-sm text-destructive">{t('tender.prospects.listFailed', 'Не удалось загрузить поставщиков.')}</p>
      ) : (data ?? []).length === 0 ? (
        <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">
          {t('tender.prospects.empty', 'Потенциальных поставщиков пока нет')}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('tender.prospects.name', 'Наименование')}</TableHead>
                <TableHead>{t('tender.prospects.email', 'E-mail')}</TableHead>
                <TableHead>{t('tender.prospects.regNumber', 'Рег. номер (БИН/ИИН)')}</TableHead>
                <TableHead>{t('tender.prospects.countryShort', 'Страна')}</TableHead>
                {canEdit && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <div className="font-medium">{row.name}</div>
                    {row.counterparty_id && (
                      <div className="text-xs text-muted-foreground">
                        {t('tender.prospects.linked', 'Заведён контрагентом БЗО')}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{row.email}</TableCell>
                  <TableCell>{row.reg_number || '—'}</TableCell>
                  <TableCell>{row.country_code}</TableCell>
                  {canEdit && (
                    <TableCell className="text-right">
                      <Button
                        type="button" size="icon" variant="ghost"
                        aria-label={t('tender.prospects.editRow', 'Изменить {{name}}', { name: row.name })}
                        onClick={() => setEditing(row)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {editing !== undefined && (
        <ProspectDialog prospect={editing} onClose={() => setEditing(undefined)} onSaved={saved} />
      )}
    </div>
  );
}

export default ProspectsPage;
