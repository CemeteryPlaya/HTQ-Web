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
import { CalendarPlus, Check, Copy, Link2, Loader2, Send, Trash2, X } from 'lucide-react';

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
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const [allowGuests, setAllowGuests] = useState(true);
  // По умолчанию — язык самого организатора: он создаёт ссылку у себя в
  // интерфейсе и рабочий сценарий — «позвать таких же коллег», не «иностранцев».
  // Явный выбор ниже — это и есть ответ на «если это иностранцы, нам нужен
  // английский»: организатор решает осознанно, а не потому что так вышло.
  const [locale, setLocale] = useState<'ru' | 'en'>(
    () => (i18n.language?.startsWith('en') ? 'en' : 'ru'));
  const [copied, setCopied] = useState<string | null>(null);
  // Адреса храним списком, а не одной строкой: человек видит, что именно уже
  // добавлено, и может убрать один адрес, не перебирая строку целиком.
  const [emailList, setEmailList] = useState<string[]>([]);
  const [emailInput, setEmailInput] = useState('');
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
    mutationFn: () => createInvite({
      room_id: roomId, title: title.trim(), allow_guests: allowGuests, locale,
    }),
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

  const parsedEmails = emailList;

  /** Добавить набранный адрес. Возвращает false, если добавлять нечего. */
  const commitEmail = (raw: string): boolean => {
    // Разделители принимаем те же, что и раньше: человек вполне может
    // вставить сразу список из письма, и он не обязан знать про Enter.
    const parts = raw.split(/[\s,;]+/).map((v) => v.trim()).filter(Boolean);
    const valid = parts.filter((v) => v.includes('@'));
    if (valid.length === 0) return false;
    setEmailList((prev) => Array.from(new Set([...prev, ...valid])));
    return true;
  };

  const removeEmail = (value: string) =>
    setEmailList((prev) => prev.filter((item) => item !== value));

  const send = useMutation({
    mutationFn: () => sendInvite(sendTarget!.id, {
      emails: parsedEmails, user_ids: staffIds,
    }),
    onSuccess: (result) => {
      const parts = [];
      if (result.emails_sent) parts.push(t('conference.invite.sentEmails', { count: result.emails_sent }));
      if (result.notified) parts.push(t('conference.invite.sentMessenger', { count: result.notified }));
      toast.success(t('conference.invite.sentToast', { details: parts.join(', ') }));
      // Отказ одного канала не отменяет другой — показываем оба исхода.
      result.errors.forEach((err) => toast.error(err));
      setEmailList([]);
      setEmailInput('');
    },
    onError: () => toast.error(t('conference.invite.sendError', 'Не удалось отправить')),
  });

  const schedule = useMutation({
    mutationFn: () => {
      const start = new Date(startAt);
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      return createCalendarEvent({
        title: title.trim() || t('conference.join.defaultTitle'),
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
      {/* Базовый DialogContent уже адаптивен по ширине ниже sm (calc(100vw-1.5rem)),
          но наш собственный `sm:max-w-lg` фиксировал ширину в 512px начиная
          с 640px — в том числе на альбомном телефоне (~740px), где половина
          экрана простаивала. `max-w-none sm:max-w-none` снимает ограничение
          до планшетного `md` (768px), а `md:max-w-lg` возвращает прежний вид
          на настоящих десктопах — там ничего не меняется. */}
      <DialogContent className="max-w-none sm:max-w-none md:max-w-lg">
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

        {/* min-w-0 — не косметика: DialogContent сам `display: grid`, а его
            прямой ребёнок по умолчанию имеет `min-width: auto` и отказывается
            сжиматься уже ЗДЕСЬ уже раньше явной ширины диалога, если где-то
            внутри есть `truncate`/`nowrap`-текст (например, полная ссылка-
            приглашение ниже) — сам truncate обрезает только то, что видно,
            а не то, что участвует в подсчёте intrinsic-ширины. Без этого
            класса диалог получал собственный горизонтальный скролл ровно
            под шириной самой длинной нигде не переносимой строки. */}
        <div className="min-w-0 space-y-4">
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

          <div className="flex items-center justify-between gap-3 rounded-xl border p-3 text-sm">
            <span>
              <span className="font-medium">
                {t('conference.invite.languageLabel', 'Язык интерфейса для гостя')}
              </span>
              <span className="block text-xs text-muted-foreground">
                {t('conference.invite.languageHint',
                  'На этом языке увидит платформу тот, кто откроет ссылку.')}
              </span>
            </span>
            <div className="flex shrink-0 items-center gap-1 rounded-md border bg-background p-0.5">
              {(['ru', 'en'] as const).map((code) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setLocale(code)}
                  aria-pressed={locale === code}
                  className={`h-7 rounded px-2 text-xs font-medium transition ${
                    locale === code
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted'
                  }`}
                >
                  {code.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

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

              {/* Первая строка — внешние адреса: набрал и нажал Enter. */}
              <div className="space-y-2">
                <Input
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter' && e.key !== ',' && e.key !== ';') return;
                    // Enter внутри диалога иначе отправит форму целиком.
                    e.preventDefault();
                    if (commitEmail(emailInput)) setEmailInput('');
                  }}
                  // Потерять набранное при уходе фокусом обиднее, чем добавить
                  // лишний адрес, который видно и можно убрать одним кликом.
                  onBlur={() => { if (commitEmail(emailInput)) setEmailInput(''); }}
                  placeholder={t('conference.invite.emailAdd', 'Почта внешнего участника — Enter, чтобы добавить')}
                />
                {emailList.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {emailList.map((value) => (
                      <span
                        key={value}
                        className="inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2.5 py-1 text-xs"
                      >
                        {value}
                        <button
                          type="button"
                          onClick={() => removeEmail(value)}
                          className="text-muted-foreground hover:text-destructive"
                          aria-label={t('conference.invite.emailRemove', 'Убрать адрес')}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Вторая строка — сотрудники компании: имя, логин или почта. */}
              <div className="space-y-2">
                <Input
                  value={staffQuery}
                  onChange={(e) => setStaffQuery(e.target.value)}
                  placeholder={t('conference.invite.staffSearch', 'Сотрудник — имя, логин или почта')}
                />
                {staffOptions.length > 0 && (
                  <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border p-2">
                    {staffOptions.slice(0, 20).map((option) => (
                      <label
                        key={option.id}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-0.5 text-sm hover:bg-accent/50"
                      >
                        <input
                          type="checkbox"
                          checked={staffIds.includes(option.id)}
                          onChange={() => toggleStaff(option.id)}
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {option.full_name || option.username || option.email}
                        </span>
                        {/* Второй строкой — чем человек отличается от тёзки. */}
                        <span className="shrink-0 truncate text-xs text-muted-foreground">
                          {option.username && option.username !== option.full_name
                            ? option.username
                            : option.email}
                        </span>
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

              {/* Колонка на узких экранах, а не строка: у datetime-local
                  свой минимальный размер виджета, который браузер не сжимает
                  ниже — рядом с кнопкой это и был источник горизонтальной
                  прокрутки диалога. flex-col снимает конкуренцию за ширину,
                  sm:flex-row возвращает прежний вид на широких экранах. */}
              <div className="flex flex-col gap-2 border-t pt-3 sm:flex-row sm:items-center">
                <Input
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                  className="min-w-0 sm:flex-1"
                />
                <Button
                  variant="outline"
                  className="w-full rounded-xl sm:w-auto"
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
