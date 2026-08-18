/**
 * Карточка прошедшей встречи — /conference/history/:sessionId.
 *
 * Здесь сходятся обе половины задачи: слева запись, справа протокол, и они
 * связаны тайм-кодами — клик по реплике перематывает видео, а идущее видео
 * подсвечивает текущую реплику. Смотреть часовую запись целиком никто не
 * будет; ценность в том, чтобы найти нужную минуту по тексту.
 *
 * Видео играет по подписанной ссылке из карточки (`recording_url`), а не
 * через blob: `<video>` не умеет отправлять Authorization, а скачивание
 * файла целиком в память отняло бы перемотку. См. api/conference.ts.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  AlertTriangle,
  ArrowLeft,
  Clock,
  Download,
  FileText,
  Loader2,
  Users,
  Video,
} from 'lucide-react';

import {
  downloadTranscript,
  getSession,
  getTranscript,
  type ConferenceSessionDetail as SessionDetail,
  type TranscriptSegment,
} from '@/api/conference';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import {
  activeSegmentIndex,
  daysUntilExpiry,
  formatDateTime,
  formatDuration,
  formatTimecode,
  recordingBadge,
  timecodeToSeconds,
} from '@/lib/conference/history';

const ConferenceSessionDetailPage: React.FC = () => {
  const { t } = useTranslation();
  const { sessionId } = useParams<{ sessionId: string }>();
  const id = Number(sessionId);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);

  const sessionQuery = useQuery({
    queryKey: ['conference-session', id],
    queryFn: () => getSession(id),
    enabled: Number.isFinite(id) && id > 0,
  });

  const transcriptQuery = useQuery({
    queryKey: ['conference-transcript', id],
    queryFn: () => getTranscript(id),
    enabled: Number.isFinite(id) && id > 0,
    // Пока идёт распознавание, дёргать сервер бессмысленно: реплики
    // появятся все разом, одной транзакцией в конце задачи.
    refetchInterval: (query) => (
      query.state.data?.state === 'processing'
        || query.state.data?.state === 'pending' ? 30_000 : false
    ),
  });

  const session = sessionQuery.data;
  const segments = useMemo(
    () => transcriptQuery.data?.segments ?? [],
    [transcriptQuery.data],
  );
  const activeIndex = useMemo(
    () => activeSegmentIndex(segments, currentTime),
    [segments, currentTime],
  );

  const seekTo = (segment: TranscriptSegment) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = timecodeToSeconds(segment.start_ms);
    void video.play().catch(() => {
      // Автовоспроизведение может быть запрещено политикой браузера —
      // перемотка при этом уже сработала, и это главное.
    });
  };

  const handleDownloadTranscript = async () => {
    if (!session) return;
    try {
      await downloadTranscript(session.id, 'md', `protocol-${session.id}.md`);
    } catch {
      toast.error(t('conference.detail.downloadError', 'Не удалось скачать протокол'));
    }
  };

  if (sessionQuery.isLoading) {
    return (
      <PageShell>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-6 aspect-video w-full rounded-lg" />
      </PageShell>
    );
  }

  if (sessionQuery.isError || !session) {
    return (
      <PageShell>
        <div className="rounded-lg border border-dashed p-12 text-center">
          <AlertTriangle className="mx-auto h-10 w-10 text-muted-foreground/50" />
          <p className="mt-4 text-muted-foreground">
            {t('conference.detail.notFound',
              'Встреча не найдена или у вас нет к ней доступа')}
          </p>
          <Button asChild variant="outline" className="mt-6">
            <Link to="/conference/history">
              {t('conference.detail.backToList', 'К списку встреч')}
            </Link>
          </Button>
        </div>
      </PageShell>
    );
  }

  const badge = recordingBadge(session.recording_state);
  const daysLeft = daysUntilExpiry(session.expires_at);

  return (
    <PageShell>
      <Button asChild variant="ghost" size="sm" className="mb-4 -ml-2">
        <Link to="/conference/history">
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t('conference.detail.backToList', 'К списку встреч')}
        </Link>
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
            {session.title || t('conference.history.untitled', 'Встреча без названия')}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {session.created_by_name || '—'} · {formatDateTime(session.started_at)}
          </p>
        </div>
        <Badge variant={badge.variant}>{t(badge.i18nKey, badge.fallback)}</Badge>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Clock className="h-4 w-4" />
          {formatDuration(session.duration_sec)}
        </span>
        <span className="flex items-center gap-1.5">
          <Users className="h-4 w-4" />
          {session.participants.length}
        </span>
      </div>

      <RecordingPane
        session={session}
        videoRef={videoRef}
        onTimeUpdate={setCurrentTime}
        daysLeft={daysLeft}
      />

      <ParticipantsList session={session} />

      <section className="mt-10">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-xl font-semibold">
            <FileText className="h-5 w-5" />
            {t('conference.detail.protocol', 'Протокол встречи')}
          </h2>
          {segments.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleDownloadTranscript}>
              <Download className="mr-1.5 h-4 w-4" />
              {t('conference.detail.downloadProtocol', 'Скачать протокол')}
            </Button>
          )}
        </div>

        <TranscriptPane
          state={transcriptQuery.data?.state}
          isLoading={transcriptQuery.isLoading}
          segments={segments}
          activeIndex={activeIndex}
          onSeek={seekTo}
          seekable={Boolean(session.recording_url)}
        />
      </section>
    </PageShell>
  );
};

const PageShell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="min-h-screen bg-background flex flex-col">
    <Header />
    <main className="flex-1 container mx-auto py-8 px-4 max-w-5xl animate-in fade-in duration-500">
      {children}
    </main>
    <Footer />
  </div>
);

const RecordingPane: React.FC<{
  session: SessionDetail;
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  onTimeUpdate: (seconds: number) => void;
  daysLeft: number;
}> = ({ session, videoRef, onTimeUpdate, daysLeft }) => {
  const { t } = useTranslation();

  if (session.recording_state === 'purged') {
    return (
      <Notice icon={<Video className="h-10 w-10 text-muted-foreground/50" />}>
        {t('conference.detail.purged',
          'Запись удалена по истечении срока хранения. Протокол встречи сохранён.')}
      </Notice>
    );
  }
  if (session.recording_state === 'processing') {
    return (
      <Notice icon={<Loader2 className="h-10 w-10 animate-spin text-muted-foreground/50" />}>
        {t('conference.detail.processing',
          'Запись обрабатывается. Обычно это занимает несколько минут после встречи.')}
      </Notice>
    );
  }
  if (session.recording_state === 'recording') {
    return (
      <Notice icon={<Video className="h-10 w-10 text-destructive/60" />}>
        {t('conference.detail.ongoing',
          'Встреча идёт прямо сейчас. Запись появится после её окончания.')}
      </Notice>
    );
  }
  if (session.recording_state === 'failed') {
    return (
      <Notice icon={<AlertTriangle className="h-10 w-10 text-destructive/60" />}>
        {t('conference.detail.failed',
          'Записать встречу не удалось. Протокол мог сохраниться — он ниже.')}
      </Notice>
    );
  }
  if (!session.recording_url) {
    return (
      <Notice icon={<Video className="h-10 w-10 text-muted-foreground/50" />}>
        {t('conference.detail.noRecording', 'Запись этой встречи не велась')}
      </Notice>
    );
  }

  return (
    <section className="mt-6">
      <video
        ref={videoRef}
        controls
        preload="metadata"
        poster={session.poster_url ?? undefined}
        src={session.recording_url}
        onTimeUpdate={(event) => onTimeUpdate(event.currentTarget.currentTime)}
        className="aspect-video w-full rounded-lg bg-black"
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {daysLeft > 0
            ? t('conference.detail.expiresIn', 'Запись будет удалена через {{days}} дн.')
              .replace('{{days}}', String(daysLeft))
            : t('conference.detail.expiresSoon', 'Срок хранения записи истёк')}
        </p>
        {session.download_url && (
          <Button asChild variant="outline" size="sm">
            {/* Обычная ссылка, а не blob: файл может весить гигабайты, и имя
                вложения задаёт само хранилище (ResponseContentDisposition). */}
            <a href={session.download_url}>
              <Download className="mr-1.5 h-4 w-4" />
              {t('conference.detail.downloadVideo', 'Скачать запись')}
            </a>
          </Button>
        )}
      </div>
    </section>
  );
};

