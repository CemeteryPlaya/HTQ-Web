/**
 * Панели «Сегодня» и «Идут сейчас» — общие для двух экранов.
 *
 * Оба списка нужны в двух местах: на странице входа в конференцию (человек
 * пришёл с намерением «мне на встречу») и на странице «Мои видеоконференции».
 * Раньше разметка жила только на второй, и перенос её копией означал бы две
 * версии одного списка, которые со временем разъезжаются, — поэтому она
 * вынесена сюда, а страницы передают только данные.
 *
 * Три состояния списка (загрузка, ошибка, пустота) различаются намеренно:
 * пустой список во время загрузки выглядел бы как утверждение «встреч нет»,
 * сделанное до того, как ответ пришёл.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { format } from 'date-fns';
import { CalendarClock, Clock, FileText, Radio, Users } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type {
  ConferenceSessionListItem,
  ConferenceTodayItem,
} from '@/api/conference';
import { formatDateTime, formatDuration, recordingBadge } from '@/lib/conference/history';

interface PanelState {
  loading: boolean;
  /** Запрос упал: сообщение о пустоте показывать нельзя — оно соврёт. */
  failed: boolean;
}

const Skeletons: React.FC<{ count: number; height: string }> = ({ count, height }) => (
  <div className="space-y-3">
    {Array.from({ length: count }).map((_, index) => (
      <Skeleton key={index} className={`${height} w-full rounded-lg`} />
    ))}
  </div>
);

const EmptyState: React.FC<{ icon: React.ReactNode; text: string }> = ({ icon, text }) => (
  <div className="rounded-lg border border-dashed p-12 text-center">
    <div className="mx-auto flex justify-center text-muted-foreground/50">{icon}</div>
    <p className="mt-4 text-muted-foreground">{text}</p>
  </div>
);

export const TodayRow: React.FC<{ item: ConferenceTodayItem }> = ({ item }) => {
  const { t } = useTranslation();
  // Раньше вход рисовался только для status === 'live' — у запланированной
  // встречи не было НИКАКОГО способа попасть в комнату, хотя комната у неё
  // уже есть (allocate_conference_room_id) и первый вошедший её и начинает.
  // Бейдж со статусом остаётся всегда — человек должен видеть, входит он в
  // идущий разговор или открывает пустую комнату, — а действие рядом с ним
  // теперь есть для каждого статуса. Для завершённой это НЕ комната (её там
  // больше нет), а карточка встречи в истории.
  const badgeVariant = item.status === 'finished'
    ? 'outline' as const
    : item.status === 'live'
      ? 'default' as const
      : 'secondary' as const;

  return (
    <li className="flex items-center justify-between gap-3 rounded-2xl border p-4">
      <div className="min-w-0">
        <p className="truncate font-medium">{item.title}</p>
        <p className="text-xs text-muted-foreground">
          {format(new Date(item.start_at), 'HH:mm')}
          {' — '}
          {format(new Date(item.end_at), 'HH:mm')}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={badgeVariant}>
          {t(`conference.overview.status.${item.status}`)}
        </Badge>
        {item.status === 'finished' ? (
          item.session_id != null && (
            <Button asChild size="sm" variant="outline">
              <Link to={`/conference/history/${item.session_id}`}>
                {t('conference.overview.openHistory', 'Открыть')}
              </Link>
            </Button>
          )
        ) : (
          <Button asChild size="sm">
            <Link to={`/room/${item.room_id}`}>
              {item.status === 'live'
                ? t('conference.overview.join', 'Войти')
                : t('conference.overview.start', 'Начать')}
            </Link>
          </Button>
        )}
      </div>
    </li>
  );
};

export const SessionRow: React.FC<{ session: ConferenceSessionListItem }> = ({ session }) => {
  const { t } = useTranslation();
  const badge = recordingBadge(session.recording_state);

  return (
    <li>
      <Link
        to={`/conference/history/${session.id}`}
        className="block rounded-lg border p-4 transition-colors hover:bg-accent/50"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate font-medium">
              {session.title
                || t('conference.history.untitled', 'Встреча без названия')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {session.created_by_name || '—'} · {formatDateTime(session.started_at)}
            </p>
          </div>
          <Badge variant={badge.variant}>{t(badge.i18nKey, badge.fallback)}</Badge>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Clock className="h-4 w-4" />
            {session.ended_at
              ? formatDuration(session.duration_sec)
              : t('conference.history.ongoing', 'Идёт сейчас')}
          </span>
          <span className="flex items-center gap-1.5">
            <Users className="h-4 w-4" />
            {session.participant_count}
          </span>
          {session.transcript_state === 'ready' && (
            <span className="flex items-center gap-1.5">
              <FileText className="h-4 w-4" />
              {t('conference.history.hasTranscript', 'Есть протокол')}
            </span>
          )}
        </div>
      </Link>
    </li>
  );
};

export const TodayPanel: React.FC<PanelState & { items: ConferenceTodayItem[] }> = ({
  items, loading, failed,
}) => {
  const { t } = useTranslation();
  if (loading) return <Skeletons count={3} height="h-16" />;
  if (items.length > 0) {
    return (
      <ul className="space-y-3">
        {items.map((item) => <TodayRow key={item.event_id} item={item} />)}
      </ul>
    );
  }
  if (failed) return null;
  return (
    <EmptyState
      icon={<CalendarClock className="h-10 w-10" />}
      text={t('conference.overview.emptyToday', 'Сегодня встреч нет')}
    />
  );
};

export const LivePanel: React.FC<PanelState & { items: ConferenceSessionListItem[] }> = ({
  items, loading, failed,
}) => {
  const { t } = useTranslation();
  if (loading) return <Skeletons count={3} height="h-24" />;
  if (items.length > 0) {
    return (
      <ul className="space-y-3">
        {items.map((session) => <SessionRow key={session.id} session={session} />)}
      </ul>
    );
  }
  if (failed) return null;
  return (
    <EmptyState
      icon={<Radio className="h-10 w-10" />}
      text={t('conference.overview.emptyLive', 'Сейчас никто не разговаривает')}
    />
  );
};
