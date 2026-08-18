/**
 * Приглашения в видеоконференцию.
 *
 * Два маршрута из четырёх — публичные: по ссылке приходит человек без
 * учётки, и проверить его нечем, кроме токена в самом адресе. Поэтому здесь
 * используется голый `fetch`, а не общий `api`-клиент: тот подставляет
 * Authorization и на 401 уводит на страницу входа — ровно то, чего гостю
 * делать нельзя (его 401 означал бы «ссылка не работает», а не «залогинься»).
 */
import api from '@/api/client';
import { getAccessToken } from '@/lib/auth/profileStorage';

export interface ConferenceInvite {
  id: number;
  room_id: string;
  title: string;
  /** Адрес, собранный сервером — годится для писем. В браузере пользуйтесь
   *  `joinUrl()`: за прокси у бэкенда в `Host` может оказаться внутреннее
   *  имя контейнера, и такая ссылка не откроется ни у кого. */
  url: string;
  token: string;
  allow_guests: boolean;
  expires_at: string;
  revoked: boolean;
  max_uses: number;
  uses: number;
  created_at: string;
}

export interface InvitePublicInfo {
  title: string;
  allow_guests: boolean;
  expires_at: string;
  /** Приезжает только сотруднику: анонимному посетителю комнату не отдаём. */
  room_id: string | null;
}

export interface GuestTokenResponse {
  access_token: string;
  expires_in: number;
  room_id: string;
  display_name: string;
  title: string;
  conference: unknown;
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/').replace(/\/+$/, '');

/**
 * Ссылка-приглашение так, как её увидит человек.
 *
 * Собирается от origin текущей вкладки, а не от того, что вернул сервер:
 * браузер свой адрес знает точно, а бэкенд за прокси — нет. Именно из-за
 * этого первая версия отдавала `http://backend-web:8000/join/...` — имя
 * контейнера, которое не резолвится нигде, кроме docker-сети.
 */
export const joinUrl = (token: string): string =>
  `${window.location.origin}/join/${token}`;

export const createInvite = async (payload: {
  room_id: string;
  title?: string;
  allow_guests?: boolean;
  ttl_hours?: number | null;
  max_uses?: number;
}): Promise<ConferenceInvite> =>
  (await api.post<ConferenceInvite>('cms/v1/conference/invites', payload)).data;

export const listInvites = async (roomId: string): Promise<ConferenceInvite[]> =>
  (await api.get<ConferenceInvite[]>('cms/v1/conference/invites', {
    params: { room_id: roomId },
  })).data;

export const revokeInvite = async (id: number): Promise<void> => {
  await api.delete(`cms/v1/conference/invites/${id}`);
};

/**
 * Что за встреча по ссылке. Токен сотрудника прикладывается, если он есть, —
 * тогда сервер вернёт ещё и комнату, и человека можно отправить в звонок
 * сразу, не заставляя представляться.
 */
export const fetchInviteInfo = async (token: string): Promise<InvitePublicInfo> => {
  const access = getAccessToken();
  const res = await fetch(`${API_BASE}/cms/v1/conference/join/${encodeURIComponent(token)}`, {
    headers: access ? { Authorization: `Bearer ${access}` } : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail || 'Ссылка недействительна');
  }
  return res.json();
};

export const requestGuestToken = async (
  token: string, displayName: string,
): Promise<GuestTokenResponse> => {
  const res = await fetch(
    `${API_BASE}/cms/v1/conference/join/${encodeURIComponent(token)}/guest`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail || 'Не удалось войти по ссылке');
  }
  return res.json();
};

export interface InviteSendResult {
  emails_sent: number;
  notified: number;
  errors: string[];
}

/** Разослать ссылку: почтой на адреса и уведомлением сотрудникам. */
export const sendInvite = async (
  id: number, payload: { emails?: string[]; user_ids?: number[] },
): Promise<InviteSendResult> =>
  (await api.post<InviteSendResult>(`cms/v1/conference/invites/${id}/send`, payload)).data;

// ─── История встреч, записи и протокол (apps/conference) ────────────────────
// Отдельный домен от приглашений выше: те живут в cms (/api/cms/v1/), эти — в
// собственной аппке (/api/conference/v1/), которую можно выключить отдельно.

