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

const TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'one_time', label: 'Одноразовая (инвалидируется после открытия)' },
  { value: 'time_limited', label: 'По времени (только с датой истечения)' },
  { value: 'permanent_with_expiry', label: 'Постоянная с датой истечения' },
];

export function ShareOrgDialog({ open, onClose, defaultLanguage = 'ru' }: Props) {
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
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] overflow-y-auto sm:max-h-[calc(100dvh-4rem)]">
        <DialogHeader>
          <DialogTitle>Поделиться оргструктурой</DialogTitle>
        </DialogHeader>

        {!created ? (
          <div className="grid gap-4 text-sm">
            <label className="grid gap-1.5">
              Описание (для архива)
              <Input
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="Например: ТОО Заказчик"
                maxLength={200}
              />
            </label>
            <label className="grid gap-1.5">
              Имя получателя в водяном знаке
              <Input
                value={form.viewer_label}
                onChange={(e) => setForm({ ...form, viewer_label: e.target.value })}
                placeholder="ТОО Заказчик · 2026-05-04"
                maxLength={64}
              />
              <span className="text-xs text-muted-foreground">
                Покажется поверх схемы при открытии — для отслеживания утечек.
              </span>
            </label>
            <label className="grid gap-1.5">
              Дополнительный текст знака (опц.)
              <Input
                value={form.watermark_text}
                onChange={(e) => setForm({ ...form, watermark_text: e.target.value })}
                placeholder="CONFIDENTIAL"
                maxLength={128}
              />
            </label>
            <label className="grid gap-1.5">
              Тип ссылки
              <Select value={form.link_type} onValueChange={(v) => setForm({ ...form, link_type: v })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-1.5">
              Основной язык
              <Select
                value={form.default_language}
                onValueChange={(v) => setForm({ ...form, default_language: v as 'ru' | 'en' })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ru">Русский</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </label>
            {form.link_type !== 'one_time' && (
              <label className="grid gap-1.5">
                Дата истечения
                <Input
                  type="datetime-local"
                  value={form.expires_at}
                  onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                />
              </label>
            )}
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={close}>
                Отмена
              </Button>
              <Button onClick={() => createM.mutate()} disabled={createM.isPending}>
                {createM.isPending ? 'Создание…' : 'Создать ссылку'}
              </Button>
            </div>
            {createM.isError && (
              <p className="text-xs text-destructive">Не удалось создать ссылку. Попробуйте ещё раз.</p>
            )}
          </div>
        ) : (
          <div className="grid gap-3 text-sm">
            <p className="text-muted-foreground">
              Скопируйте ссылку сейчас — она показывается только один раз. После закрытия окна
              восстановить её будет нельзя.
            </p>
            <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs break-all">
              {shareUrl}
            </div>
            {created.expires_at && (
              <p className="text-xs text-muted-foreground">
                Истекает: {new Date(created.expires_at).toLocaleString('ru')}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={copy}>
                {copied ? 'Скопировано' : 'Копировать'}
              </Button>
              <Button onClick={close}>Готово</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
