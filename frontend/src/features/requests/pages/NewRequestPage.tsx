/** /requests/new — Lark-style catalog: pick a form from the grid, then fill
 *  it in and save-as-draft or submit for approval. */

import { useMemo, useState } from 'react';
import { ArrowLeft, FileText, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { FormRenderer } from '@/features/requests/components/FormRenderer';
import { useTemplate, useTemplates, useTemplateVersion } from '@/features/requests/hooks';
import type { FormTemplate } from '@/features/requests/types';

function CatalogCard({ t, onPick }: { t: FormTemplate; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      className="flex items-center gap-3 rounded-xl border bg-card/70 p-4 text-left shadow-[var(--shadow-soft)] transition-colors hover:bg-muted/40"
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white"
        style={{ backgroundColor: t.color || '#3b82f6' }}
      >
        <FileText className="h-5 w-5" />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{t.name}</span>
        {t.description && (
          <span className="block truncate text-xs text-muted-foreground">{t.description}</span>
        )}
      </span>
    </button>
  );
}

export default function NewRequestPage() {
  const navigate = useNavigate();
  const templates = useTemplates(null);
  const [tplId, setTplId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [title, setTitle] = useState('');
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);

  const tpl = useTemplate(tplId);
  const ver = useTemplateVersion(tplId, tpl.data?.current_version_id ?? null);

  const activeTemplates = useMemo(
    () => (templates.data ?? []).filter((t) => t.is_active && t.current_version_id != null),
    [templates.data],
  );
  const filtered = useMemo(
    () => activeTemplates.filter((t) => t.name.toLowerCase().includes(search.trim().toLowerCase())),
    [activeTemplates, search],
  );

  async function persistAndOptionallySubmit(submitAfter: boolean) {
    if (!tplId) return;
    setBusy(true);
    try {
      const draft = await requestsApi.instances.create({
        template_id: tplId,
        title: title || undefined,
        form_values: values,
      });
      if (submitAfter) {
        try {
          const sent = await requestsApi.instances.submit(draft.id);
          toast.success(`Запрос ${sent.code} отправлен на согласование`);
          navigate(`/requests/${sent.id}`);
          return;
        } catch (e: any) {
          toast.error(e?.response?.data?.detail ?? 'Не удалось отправить — открыта страница черновика');
          navigate(`/requests/${draft.id}`);
          return;
        }
      }
      toast.success('Черновик сохранён');
      navigate(`/requests/${draft.id}`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? e?.message ?? 'Не удалось создать запрос');
    } finally {
      setBusy(false);
    }
  }

  // ─── Catalog view — pick a form ─────────────────────────────────────────
  if (tplId == null) {
    return (
      <RequestsLayout title="Отправить запрос" subtitle="Выберите форму запроса">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск формы…"
            className="pl-9"
          />
        </div>

        {templates.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-20" />)}
          </div>
        ) : filtered.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              {activeTemplates.length === 0
                ? 'Нет опубликованных форм. Создайте шаблон в разделе «Шаблоны».'
                : 'Ничего не найдено.'}
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            <div className="text-sm uppercase tracking-[0.2em] text-muted-foreground">Все запросы</div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((t) => (
                <CatalogCard
                  key={t.id}
                  t={t}
                  onPick={() => { setTplId(t.id); setValues({}); setTitle(''); }}
                />
              ))}
            </div>
          </div>
        )}
      </RequestsLayout>
    );
  }

  // ─── Fill view — the chosen form ────────────────────────────────────────
  return (
    <RequestsLayout
      title={tpl.data?.name ?? 'Новый запрос'}
      subtitle="Заполните форму запроса"
      actions={
        <Button variant="outline" onClick={() => setTplId(null)}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          К списку форм
        </Button>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Заголовок</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            <Label htmlFor="title">Заголовок</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Краткое название запроса"
            />
          </div>
        </CardContent>
      </Card>

      {ver.isLoading && <Skeleton className="h-40" />}
      {ver.data && (
        <Card>
          <CardHeader>
            <CardTitle>Поля формы</CardTitle>
          </CardHeader>
          <CardContent>
            <FormRenderer schema={ver.data.schema_json} values={values} onChange={setValues} />
          </CardContent>
        </Card>
      )}

      {ver.data && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={() => persistAndOptionallySubmit(false)}>
            Сохранить черновик
          </Button>
          <Button disabled={busy} onClick={() => persistAndOptionallySubmit(true)}>
            Отправить на согласование
          </Button>
        </div>
      )}
    </RequestsLayout>
  );
}
