import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';

interface ShareLink {
  id: string;
  label: string | null;
  viewer_label: string | null;
  watermark_text: string | null;
  max_level: number;
  link_type: string;
  expires_at: string | null;
  opened_at: string | null;
  used_at: string | null;
  revoked_at: string | null;
  is_active: boolean;
  created_at: string;
}

interface CreatedLink extends ShareLink {
  token: string;
  url: string;
}

interface AuditEntry {
  id: number;
  action: string;
  occurred_at: string;
  ip: string | null;
  user_agent: string | null;
  reason: string | null;
}

const TYPE_LABELS: Record<string, string> = {
  one_time: 'Одноразовая',
  time_limited: 'По времени',
  permanent_with_expiry: 'Постоянная с датой',
};

const ACTION_LABELS: Record<string, string> = {
  created: 'Создана',
  open: 'Открыта',
  denied_revoked: 'Отказ: отозвана',
  denied_expired: 'Отказ: истекла',
  denied_used: 'Отказ: уже использована',
  revoked: 'Отозвана',
};

function statusLabel(link: ShareLink): { text: string; tone: 'default' | 'secondary' | 'destructive' } {
  if (link.revoked_at) return { text: 'Отозвана', tone: 'destructive' };
  if (link.used_at) return { text: 'Использована', tone: 'secondary' };
  if (link.expires_at && new Date(link.expires_at) < new Date()) return { text: 'Истекла', tone: 'secondary' };
  if (!link.is_active) return { text: 'Неактивна', tone: 'secondary' };
  return { text: link.opened_at ? 'Открывалась' : 'Активна', tone: 'default' };
}

