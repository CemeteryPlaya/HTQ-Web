/** /requests/reference — admin management of reference data sources
 *  (Lark-Base-style lookup tables). Create sources with columns, then add/remove
 *  rows. Form `reference` widgets read their options from these. */

import { useQueryClient } from '@tanstack/react-query';
import { Database, Plus, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { useReferenceRows, useReferenceSources } from '@/features/requests/hooks';
import type { ReferenceSource } from '@/features/requests/types';
import { useTranslation } from 'react-i18next';

const RK = { sources: ['requests', 'reference', 'sources'] as const, rows: (id: number) => ['requests', 'reference', 'rows', id] as const };

export default function ReferenceSourcesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const sources = useReferenceSources();
  // Template data tables (template_id set) live on the "Управление данными"
  // screen; here we only manage manually-created reference sources.
  const manual = (sources.data ?? []).filter((s) => s.template_id == null);
  const [selected, setSelected] = useState<ReferenceSource | null>(null);

  const [name, setName] = useState('');
  const [cols, setCols] = useState('');

  async function createSource(e: FormEvent) {
    e.preventDefault();
    const columns = cols.split(',').map((s) => s.trim()).filter(Boolean);
    if (!name.trim() || columns.length === 0) return;
    try {
      await requestsApi.reference.create({ name: name.trim(), columns });
      qc.invalidateQueries({ queryKey: RK.sources });
      setName(''); setCols('');
      toast.success(t('requests.reference.created'));
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.reference.createError'));
    }
  }

  async function removeSource(id: number) {
    try {
      await requestsApi.reference.remove(id);
      qc.invalidateQueries({ queryKey: RK.sources });
      if (selected?.id === id) setSelected(null);
      toast.success(t('requests.reference.deleted'));
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.projects.deleteError'));
    }
  }

  return (
    <RequestsLayout title={t('requests.nav.reference')} subtitle={t('requests.reference.subtitle')}>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] items-start">
        {/* left: sources list + create */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base">{t('requests.reference.create')}</CardTitle></CardHeader>
            <CardContent>
              <form onSubmit={createSource} className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="rs-name">{t('hr.pmo.name')}</Label>
                  <Input id="rs-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t('requests.reference.namePlaceholder')} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rs-cols">{t('requests.reference.columns')}</Label>
                  <Input id="rs-cols" value={cols} onChange={(e) => setCols(e.target.value)} placeholder="admin, budget, spec" />
                </div>
                <Button type="submit" size="sm"><Plus className="mr-1 h-4 w-4" /> {t('common.create')}</Button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              {sources.isLoading && <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>}
              {!sources.isLoading && manual.length === 0 && (
                <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t('requests.reference.empty')}</div>
              )}
              {manual.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelected(s)}
                  className={`flex w-full items-center justify-between border-b px-4 py-3 text-left last:border-b-0 ${selected?.id === s.id ? 'bg-primary/10' : 'hover:bg-muted/40'}`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <Database className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{s.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">slug «{s.slug}» · {s.columns.join(', ')}</span>
                    </span>
                  </span>
                  <span onClick={(e) => { e.stopPropagation(); removeSource(s.id); }} className="text-muted-foreground hover:text-destructive" role="button" aria-label={t('requests.reference.deleteSource')}>
                    <Trash2 className="h-4 w-4" />
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* right: rows of the selected source */}
        <div>
          {selected ? <RowsEditor source={selected} /> : (
            <Card><CardContent className="py-16 text-center text-sm text-muted-foreground">{t('requests.reference.pickToEdit')}</CardContent></Card>
          )}
        </div>
      </div>
    </RequestsLayout>
  );
}

function RowsEditor({ source }: { source: ReferenceSource }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const rows = useReferenceRows(source.id);
  const [draft, setDraft] = useState<Record<string, string>>({});

  async function addRow() {
    if (source.columns.every((c) => !draft[c])) return;
    try {
      await requestsApi.reference.addRow(source.id, draft);
      qc.invalidateQueries({ queryKey: RK.rows(source.id) });
      setDraft({});
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.reference.addRowError'));
    }
  }
  async function delRow(rowId: number) {
    await requestsApi.reference.removeRow(source.id, rowId);
    qc.invalidateQueries({ queryKey: RK.rows(source.id) });
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{t('requests.reference.rowsTitle', { name: source.name })}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                {source.columns.map((c) => <th key={c} className="px-2 py-1.5">{c}</th>)}
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.data?.map((r) => (
                <tr key={r.id} className="border-b last:border-b-0">
                  {source.columns.map((c) => <td key={c} className="px-2 py-1.5">{String((r.data as any)[c] ?? '')}</td>)}
                  <td className="px-2 py-1.5">
                    <button type="button" onClick={() => delRow(r.id)} className="text-muted-foreground hover:text-destructive" aria-label={t('requests.reference.deleteRow')}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {/* new row */}
              <tr>
                {source.columns.map((c) => (
                  <td key={c} className="px-2 py-1.5">
                    <Input value={draft[c] ?? ''} onChange={(e) => setDraft((d) => ({ ...d, [c]: e.target.value }))} className="h-8" placeholder={c} />
                  </td>
                ))}
                <td className="px-2 py-1.5">
                  <Button type="button" size="sm" variant="outline" onClick={addRow}><Plus className="h-4 w-4" /></Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        {rows.data?.length === 0 && <p className="text-xs text-muted-foreground">{t('requests.reference.noRows')}</p>}
      </CardContent>
    </Card>
  );
}
