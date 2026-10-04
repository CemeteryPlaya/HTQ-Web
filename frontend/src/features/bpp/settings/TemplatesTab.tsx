/**
 * Вкладка «Шаблоны выписок» экрана «Настройки» (ТЗ §18, A3.1): список
 * шаблонов, создание и правка в `TemplateEditor`, архив и возврат из архива.
 *
 * Архив шаблона, по которому разбирается действующий счёт, сервер
 * отвергает (409 `E-STATE-01`) — сначала счёт переводят на другой шаблон.
 */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { useIdempotentAction } from '../core/useIdempotentAction';

import { bankSettingsApi, TEMPLATES_KEY, type StatementTemplate } from './api';
import { TemplateEditor } from './TemplateEditor';
import { FORMAT_LABELS } from './templateFields';

function ArchiveToggle({ template, onChanged }: { template: StatementTemplate; onChanged: () => void }) {
  const { t } = useTranslation();
  const toggle = useIdempotentAction((key) => bankSettingsApi.updateTemplate(template.id, key, {
    version: template.version, is_active: !template.is_active,
  }));
  const run = () => {
    toggle.run().then(onChanged, (error: unknown) =>
      reportApiError(error, t('bpp.bankSettings.templateToggleFailed', 'Не удалось изменить шаблон')));
  };
  return (
    <Button size="sm" variant="ghost" disabled={toggle.pending} onClick={run}>
      {template.is_active
        ? t('bpp.bankSettings.archive', 'В архив')
        : t('bpp.bankSettings.restore', 'Вернуть из архива')}
    </Button>
  );
}

interface Props {
  canEdit: boolean;
}

export function TemplatesTab({ canEdit }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: TEMPLATES_KEY,
    queryFn: () => bankSettingsApi.templates(),
  });
  // `undefined` — редактор закрыт, `null` — новый шаблон.
  const [editing, setEditing] = useState<StatementTemplate | null | undefined>(undefined);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'bank'] });
  };

  if (editing !== undefined) {
    return (
      <TemplateEditor
        key={editing?.id ?? 'new'}
        template={editing}
        canEdit={canEdit}
        onSaved={(saved) => { refresh(); setEditing(saved); }}
        onClose={() => setEditing(undefined)}
      />
    );
  }

  const templates = data ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {t('bpp.bankSettings.templatesHint', 'Шаблон говорит, как читать выписку банк-клиента: формат файла и в каких колонках дата, номер, сумма и назначение платежа.')}
        </p>
        {canEdit && (
          <Button size="sm" onClick={() => setEditing(null)}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('bpp.bankSettings.createTemplate', 'Создать шаблон')}
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : isError ? (
        <p className="rounded-lg border p-6 text-center text-sm text-destructive">
          {t('bpp.bankSettings.loadError', 'Не удалось загрузить справочник. Обновите страницу.')}
        </p>
      ) : templates.length === 0 ? (
        <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          {canEdit
            ? t('bpp.bankSettings.noTemplates', 'Шаблонов выписок пока нет — создайте первый, чтобы завести счёт организации.')
            : t('bpp.bankSettings.noTemplatesReadOnly', 'Шаблонов выписок пока нет. Их заводит администратор модуля.')}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.bankSettings.name', 'Название')}</TableHead>
                <TableHead>{t('bpp.bankSettings.format', 'Формат файла')}</TableHead>
                <TableHead>{t('bpp.bankSettings.activeAccounts', 'Счетов')}</TableHead>
                <TableHead />
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {templates.map((template) => (
                <TableRow key={template.id} className={template.is_active ? undefined : 'opacity-60'}>
                  <TableCell className="font-medium">{template.name}</TableCell>
                  <TableCell>{t(FORMAT_LABELS[template.format][0], FORMAT_LABELS[template.format][1])}</TableCell>
                  <TableCell className="tabular-nums">{template.active_accounts}</TableCell>
                  <TableCell>
                    {!template.is_active && (
                      <Badge variant="outline">{t('bpp.bankSettings.archived', 'Архив')}</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(template)}>
                        {canEdit ? t('bpp.bankSettings.edit', 'Изменить') : t('bpp.bankSettings.open', 'Открыть')}
                      </Button>
                      {canEdit && <ArchiveToggle template={template} onChanged={refresh} />}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default TemplatesTab;
