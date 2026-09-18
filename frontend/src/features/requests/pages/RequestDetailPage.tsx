/** /requests/:id — карточка заявки.
 *
 * Решения по заявке принимает `apps.signoff` — тот же движок, что согласует
 * договоры, — поэтому здесь те же блоки, что на карточке договора: кнопка
 * «На согласование» (`SubmitForApproval`) и история кругов
 * (`SubjectProcesses`). Собственной ленты решений у заявок больше нет:
 * одобрить или вернуть её согласующий может из «Ждёт меня» или из карточки
 * процесса, куда и ведут ссылки. */

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { REQUEST_SUBJECT_TYPE } from '@/features/requests/subject';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { FormRenderer } from '@/features/requests/components/FormRenderer';
import { LinkedDocuments } from '@/features/requests/components/LinkedDocuments';
import { hasBudgetLine } from '@/features/requests/hasBudgetLine';
import { blockedByRequired } from '@/features/requests/requiredFields';
import {
  QK, useInstance, useRequestsStream, useTemplate, useTemplateVersion,
} from '@/features/requests/hooks';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { useTranslation } from 'react-i18next';

export default function RequestDetailPage() {
  const { t } = useTranslation();
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
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);

  if (Number.isNaN(instanceId)) {
    return (
      <RequestsLayout title={t('requests.detail.notFound')}>
        <Card><CardContent className="py-6 text-sm text-destructive">{t('requests.detail.badId')}</CardContent></Card>
      </RequestsLayout>
    );
  }
  if (inst.isLoading) {
    return (
      <RequestsLayout title={t('signoff.loadingEllipsis')}>
        <Skeleton className="h-32" />
        <Skeleton className="h-48" />
      </RequestsLayout>
    );
  }
  if (inst.error || !inst.data) {
    return (
      <RequestsLayout title={t('requests.detail.notFound')}>
        <Card><CardContent className="py-6 text-sm text-destructive">{t('requests.detail.notFoundOrNoAccess')}</CardContent></Card>
      </RequestsLayout>
    );
  }

  const data = inst.data;
  const currentUserId = parseInt(profile.activeProfile?.id ?? '0', 10) || 0;
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
      toast.success(t('requests.new.draftSaved'));
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? t('requests.detail.draftSaveError'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <RequestsLayout title={data.title || data.code} subtitle={subtitle}>
      <Card>
        <CardHeader>
          <CardTitle>{t('requests.builder.fields')}</CardTitle>
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

      {/* Одобренная заявка со строкой бюджета исполняется договором или счётом
          в разделе «Договоры» — здесь видно, что по ней уже заведено. */}
      {data.status === 'approved' && hasBudgetLine(ver.data?.schema_json, values) && (
        <LinkedDocuments requestId={data.id} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        {isEditable && draft && (
          <Button variant="outline" onClick={persistDraft} disabled={saving}>
            {t('requests.new.saveDraft')}
          </Button>
        )}
        {/* Отправку выполняет эндпоинт САМОЙ заявки (он проверяет форму и
            ссылки на бюджет), а кнопка — общая с договорами: она знает, что
            показать в каждом состоянии согласования. */}
        {isInitiator && (
          <SubmitForApproval
            subjectType={REQUEST_SUBJECT_TYPE}
            subjectId={data.id}
            state={data.approval_state}
            submit={async (id) => {
              if (draft) await persistDraft();
              return requestsApi.instances.submitRaw(id);
            }}
            invalidate={[QK.instance(instanceId), QK.inbox, QK.sent]}
            showProcessLink
            // Незаполненное обязательное поле гасит кнопку С ПРИЧИНОЙ:
            // иначе человек узнавал бы о нём из 422 после нажатия.
            blockedReason={blockedByRequired(ver.data?.schema_json, values)}
          />
        )}
      </div>

      <SubjectProcesses subjectType={REQUEST_SUBJECT_TYPE} subjectId={data.id} />
    </RequestsLayout>
  );
}