function CreatedDialog({ created, onClose }: { created: CreatedLink; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  // Build the URL from the frontend's own origin. The server's `created.url`
  // is unreliable when API and frontend live on different hosts (Vite dev
  // proxy rewrites Host to the API host).
  const shareUrl = `${window.location.origin}/public/org/${created.token}`;
  const copy = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ссылка создана</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            Скопируйте ссылку сейчас — она показывается только один раз. После закрытия окна
            восстановить её будет нельзя.
          </p>
          <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs break-all">
            {shareUrl}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={copy}>{copied ? 'Скопировано' : 'Копировать'}</Button>
            <Button onClick={onClose}>Готово</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AuditDialog({ linkId, onClose }: { linkId: string; onClose: () => void }) {
  const { data = [], isLoading } = useQuery<AuditEntry[]>({
    queryKey: ['hr-share-link-audit', linkId],
    queryFn: async () => (await api.get(`hr/v1/share-links/${linkId}/audit`)).data,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Журнал ссылки</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Загрузка…</p>
        ) : data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Записей нет.</p>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {data.map((e) => (
              <div key={e.id} className="rounded-md border px-3 py-2 text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="font-medium">{ACTION_LABELS[e.action] ?? e.action}</span>
                  <span className="text-muted-foreground">{new Date(e.occurred_at).toLocaleString('ru')}</span>
                </div>
                {e.ip && <div className="font-mono text-muted-foreground">IP: {e.ip}</div>}
                {e.user_agent && <div className="text-muted-foreground truncate" title={e.user_agent}>UA: {e.user_agent}</div>}
                {e.reason && <div className="text-muted-foreground">{e.reason}</div>}
              </div>
            ))}
          </div>
        )}
        <div className="flex justify-end pt-2">
          <Button variant="outline" onClick={onClose}>Закрыть</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LinkRow({ link, onRevoke, onAudit }: { link: ShareLink; onRevoke: () => void; onAudit: () => void }) {
  const status = statusLabel(link);
  const inactive = !link.is_active;
  return (
    <div className={`rounded-xl border bg-card px-4 py-3 ${inactive ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-start gap-2 justify-between">
        <div className="min-w-0">
          <p className="font-medium text-sm truncate">{link.label || '(без названия)'}</p>
          {link.viewer_label && (
            <p className="text-xs text-muted-foreground mt-0.5">Получатель: {link.viewer_label}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Badge variant="outline" className="text-xs">{TYPE_LABELS[link.link_type] ?? link.link_type}</Badge>
          <Badge variant={status.tone} className="text-xs">{status.text}</Badge>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-xs text-muted-foreground">
        <span>Уровней: до {link.max_level}</span>
        {link.expires_at && <span>Истекает: {new Date(link.expires_at).toLocaleString('ru')}</span>}
        {link.opened_at && <span>Первое открытие: {new Date(link.opened_at).toLocaleString('ru')}</span>}
        {link.revoked_at && <span>Отозвана: {new Date(link.revoked_at).toLocaleString('ru')}</span>}
        <span>Создана: {new Date(link.created_at).toLocaleDateString('ru')}</span>
      </div>
      <div className="flex gap-2 mt-3">
        <Button size="sm" variant="outline" onClick={onAudit}>Журнал</Button>
        {link.is_active && (
          <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={onRevoke}>
            Отозвать
          </Button>
        )}
      </div>
    </div>
  );
}

const HRShareLinks = () => {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [createdLink, setCreatedLink] = useState<CreatedLink | null>(null);
  const [auditLinkId, setAuditLinkId] = useState<string | null>(null);
  const [form, setForm] = useState({
    label: '',
    viewer_label: '',
    watermark_text: '',
    max_level: '10',
    link_type: 'one_time',
    expires_at: '',
  });

  const { data: links = [], isLoading } = useQuery<ShareLink[]>({
    queryKey: ['hr-share-links'],
    queryFn: async () => (await api.get('hr/v1/share-links/')).data,
  });

  const createMutation = useMutation({
    mutationFn: async (): Promise<CreatedLink> => {
      const res = await api.post('hr/v1/share-links/', {
        label: form.label || null,
        viewer_label: form.viewer_label || null,
        watermark_text: form.watermark_text || null,
        max_level: parseInt(form.max_level),
        link_type: form.link_type,
        expires_at: form.expires_at || null,
      });
      return res.data;
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['hr-share-links'] });
      setCreateOpen(false);
      setCreatedLink(created);
      setForm({ label: '', viewer_label: '', watermark_text: '', max_level: '10', link_type: 'one_time', expires_at: '' });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`hr/v1/share-links/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-share-links'] }),
  });

  const activeLinks = links.filter((l) => l.is_active);
  const usedLinks = links.filter((l) => !l.is_active);

  return (
    <HRLayout title="Общий доступ" subtitle="Безопасные ссылки на структуру компании для внешних пользователей">
      <div className="flex items-center justify-between mb-6">
        <p className="text-sm text-muted-foreground">Активных: {activeLinks.length}</p>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>+ Создать ссылку</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Новая ссылка доступа</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                Описание (для кого)
                <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Например: Заказчик ООО Ромашка" />
              </label>
              <label className="grid gap-2 text-sm">
                Имя получателя в водяном знаке
                <Input
                  value={form.viewer_label}
                  onChange={(e) => setForm({ ...form, viewer_label: e.target.value })}
                  placeholder="ТОО Заказчик"
                  maxLength={64}
                />
                <span className="text-xs text-muted-foreground">Покажется поверх схемы при открытии — для отслеживания утечек.</span>
              </label>
              <label className="grid gap-2 text-sm">
                Дополнительный текст знака (опц.)
                <Input
                  value={form.watermark_text}
                  onChange={(e) => setForm({ ...form, watermark_text: e.target.value })}
                  placeholder="CONFIDENTIAL"
                  maxLength={128}
                />
              </label>
              <label className="grid gap-2 text-sm">
                Максимальный уровень (1–10)
                <Input type="number" min={1} max={10} value={form.max_level} onChange={(e) => setForm({ ...form, max_level: e.target.value })} />
                <span className="text-xs text-muted-foreground">Заказчик увидит структуру до этого уровня включительно</span>
              </label>
              <label className="grid gap-2 text-sm">
                Тип ссылки
                <Select value={form.link_type} onValueChange={(v) => setForm({ ...form, link_type: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="one_time">Одноразовая (инвалидируется после открытия)</SelectItem>
                    <SelectItem value="time_limited">По времени (только с датой истечения)</SelectItem>
                    <SelectItem value="permanent_with_expiry">Постоянная с датой истечения</SelectItem>
                  </SelectContent>
                </Select>
              </label>
              {form.link_type !== 'one_time' && (
                <label className="grid gap-2 text-sm">
                  Дата истечения
                  <Input type="datetime-local" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
                </label>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setCreateOpen(false)}>Отмена</Button>
                <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
                  {createMutation.isPending ? 'Создание…' : 'Создать'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground text-center py-12">Загрузка…</div>
      ) : (
        <div className="space-y-6">
          {activeLinks.length > 0 && (
            <section>
              <h3 className="text-sm font-medium text-muted-foreground mb-3">Активные</h3>
              <div className="space-y-3">
                {activeLinks.map((l) => (
                  <LinkRow
                    key={l.id}
                    link={l}
                    onRevoke={() => revokeMutation.mutate(l.id)}
                    onAudit={() => setAuditLinkId(l.id)}
                  />
                ))}
              </div>
            </section>
          )}
          {usedLinks.length > 0 && (
            <section>
              <h3 className="text-sm font-medium text-muted-foreground mb-3">История</h3>
              <div className="space-y-3">
                {usedLinks.map((l) => (
                  <LinkRow
                    key={l.id}
                    link={l}
                    onRevoke={() => {}}
                    onAudit={() => setAuditLinkId(l.id)}
                  />
                ))}
              </div>
            </section>
          )}
          {links.length === 0 && (
            <div className="text-center py-16 text-muted-foreground text-sm">
              Ссылок ещё нет. Создайте первую.
            </div>
          )}
        </div>
      )}

      {createdLink && <CreatedDialog created={createdLink} onClose={() => setCreatedLink(null)} />}
      {auditLinkId && <AuditDialog linkId={auditLinkId} onClose={() => setAuditLinkId(null)} />}
    </HRLayout>
  );
};

export default HRShareLinks;
