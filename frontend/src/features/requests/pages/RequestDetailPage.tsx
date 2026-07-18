/** /requests/:id — view + act on a single request instance. */

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { ActionBar } from '@/features/requests/components/ActionBar';
import { ApprovalTimeline } from '@/features/requests/components/ApprovalTimeline';
import { FormRenderer } from '@/features/requests/components/FormRenderer';
import {
  QK, useInstance, useRequestsStream, useSubmitInstance, useTemplate, useTemplateVersion,
} from '@/features/requests/hooks';
import { useActiveProfile } from '@/hooks/useActiveProfile';

export default function RequestDetailPage() {
  useRequestsStream();
  const { id } = useParams<{ id: string }>();
  const instanceId = id ? parseInt(id, 10) : NaN;
  const inst = useInstance(Number.isNaN(instanceId) ? null : instanceId);
  const tpl = useTemplate(inst.data?.template_id ?? null);
  const ver = useTemplateVersion(
    inst.data?.template_id ?? null,
    inst.data?.template_version_id ?? null,
  );
  const profile = useActiveProfile();
  const qc = useQueryClient();
  const submit = useSubmitInstance(instanceId);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);

  if (Number.isNaN(instanceId)) {
    return (
      <RequestsLayout title="Запрос не найден">
        <Card><CardContent className="py-6 text-sm text-destructive">Некорректный идентификатор запроса.</CardContent></Card>
      </RequestsLayout>
    );
  }
  if (inst.isLoading) {
    return (
      <RequestsLayout title="Загрузка…">
        <Skeleton className="h-32" />
        <Skeleton className="h-48" />
      </RequestsLayout>
    );
  }
  if (inst.error || !inst.data) {
    return (
      <RequestsLayout title="Запрос не найден">
        <Card><CardContent className="py-6 text-sm text-destructive">Запрос не найден или нет доступа.</CardContent></Card>
      </RequestsLayout>
    );
  }

  const data = inst.data;
  const currentUserId = parseInt(profile.activeProfile?.id ?? '0', 10) || 0;
  const isElevated = (profile.activeProfile?.roles ?? []).some((r) =>
    ['admin', 'staff', 'superuser'].includes(r),
  );
  const isInitiator = data.initiator_id === currentUserId;
  const isEditable = isInitiator && (data.status === 'draft' || data.status === 'returned');
  const values = draft ?? (data.form_values_json as Record<string, unknown>);
  const subtitle = `${data.code}${tpl.data ? ` · шаблон «${tpl.data.name}»` : ''}`;

  async function persistDraft() {
    if (!draft) return;
    setSaving(true);
    try {
      const updated = await requestsApi.instances.update(instanceId, { form_values: draft });
      qc.setQueryData(QK.instance(instanceId), updated);
      setDraft(null);
      toast.success('Черновик сохранён');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Не удалось сохранить черновик');
    } finally {
      setSaving(false);
    }
  }

  async function onSubmit() {
    if (draft) await persistDraft();
    try {
      await submit.mutateAsync();
      toast.success('Запрос отправлен на согласование');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Не удалось отправить');
    }
  }

  return (
    <RequestsLayout title={data.title || data.code} subtitle={subtitle}>
      <ApprovalTimeline instance={data} />

      <Card>
        <CardHeader>
          <CardTitle>Поля формы</CardTitle>
        </CardHeader>
        <CardContent>
          {ver.isLoading && <Skeleton className="h-24" />}
          {ver.data && (
            <FormRenderer
              schema={ver.data.schema_json}
              values={values}
              onChange={(v) => setDraft(v)}
              readOnly={!isEditable}
            />
          )}
        </CardContent>
      </Card>

      {isEditable && (
        <div className="flex flex-wrap gap-2">
          {draft && (
            <Button variant="outline" onClick={persistDraft} disabled={saving}>
              Сохранить черновик
            </Button>
          )}
          <Button onClick={onSubmit} disabled={submit.isPending}>
            {data.status === 'returned' ? 'Отправить повторно' : 'Отправить на согласование'}
          </Button>
        </div>
      )}

      <ActionBar
        instance={data}
        currentUserId={currentUserId}
        isElevated={isElevated}
        canApprove={data.status === 'pending'}
      />
    </RequestsLayout>
  );
}
