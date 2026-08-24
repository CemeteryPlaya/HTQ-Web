/**
 * Форматирование истории конференций.
 *
 * Вынесено из компонентов отдельным модулем не ради красоты: тайм-код
 * реплики — это то, по чему пользователь прыгает в видео, и ошибка в
 * пересчёте «миллисекунды ↔ секунды плеера» проявится не падением, а тихим
 * промахом на несколько секунд. Такое ловится тестом, а не глазами.
 */
import type { RecordingState } from '@/api/conference';
import i18next from '@/i18n';

export const formatDateTime = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('ru', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

/** Длительность встречи по-человечески: «1 ч 24 мин», «7 мин», «—». */
export const formatDuration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return i18next.t('conference.duration.seconds', { seconds: Math.max(0, Math.round(seconds)) });

  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return i18next.t('conference.duration.minutes', { minutes });
  return minutes === 0 ? i18next.t('conference.duration.hours', { hours }) : i18next.t('conference.duration.hoursMinutes', { hours, minutes });
};

/**
 * Тайм-код реплики: «07:12» или «1:07:12».
 *
 * Часы появляются только когда они есть — «00:07:12» на семиминутной отметке
 * читается хуже и занимает место в узкой колонке.
 */
export const formatTimecode = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
};

/** Позиция плеера (секунды) для реплики, начинающейся на `ms`. */
export const timecodeToSeconds = (ms: number): number => Math.max(0, ms / 1000);

/**
 * Какая реплика звучит в момент `currentTime` (секунды плеера).
 *
 * Возвращает индекс или -1. Ищем последнюю начавшуюся, а не «ту, в чей
 * интервал попали»: между репликами есть паузы, и в паузе подсветка должна
 * оставаться на последнем сказанном, а не гаснуть.
 */
export const activeSegmentIndex = (
  segments: ReadonlyArray<{ start_ms: number }>,
  currentTimeSec: number,
): number => {
  const nowMs = currentTimeSec * 1000;
  let result = -1;
  for (let index = 0; index < segments.length; index += 1) {
    if (segments[index].start_ms <= nowMs) result = index;
    else break; // сегменты отсортированы сервером по start_ms
  }
  return result;
};

export interface RecordingBadge {
  i18nKey: string;
  fallback: string;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
}

/** Подпись и вид значка состояния записи. */
export const recordingBadge = (state: RecordingState): RecordingBadge => {
  switch (state) {
    case 'ready':
      return {
        i18nKey: 'conference.history.stateReady',
        fallback: 'Запись готова',
        variant: 'default',
      };
    case 'recording':
      return {
        i18nKey: 'conference.history.stateRecording',
        fallback: 'Идёт запись',
        variant: 'destructive',
      };
    case 'processing':
      return {
        i18nKey: 'conference.history.stateProcessing',
        fallback: 'Обработка',
        variant: 'secondary',
      };
    case 'failed':
      return {
        i18nKey: 'conference.history.stateFailed',
        fallback: 'Ошибка записи',
        variant: 'destructive',
      };
    case 'purged':
      return {
        i18nKey: 'conference.history.statePurged',
        fallback: 'Удалена по сроку',
        variant: 'outline',
      };
    default:
      return {
        i18nKey: 'conference.history.stateNone',
        fallback: 'Без записи',
        variant: 'outline',
      };
  }
};

/**
 * Сколько дней осталось до удаления записи.
 *
 * Отрицательное значение возможно: уборщик ходит раз в сутки, и между
 * истечением срока и фактическим удалением запись ещё доступна.
 */
export const daysUntilExpiry = (expiresAtIso: string, now = new Date()): number => {
  const expires = new Date(expiresAtIso).getTime();
  if (Number.isNaN(expires)) return 0;
  return Math.ceil((expires - now.getTime()) / (24 * 60 * 60 * 1000));
};
