/** /requests/data — Управление данными. Each template auto-owns a data table
 *  (materialized reference source) mirroring all its requests + live state
 *  (Lark "Управление данными" / Base). Read-only, auto-refreshing. Visible to
 *  the template's creator, its process admins, platform admins, and anyone they
 *  granted access to; owners can manage that access. */

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Table2, Users } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { EmployeePicker } from '@/features/requests/components/EmployeePicker';
import { useMyDataTables } from '@/features/requests/hooks';
import type { DataTable } from '@/features/requests/types';
import { useTranslation } from 'react-i18next';

/**
 * Ключи — НЕ подписи интерфейса, а значения из данных запроса: колонка
 * «Статус» приходит с бэкенда строкой по-русски, и таблица показывает её
 * как есть. Переводить ключи нельзя — сломается подбор цвета.
 */
const STATUS_CLASS: Record<string, string> = {
  'На рассмотрении': 'bg-amber-100 text-amber-800',
  'Одобрено': 'bg-emerald-100 text-emerald-800',
  'Отклонено': 'bg-rose-100 text-rose-800',
  'Отменено': 'bg-slate-200 text-slate-700',
  'Возвращено': 'bg-blue-100 text-blue-800',
  'Черновик': 'bg-slate-200 text-slate-700',
};

export default function DataManagementPage() {
  const { t } = useTranslation();
  const tablesQ = useMyDataTables();
  const tables = useMemo(() => tablesQ.data ?? [], [tablesQ.data]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const active = tables.find((t) => t.id === selectedId) ?? tables[0] ?? null;
  const [accessOpen, setAccessOpen] = useState(false);

  const rows = useQuery({
    queryKey: ['requests', 'reference', 'rows', active?.id, 'data-mgmt'],
    queryFn: () => requestsApi.reference.listRows(active!.id),
    enabled: active != null,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  });

  return (
    <RequestsLayout
      title={t('requests.nav.data')}
      subtitle={t('requests.data.subtitle')}
      actions={active && (
        <>
          {active.can_manage && (
            <Button variant="outline" size="sm" onClick={() => setAccessOpen(true)}>
              <Users className="mr-2 h-4 w-4" /> {t('requests.data.access')}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => rows.refetch()}>
            <RefreshCw className={`mr-2 h-4 w-4 ${rows.isFetching ? 'animate-spin' : ''}`} /> {t('email.actions.refresh')}
          </Button>
        </>
      )}
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)] items-start">
        <Card>
          <CardContent className="p-0">
            <div className="border-b px-4 py-2 text-xs font-semibold uppercase text-muted-foreground">{t('requests.data.tables')}</div>
            {tablesQ.isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>}
            {!tablesQ.isLoading && tables.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                {t('requests.data.noTables')}
              </div>
            )}
            {tables.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setSelectedId(t.id)}
                className={`flex w-full items-center gap-2 border-b px-4 py-2.5 text-left text-sm last:border-b-0 ${active?.id === t.id ? 'bg-primary/10' : 'hover:bg-muted/40'}`}
              >
                <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{t.name}</span>
              </button>
            ))}
          </CardContent>
        </Card>

        <div>
          {!active ? (
            <Card><CardContent className="py-16 text-center text-sm text-muted-foreground">{t('requests.data.pickTable')}</CardContent></Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="flex items-center justify-between border-b px-4 py-2">
                  <span className="font-medium">{active.name}</span>
                  <span className="text-xs text-muted-foreground">{t('requests.data.recordCount', { count: rows.data?.length ?? 0 })}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/30 text-left text-xs uppercase text-muted-foreground">
                        {active.columns.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2">{c}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.isLoading && (
                        <tr><td colSpan={active.columns.length} className="px-3 py-6"><Skeleton className="h-6" /></td></tr>
                      )}
                      {!rows.isLoading && (rows.data?.length ?? 0) === 0 && (
                        <tr><td colSpan={active.columns.length} className="px-3 py-10 text-center text-muted-foreground">{t('requests.data.noRequests')}</td></tr>
                      )}
                      {rows.data?.map((r) => (
                        <tr key={r.id} className="border-b last:border-b-0 hover:bg-muted/20">
                          {active.columns.map((c) => {
                            const val = String((r.data as Record<string, unknown>)[c] ?? '');
                            if (c === 'Статус' && val) {
                              return <td key={c} className="whitespace-nowrap px-3 py-2"><Badge variant="outline" className={STATUS_CLASS[val] ?? ''}>{val}</Badge></td>;
                            }
                            return <td key={c} className="whitespace-nowrap px-3 py-2">{val}</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {active && active.can_manage && (
        <AccessDialog table={active} open={accessOpen} onOpenChange={setAccessOpen} />
      )}
    </RequestsLayout>
  );
}

function AccessDialog({ table, open, onOpenChange }: { table: DataTable; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [ids, setIds] = useState<number[]>(table.access_ids ?? []);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await requestsApi.reference.setAccess(table.id, ids);
      qc.invalidateQueries({ queryKey: ['requests', 'reference', 'my-data-tables'] });
      toast.success(t('requests.data.accessUpdated'));
      onOpenChange(false);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.editor.saveError'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t('requests.data.accessTitle', { name: table.name })}</DialogTitle></DialogHeader>
        <div className="space-y-2 py-2">
          <Label className="text-sm">{t('requests.data.accessHint')}</Label>
          <EmployeePicker value={ids} onChange={setIds} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button disabled={busy} onClick={save}>{t('common.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