/** Состояния записи; `purged` — «была и удалена по сроку хранения». */
export type RecordingState =
  | 'none' | 'recording' | 'processing' | 'ready' | 'failed' | 'purged';

export type TranscriptState =
  | 'pending' | 'processing' | 'ready' | 'failed' | 'skipped';

export interface ConferenceSessionListItem {
  id: number;
  room_id: string;
  title: string;
  created_by_id: number | null;
  created_by_name: string;
  started_at: string;
  ended_at: string | null;
  duration_sec: number | null;
  peak_participants: number;
  recording_state: RecordingState;
  transcript_state: TranscriptState;
  expires_at: string;
  participant_count: number;
  has_recording: boolean;
}

export interface ConferenceParticipant {
  id: number;
  user_id: number | null;
  display_name: string;
  is_guest: boolean;
  joined_at: string;
  left_at: string | null;
  joined_offset_ms: number;
}

export interface ConferenceSessionDetail extends ConferenceSessionListItem {
  error: string;
  purged_at: string | null;
  participants: ConferenceParticipant[];
  /** Готово ли видео к показу. Считает сервер — правило одно на всех. */
  playable: boolean;
  /**
   * Подписанные (`?sig=&exp=`) ссылки, готовые для `<video src>` и `poster`.
   *
   * Именно ссылки, а не blob: `<video>` не умеет отправлять заголовок
   * Authorization, а скачивание файла целиком в память убило бы перемотку.
   * Права проверены сервером в момент выдачи этой карточки — тот же приём,
   * которым платформа отдаёт приватные картинки (STRUCTURE.md §7.1).
   */
  recording_url: string | null;
  download_url: string | null;
  poster_url: string | null;
}

export interface TranscriptSegment {
  id: number;
  participant_id: number | null;
  speaker_name: string;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number | null;
}

export interface ConferenceTranscript {
  session_id: number;
  state: TranscriptState;
  segments: TranscriptSegment[];
}

export interface ConferenceSessionsPage {
  items: ConferenceSessionListItem[];
  total: number;
  page: number;
  pages: number;
  limit: number;
  recorded_total: number;
  active_total: number;
}

/**
 * Страница истории.
 *
 * Конверт возвращается ЦЕЛИКОМ и это важно: `unwrapPaginatedEnvelope` в
 * api/client.ts разворачивает ответ в голый массив, когда ключей ровно
 * {items,total,page,pages,limit}. Здесь их семь — лишние `recorded_total`
 * и `active_total` и оставляют конверт нетронутым (тот же приём, что у
 * истории уведомлений с её `unread_total`).
 */
export const listSessions = async (params: {
  page?: number;
  limit?: number;
  q?: string;
  from?: string;
  to?: string;
  mine?: boolean;
} = {}): Promise<ConferenceSessionsPage> =>
  (await api.get<ConferenceSessionsPage>('conference/v1/sessions/', {
    params: {
      page: params.page ?? 1,
      limit: params.limit ?? 25,
      ...(params.q ? { q: params.q } : {}),
      ...(params.from ? { from: params.from } : {}),
      ...(params.to ? { to: params.to } : {}),
      ...(params.mine ? { mine: 1 } : {}),
    },
  })).data;

export const getSession = async (id: number): Promise<ConferenceSessionDetail> =>
  (await api.get<ConferenceSessionDetail>(`conference/v1/sessions/${id}`)).data;

export const getTranscript = async (id: number): Promise<ConferenceTranscript> =>
  (await api.get<ConferenceTranscript>(`conference/v1/sessions/${id}/transcript`)).data;

/**
 * Скачать протокол файлом.
 *
 * Здесь blob уместен — в отличие от видео: текст встречи весит килобайты,
 * перематывать его не нужно, а обычная ссылка не сработала бы, потому что
 * эндпоинт закрыт JWT. Тот же приём, что у выгрузки HR-документов.
 */
export const downloadTranscript = async (
  id: number, format: 'txt' | 'md', filename: string,
): Promise<void> => {
  const res = await api.get(`conference/v1/sessions/${id}/transcript`, {
    params: { format },
    responseType: 'blob',
  });
  const url = URL.createObjectURL(res.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};
