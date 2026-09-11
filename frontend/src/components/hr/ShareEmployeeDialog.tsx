/**
 * ShareEmployeeDialog — создание share-link на конкретного сотрудника.
 *
 * Аналог ShareOrgDialog (см. соседний файл), но публикует POST с
 * ``target_type='employee'``. Поддерживает два режима получателя:
 *  - публичная ссылка   — для внешних адресатов (без логина)
 *  - внутренняя ссылка  — копирует прямой URL /hr/employees/:id, который
 *                         сработает только для залогиненных сотрудников
 *
 * После создания публичная ссылка показывается ОДИН РАЗ — backend хранит
 * только SHA-256(token).
 */
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { createEmployeeShareLink, type EmployeeCard, type ShareLinkCreated } from '@/api/hr';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useTranslation } from 'react-i18next';
import { copyText } from '@/lib/clipboard';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface Props {
  open: boolean;
  employee: Pick<EmployeeCard, 'id' | 'full_name'> | null;
  onClose: () => void;
}

type ShareMode = 'internal' | 'public';

const TYPE_OPTIONS: Array<{ value: string; labelKey: string }> = [
  { value: 'one_time', labelKey: 'hr.share.kind.oneTime' },
  { value: 'time_limited', labelKey: 'hr.share.kind.timeLimited' },
  { value: 'permanent_with_expiry', labelKey: 'hr.share.kind.permanentWithExpiry' },
];

export function ShareEmployeeDialog({ open, employee, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [mode, setMode] = useState<ShareMode>('public');
  const [form, setForm] = useState({
    viewer_label: '',
    watermark_text: '',
    link_type: 'one_time',
    expires_at: '',
  });
  const [created, setCreated] = useState<ShareLinkCreated | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (open) {
      setMode('public');
      setForm({
        viewer_label: '',
        watermark_text: '',
        link_type: 'one_time',
        expires_at: '',
      });
      setCreated(null);
      setCopied(false);
    }
  }, [open]);

  const createM = useMutation({
    mutationFn: async () => {
      if (!employee) throw new Error('no_employee');
      return createEmployeeShareLink({
        employee_id: employee.id,
        label: employee.full_name || `Employee #${employee.id}`,
        viewer_label: form.viewer_label || null,
        watermark_text: form.watermark_text || null,
        link_type: form.link_type as 'one_time' | 'time_limited' | 'permanent_with_expiry',
        expires_at: form.expires_at || null,
      });
    },
    onSuccess: (link) => {
      setCreated(link);
      qc.invalidateQueries({ queryKey: ['hr-share-links'] });
    },
  });

  // Public URL — собираем от window.location, потому что backend в dev может
  // отдавать API-хост (см. ShareOrgDialog).
  const publicUrl =
    created && employee
      ? `${window.location.origin}/public/employee/${created.token}`
      : '';
  const internalUrl = employee
    ? `${window.location.origin}/hr/employees/${employee.id}`
    : '';

  const close = () => {
    setCreated(null);
    onClose();
  };

  const copy = async (url: string) => {
    if (!url) return;
    await copyText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] overflow-y-auto sm:max-h-[calc(100dvh-4rem)]">
        <DialogHeader>
          <DialogTitle>
            {employee?.full_name
              ? t('hr.share.cardTitleNamed', { name: employee.full_name })
              : t('hr.share.cardTitle')}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 text-sm">
          <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-1">
            <button
              type="button"
              onClick={() => setMode('public')}
              className={`rounded px-2 py-1.5 text-xs font-medium transition ${
                mode === 'public'
                  ? 'bg-primary text-primary-foreground shadow'
                  : 'text-muted-foreground hover:bg-background'
              }`}
            >
              {t('hr.share.publicLink')}
            </button>
            <button
              type="button"
              onClick={() => setMode('internal')}
              className={`rounded px-2 py-1.5 text-xs font-medium transition ${
                mode === 'internal'
                  ? 'bg-primary text-primary-foreground shadow'
                  : 'text-muted-foreground hover:bg-background'
              }`}
            >
              {t('hr.share.staffOnly')}
            </button>
          </div>

          {mode === 'internal' ? (
            <div className="grid gap-3">
              <p className="text-muted-foreground">
                {t('hr.share.staffOnlyHint')}
              </p>
              <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs break-all">
                {internalUrl}
              </div>
              <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button variant="outline" onClick={() => copy(internalUrl)}>
                  {copied ? t('hr.share.copied') : t('hr.share.copy')}
                </Button>
                <Button onClick={close}>{t('common.done')}</Button>
              </div>
            </div>
          ) : !created ? (
            <>
              <label className="grid gap-1.5">
                {t('hr.share.watermarkName')}
                <Input
                  value={form.viewer_label}
                  onChange={(e) => setForm({ ...form, viewer_label: e.target.value })}
                  placeholder={t('hr.share.watermarkPlaceholder')}
                  maxLength={64}
                />
                <span className="text-xs text-muted-foreground">
                  {t('hr.share.watermarkHintCard')}
                </span>
              </label>
              <label className="grid gap-1.5">
                {t('hr.share.watermarkExtra')}
                <Input
                  value={form.watermark_text}
                  onChange={(e) => setForm({ ...form, watermark_text: e.target.value })}
                  placeholder="CONFIDENTIAL"
                  maxLength={128}
                />
              </label>
              <label className="grid gap-1.5">
                {t('hr.share.linkType')}
                <Select
                  value={form.link_type}
                  onValueChange={(v) => setForm({ ...form, link_type: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TYPE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {t(o.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              {form.link_type !== 'one_time' && (
                <label className="grid gap-1.5">
                  {t('hr.share.expiresAt')}
                  <Input
                    type="datetime-local"
                    value={form.expires_at}
                    onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                  />
                </label>
              )}
              <p className="text-xs text-muted-foreground">
                {t('hr.share.publicHint')}
              </p>
              <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button variant="outline" onClick={close}>
                  {t('common.cancel')}
                </Button>
                <Button
                  onClick={() => createM.mutate()}
                  disabled={createM.isPending || !employee}
                >
                  {createM.isPending ? t('hr.share.creating') : t('hr.share.create')}
                </Button>
              </div>
              {createM.isError && (
                <p className="text-xs text-destructive">
                  {t('hr.share.createError')}
                </p>
              )}
            </>
          ) : (
            <div className="grid gap-3">
              <p className="text-muted-foreground">
                {t('hr.share.copyNowHint')}
              </p>
              <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs break-all">
                {publicUrl}
              </div>
              {created.expires_at && (
                <p className="text-xs text-muted-foreground">
                  {t('hr.share.expiresAtValue', { stamp: new Date(created.expires_at).toLocaleString(i18n.language) })}
                </p>
              )}
              <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button variant="outline" onClick={() => copy(publicUrl)}>
                  {copied ? t('hr.share.copied') : t('hr.share.copy')}
                </Button>
                <Button onClick={close}>{t('common.done')}</Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
