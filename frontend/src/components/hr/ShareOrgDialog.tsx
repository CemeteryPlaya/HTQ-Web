/**
 * ShareOrgDialog — create a public share-link for the org chart from the
 * OrgChart page itself. Mirrors the dialog on /share-links but is pre-filled
 * with the chart's current language.
 *
 * Hits POST /hr/v1/share-links/ which returns the raw token + URL exactly
 * once. The URL is shown in a "copy now, can't retrieve again" panel.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTranslation } from 'react-i18next';
import { copyText } from '@/lib/clipboard';

interface CreatedLink {
  id: string;
  token: string;
  url: string;
  expires_at: string | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  defaultLanguage?: 'ru' | 'en';
}

const TYPE_OPTIONS: Array<{ value: string; labelKey: string }> = [
  { value: 'one_time', labelKey: 'hr.share.kind.oneTime' },
  { value: 'time_limited', labelKey: 'hr.share.kind.timeLimited' },
  { value: 'permanent_with_expiry', labelKey: 'hr.share.kind.permanentWithExpiry' },
];

export function ShareOrgDialog({ open, onClose, defaultLanguage = 'ru' }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    label: '',
    viewer_label: '',
    watermark_text: '',
    default_language: defaultLanguage,
    link_type: 'one_time',
    expires_at: '',
  });
  const [created, setCreated] = useState<CreatedLink | null>(null);
  const [copied, setCopied] = useState(false);

  // Reset form whenever the dialog re-opens; keep the chart's current language.
  useEffect(() => {
    if (open) {
      setForm({
        label: '',
        viewer_label: '',
        watermark_text: '',
        default_language: defaultLanguage,
        link_type: 'one_time',
        expires_at: '',
      });
      setCreated(null);
      setCopied(false);
    }
  }, [open, defaultLanguage]);

  const createM = useMutation({
    mutationFn: async (): Promise<CreatedLink> => {
      const res = await api.post('hr/v1/share-links/', {
        label: form.label || null,
        viewer_label: form.viewer_label || null,
        watermark_text: form.watermark_text || null,
        max_level: 10,
        default_language: form.default_language,
        link_type: form.link_type,
        expires_at: form.expires_at || null,
      });
      return res.data;
    },
    onSuccess: (link) => {
      setCreated(link);
      qc.invalidateQueries({ queryKey: ['hr-share-links'] });
    },
  });

  // Build the public URL from the *frontend* origin. The backend's `created.url`
  // is unreliable in dev because Vite proxies API calls with `changeOrigin:
  // true`, so request.url.netloc on the server is the API host (e.g.
  // 127.0.0.1:8006) — not the URL the user actually browses to.
  const shareUrl = created ? `${window.location.origin}/public/org/${created.token}` : '';

  const close = () => {
    setCreated(null);
    onClose();
  };

  const copy = async () => {
    if (!shareUrl) return;
    await copyText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] overflow-y-auto sm:max-h-[calc(100dvh-4rem)]">
        <DialogHeader>
          <DialogTitle>{t('hr.share.orgTitle')}</DialogTitle>
        </DialogHeader>

        {!created ? (
          <div className="grid gap-4 text-sm">
            <label className="grid gap-1.5">
              {t('hr.share.description')}
              <Input
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder={t('hr.share.descriptionPlaceholder')}
                maxLength={200}
              />
            </label>
            <label className="grid gap-1.5">
              {t('hr.share.watermarkName')}
              <Input
                value={form.viewer_label}
                onChange={(e) => setForm({ ...form, viewer_label: e.target.value })}
                placeholder={t('hr.share.watermarkPlaceholder')}
                maxLength={64}
              />
              <span className="text-xs text-muted-foreground">
                {t('hr.share.watermarkHintChart')}
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
              <Select value={form.link_type} onValueChange={(v) => setForm({ ...form, link_type: v })}>
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
            <label className="grid gap-1.5">
              {t('hr.share.primaryLanguage')}
              <Select
                value={form.default_language}
                onValueChange={(v) => setForm({ ...form, default_language: v as 'ru' | 'en' })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ru">{t('hr.share.russian')}</SelectItem>
                  <SelectItem value="en">English</SelectItem>
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
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button onClick={() => createM.mutate()} disabled={createM.isPending}>
                {createM.isPending ? t('hr.share.creatingEllipsis') : t('hr.share.create')}
              </Button>
            </div>
            {createM.isError && (
              <p className="text-xs text-destructive">{t('hr.share.createError')}</p>
            )}
          </div>
        ) : (
          <div className="grid gap-3 text-sm">
            <p className="text-muted-foreground">
              {t('hr.share.copyNowHint')}
            </p>
            <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs break-all">
              {shareUrl}
            </div>
            {created.expires_at && (
              <p className="text-xs text-muted-foreground">
                {t('hr.share.expiresAtValue', { stamp: new Date(created.expires_at).toLocaleString(i18n.language) })}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={copy}>
                {copied ? t('hr.share.copied') : t('hr.share.copy')}
              </Button>
              <Button onClick={close}>{t('common.done')}</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