const Notice: React.FC<{ icon: React.ReactNode; children: React.ReactNode }> = ({
  icon, children,
}) => (
  <div className="mt-6 rounded-lg border border-dashed p-12 text-center">
    <div className="mx-auto flex justify-center">{icon}</div>
    <p className="mt-4 text-muted-foreground">{children}</p>
  </div>
);

const ParticipantsList: React.FC<{ session: SessionDetail }> = ({ session }) => {
  const { t } = useTranslation();
  if (session.participants.length === 0) return null;

  return (
    <section className="mt-8">
      <h2 className="mb-3 text-lg font-semibold">
        {t('conference.detail.participants', 'Участники')}
      </h2>
      <ul className="flex flex-wrap gap-2">
        {session.participants.map((participant) => (
          <li key={participant.id}>
            <Badge variant={participant.is_guest ? 'outline' : 'secondary'}>
              {participant.display_name}
              {participant.is_guest
                && ` · ${t('conference.detail.guest', 'гость')}`}
            </Badge>
          </li>
        ))}
      </ul>
    </section>
  );
};

const TranscriptPane: React.FC<{
  state: string | undefined;
  isLoading: boolean;
  segments: TranscriptSegment[];
  activeIndex: number;
  onSeek: (segment: TranscriptSegment) => void;
  seekable: boolean;
}> = ({ state, isLoading, segments, activeIndex, onSeek, seekable }) => {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (segments.length === 0) {
    const message = state === 'processing' || state === 'pending'
      ? t('conference.detail.transcriptPending',
        'Речь распознаётся. Протокол появится, когда обработка закончится.')
      : state === 'failed'
        ? t('conference.detail.transcriptFailed', 'Распознать речь не удалось')
        : t('conference.detail.transcriptEmpty', 'Протокол пуст: речь не распознана');
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        {message}
      </div>
    );
  }

  return (
    <ol className="space-y-1">
      {segments.map((segment, index) => (
        <li key={segment.id}>
          <button
            type="button"
            disabled={!seekable}
            onClick={() => onSeek(segment)}
            className={cn(
              'flex w-full gap-3 rounded-md px-3 py-2 text-left transition-colors',
              seekable ? 'hover:bg-accent/50' : 'cursor-default',
              index === activeIndex && 'bg-accent',
            )}
          >
            <span className="shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
              {formatTimecode(segment.start_ms)}
            </span>
            <span className="min-w-0">
              <span className="mr-2 font-medium">{segment.speaker_name}:</span>
              <span className="text-muted-foreground">{segment.text}</span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
};

export default ConferenceSessionDetailPage;
