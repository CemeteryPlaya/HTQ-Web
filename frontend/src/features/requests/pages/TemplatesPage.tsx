/** /requests/templates — list all visible templates + create new shell. */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { QK, useProjects, useTemplates } from '@/features/requests/hooks';
import type { FormTemplate } from '@/features/requests/types';
import { useTranslation } from 'react-i18next';

export default function TemplatesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const projects = useProjects();
  const templates = useTemplates(null);
  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState<string>('none');

  const create = useMutation({
    mutationFn: () =>
      requestsApi.templates.create({
        name: name.trim(),
        project_id: projectId === 'none' ? null : Number(projectId),
      }),
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: QK.templates(null) });
      setName('');
      setProjectId('none');
      toast.success(t('requests.templates.created', { name: tpl.name }));
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? e?.message ?? t('requests.templates.createError');
      toast.error(detail);
    },
  });

  return (
    <RequestsLayout
      title={t('requests.templates.title')}
      subtitle={t('requests.templates.subtitle')}
    >
      <Card>
        <CardHeader>
          <CardTitle>{t('requests.templates.create')}</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
            className="grid gap-4 sm:grid-cols-[1fr_220px_auto] sm:items-end"
          >
            <div className="space-y-1.5">
              <Label htmlFor="tpl-name">{t('hr.pmo.name')}</Label>
              <Input
                id="tpl-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder={t('requests.templates.namePlaceholder')}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tpl-project">{t('requests.templates.project')}</Label>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger id="tpl-project">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('requests.templates.globalOption')}</SelectItem>
                  {projects.data?.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              {t('requests.templates.create')}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {templates.isLoading && (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          )}
          {!templates.isLoading && templates.data?.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              {t('requests.templates.empty')}
            </div>
          )}
          {templates.data?.map((tpl) => (
            <div
              key={tpl.id}
              className="flex items-center justify-between gap-3 border-b px-4 py-3 last:border-b-0 hover:bg-muted/40"
            >
              <Link to={`/requests/templates/${tpl.id}/editor`} className="flex min-w-0 items-center gap-3">
                <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <div className="truncate font-medium">{tpl.name}</div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>slug «{tpl.slug}»</span>
                    <span>·</span>
                    {tpl.project_id != null ? (
                      <span>{t('requests.templates.projectNumber', { id: tpl.project_id })}</span>
                    ) : (
                      <Badge variant="secondary">{t('requests.templates.global')}</Badge>
                    )}
                    <span>·</span>
                    {tpl.current_version_id == null ? (
                      <Badge variant="outline" className="bg-amber-100 text-amber-800 hover:bg-amber-100">{t('requests.templates.draft')}</Badge>
                    ) : (
                      <span>{t('requests.templates.versionNumber', { id: tpl.current_version_id })}</span>
                    )}
                    {tpl.status === 'inactive' && (
                      <Badge variant="outline" className="bg-rose-100 text-rose-800 hover:bg-rose-100">{t('requests.templates.deactivated')}</Badge>
                    )}
                  </div>
                </div>
              </Link>
              <TemplateActions tpl={tpl} />
            </div>
          ))}
        </CardContent>
      </Card>
    </RequestsLayout>
  );
}

function TemplateActions({ tpl }: { tpl: FormTemplate }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      qc.invalidateQueries({ queryKey: QK.templates(null) });
      toast.success(ok);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.templates.actionError'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex shrink-0 items-center gap-2">
      {tpl.status === 'inactive' ? (
        <Button variant="outline" size="sm" disabled={busy}
          onClick={() => run(() => requestsApi.templates.activate(tpl.id), t('requests.templates.activated'))}>
          {t('requests.templates.activate')}
        </Button>
      ) : (
        <Button variant="outline" size="sm" disabled={busy}
          onClick={() => run(() => requestsApi.templates.deactivate(tpl.id), t('requests.templates.deactivatedToast'))}>
          {t('requests.templates.deactivate')}
        </Button>
      )}
      <Button
        variant="ghost" size="sm" className="text-destructive hover:text-destructive" disabled={busy}
        aria-label={t('requests.templates.delete')}
        onClick={() => {
          if (window.confirm(t('requests.templates.confirmDelete', { name: tpl.name }))) {
            run(() => requestsApi.templates.remove(tpl.id), t('requests.templates.deleted'));
          }
        }}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}
