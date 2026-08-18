/**
 * «Пригласить в конференцию» — ссылка вместо диктовки идентификатора.
 *
 * До этого позвать человека можно было только одним способом: скопировать
 * id комнаты и продиктовать. Для коллеги это терпимо, для внешнего
 * участника не работало вовсе — маршрут комнаты требует авторизации.
 *
 * Ссылка создаётся здесь же, потому что у неё есть свойства, которых у
 * голого адреса комнаты нет: срок, лимит входов, возможность отозвать и
 * решение «пускать ли посторонних». Последнее — главный переключатель
 * диалога: с ним ссылка пускает человека без учётки, без него ведёт в
 * комнату через обычный вход.
 */
import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CalendarPlus, Check, Copy, Link2, Loader2, Send, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  ConferenceInvite, createInvite, joinUrl, listInvites, revokeInvite, sendInvite,
} from '@/api/conference';
import { createCalendarEvent, fetchCalendarUserOptions } from '@/api/calendar';

interface Props {
  roomId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Локальное время в формате datetime-local, округлённое до ближайших 5 минут. */
const defaultStart = (): string => {
  const at = new Date(Date.now() + 15 * 60 * 1000);
  at.setMinutes(Math.ceil(at.getMinutes() / 5) * 5, 0, 0);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`
    + `T${pad(at.getHours())}:${pad(at.getMinutes())}`;
};

export const InviteDialog: React.FC<Props> = ({ roomId, open, onOpenChange }) => {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const [allowGuests, setAllowGuests] = useState(true);
  const [copied, setCopied] = useState<string | null>(null);
  const [emails, setEmails] = useState('');
  const [staffQuery, setStaffQuery] = useState('');
  const [staffIds, setStaffIds] = useState<number[]>([]);
  const [startAt, setStartAt] = useState(defaultStart);
  const [target, setTarget] = useState<ConferenceInvite | null>(null);

  const { data: invites = [], isLoading } = useQuery({
    queryKey: ['conference-invites', roomId],
    queryFn: () => listInvites(roomId),
    enabled: open && Boolean(roomId),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['conference-invites', roomId] });

  const create = useMutation({
    mutationFn: () => createInvite({ room_id: roomId, title: title.trim(), allow_guests: allowGuests }),
    onSuccess: async (invite) => {
      invalidate();
      setTarget(invite);
      await copy(joinUrl(invite.token));
      toast.success(t('conference.invite.created', 'Ссылка создана и скопирована'));
    },
    onError: () => toast.error(t('conference.invite.createError', 'Не удалось создать ссылку')),
  });

  const remove = useMutation({
    mutationFn: (id: number) => revokeInvite(id),
    onSuccess: () => {
      invalidate();
      toast.success(t('conference.invite.revoked', 'Ссылка отозвана'));
    },
  });

  // Кому отправлять — ссылка, только что созданная, либо первая живая:
  // отдельный выбор здесь был бы лишним шагом, а не свободой.
  const sendTarget = target ?? invites.find((invite) => !invite.revoked) ?? null;

  const { data: staffOptions = [] } = useQuery({
    queryKey: ['calendar-user-options', staffQuery],
    queryFn: () => fetchCalendarUserOptions(staffQuery),
    enabled: open,
  });

  const parsedEmails = emails
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter((value) => value.includes('@'));

  const send = useMutation({
    mutationFn: () => sendInvite(sendTarget!.id, {
      emails: parsedEmails, user_ids: staffIds,
    }),
    onSuccess: (result) => {
      const parts = [];
      if (result.emails_sent) parts.push(`письма: ${result.emails_sent}`);
      if (result.notified) parts.push(`в мессенджер: ${result.notified}`);
      toast.success(`Приглашение отправлено (${parts.join(', ')})`);
      // Отказ одного канала не отменяет другой — показываем оба исхода.
      result.errors.forEach((err) => toast.error(err));
      setEmails('');
    },
    onError: () => toast.error(t('conference.invite.sendError', 'Не удалось отправить')),
  });

  const schedule = useMutation({
    mutationFn: () => {
      const start = new Date(startAt);
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      return createCalendarEvent({
        title: title.trim() || 'Видеоконференция',
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        event_type: 'conference',
        // Именно этот идентификатор превращает событие в звонок: по нему
        // ConferenceNotifier за 5 минут напомнит участникам и уведёт в комнату.
        conference_room_id: roomId,
        participant_user_ids: staffIds,
      });
    },
    onSuccess: () => toast.success(
      t('conference.invite.scheduled', 'Встреча добавлена в календарь')),
    onError: () => toast.error(
      t('conference.invite.scheduleError', 'Не удалось создать встречу')),
  });

  const toggleStaff = (id: number) => setStaffIds(
    (prev) => (prev.includes(id) ? prev.filter((value) => value !== id) : [...prev, id]));

  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(url);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.error(t('conference.invite.copyError', 'Скопируйте ссылку вручную'));
    }
  };

  const live = invites.filter((invite) => !invite.revoked);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-5 w-5" />
            {t('conference.invite.title', 'Пригласить в конференцию')}
          </DialogTitle>
          <DialogDescription>
            {t('conference.invite.subtitle',
              'Ссылку можно отправить кому угодно. Её видно только тому, кому вы её дали, и её можно отозвать.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="invite-title">
              {t('conference.invite.nameLabel', 'Название встречи')}
            </label>
            <Input
              id="invite-title"
              value={title}
              maxLength={255}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('conference.invite.namePlaceholder', 'Например: приёмка объекта')}
            />
            <p className="text-xs text-muted-foreground">
              {t('conference.invite.nameHint',
                'Показывается тому, кто открыл ссылку, — чтобы он понимал, куда его позвали.')}
            </p>
          </div>

          <label className="flex items-start gap-3 rounded-xl border p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={allowGuests}
              onChange={(e) => setAllowGuests(e.target.checked)}
            />
            <span>
              <span className="font-medium">
                {t('conference.invite.allowGuests', 'Пускать без учётной записи')}
              </span>
              <span className="block text-xs text-muted-foreground">
                {t('conference.invite.allowGuestsHint',
                  'Внешний участник назовёт имя и войдёт. Выключите, если зовёте только сотрудников.')}
              </span>
            </span>
          </label>

          <Button
            className="w-full rounded-xl"
            onClick={() => create.mutate()}
            disabled={create.isPending || !roomId}
          >
            {create.isPending
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              : <Link2 className="mr-2 h-4 w-4" />}
            {t('conference.invite.create', 'Создать ссылку')}
          </Button>

          {isLoading && (
            <p className="text-sm text-muted-foreground">{t('common.loading', 'Загрузка…')}</p>
          )}

          {live.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                {t('conference.invite.active', 'Действующие ссылки')}
              </p>
              {live.map((invite) => (
                <div key={invite.id} className="flex items-center gap-2 rounded-xl border p-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-mono">{joinUrl(invite.token)}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {invite.allow_guests
                        ? t('conference.invite.badgeGuests', 'Для внешних участников')
                        : t('conference.invite.badgeStaff', 'Только для сотрудников')}
                      {' · '}
                      {t('conference.invite.uses', 'входов')}: {invite.uses}
                    </p>
                  </div>
                  <Button variant="ghost" size="icon" onClick={() => copy(joinUrl(invite.token))}
                          title={t('conference.invite.copy', 'Скопировать')}>
                    {copied === joinUrl(invite.token)
                      ? <Check className="h-4 w-4 text-emerald-500" />
                      : <Copy className="h-4 w-4" />}
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => remove.mutate(invite.id)}
                          title={t('conference.invite.revoke', 'Отозвать')}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {sendTarget && (
            <div className="space-y-3 rounded-xl border p-3">
              <p className="text-sm font-medium">
                {t('conference.invite.sendTitle', 'Отправить приглашение')}
              </p>

              <Input
                value={emails}
                onChange={(e) => setEmails(e.target.value)}
                placeholder={t('conference.invite.emails', 'Почта через запятую — для внешних участников')}
              />

              <div className="space-y-2">
                <Input
                  value={staffQuery}
                  onChange={(e) => setStaffQuery(e.target.value)}
                  placeholder={t('conference.invite.staffSearch', 'Поиск сотрудника')}
                />
                {staffOptions.length > 0 && (
                  <div className="max-h-32 space-y-1 overflow-y-auto rounded-lg border p-2">
                    {staffOptions.slice(0, 20).map((option) => (
                      <label key={option.id} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={staffIds.includes(option.id)}
                          onChange={() => toggleStaff(option.id)}
                        />
                        <span className="truncate">{option.full_name || option.email}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <Button
                className="w-full rounded-xl"
                variant="secondary"
                disabled={send.isPending || (parsedEmails.length === 0 && staffIds.length === 0)}
                onClick={() => send.mutate()}
              >
                {send.isPending
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <Send className="mr-2 h-4 w-4" />}
                {t('conference.invite.send', 'Отправить почтой и в мессенджер')}
              </Button>

              <div className="flex items-center gap-2 border-t pt-3">
                <Input
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                  className="flex-1"
                />
                <Button
                  variant="outline"
                  className="rounded-xl"
                  disabled={schedule.isPending}
                  onClick={() => schedule.mutate()}
                  title={t('conference.invite.scheduleHint',
                    'Создаст встречу в календаре: выбранным сотрудникам придёт напоминание за 5 минут.')}
                >
                  <CalendarPlus className="mr-2 h-4 w-4" />
                  {t('conference.invite.schedule', 'В календарь')}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
