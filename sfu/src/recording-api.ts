/**
 * Канал SFU → Django: что происходило в комнате.
 *
 * SFU — единственный, кто знает, когда звонок реально начался, кто вошёл и
 * когда все разошлись. Django эти факты принимает и хранит
 * (`/api/conference/v1/internal/*`, аппка `apps.conference`).
 *
 * **Связь односторонняя и НЕОБЯЗАТЕЛЬНАЯ.** До сих пор SFU не ходил в
 * бэкенд ни разу, и появление такой зависимости не должно означать, что
 * упавший Django ломает конференцию. Поэтому здесь каждый запрос:
 *
 * - имеет короткий таймаут (звонок не ждёт журнал);
 * - никогда не пробрасывает исключение наружу — вместо этого `null` и
 *   строка `FALLBACK` через общий примитив `fallback.ts`;
 * - помечен `expected: false`. Потерянная запись встречи — это не
 *   предусмотренная деградация, а поломка, которую обязано быть видно в
 *   `sfu_fallback_total` и в Loki.
 *
 * Аутентификация — общий секрет в заголовке, не JWT: у SFU нет
 * пользователя, от чьего имени ходить (см. докстринг
 * `apps/conference/services/internal_auth.py`).
 */

import { config } from './config.js';
import { fallback } from './fallback.js';

const TOKEN_HEADER = 'X-HTQ-Internal-Token';

export interface SessionHandle {
  sessionId: number;
  startedAtMs: number;
  recordingEnabled: boolean;
}

export interface ArtifactReport {
  kind: 'peer_audio' | 'peer_video';
  peer_id: string;
  rel_path: string;
  started_offset_ms: number;
  size: number;
}

/** Настроен ли канал вообще. Без него запись не имеет смысла. */
export function isConfigured(): boolean {
  return Boolean(
    config.recording.enabled
      && config.recording.backendUrl.trim()
      && config.recording.internalToken.trim()
  );
}

function endpoint(path: string): string {
  const base = config.recording.backendUrl.trim().replace(/\/+$/, '');
  return `${base}/api/conference/v1/${path.replace(/^\/+/, '')}`;
}

async function post<T>(path: string, body: unknown, site: string): Promise<T | null> {
  if (!isConfigured()) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.recording.backendTimeoutMs);

  try {
    const response = await fetch(endpoint(path), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        [TOKEN_HEADER]: config.recording.internalToken,
      },
      body: JSON.stringify(body ?? {}),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      return fallback(site, null, {
        reason: 'бэкенд отказал в приёме события конференции',
        context: { path, status: response.status, body: text.slice(0, 300) },
      });
    }
    return (await response.json()) as T;
  } catch (cause) {
    return fallback(site, null, {
      reason: 'бэкенд недоступен, событие конференции потеряно',
      cause,
      context: { path },
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Открыть (или получить уже открытую) сессию комнаты.
 *
 * Зовётся на КАЖДОМ входе, а не только на первом: SFU мог перезапуститься
 * посреди звонка и не помнить, рассказывал ли он уже об этой встрече.
 * Django на своей стороне идемпотентен.
 */
export async function startSession(params: {
  roomId: string;
  createdById?: number | null;
  createdByName?: string;
}): Promise<SessionHandle | null> {
  const data = await post<{
    session_id: number;
    started_at: string;
    recording_enabled: boolean;
  }>(
    'internal/sessions',
    {
      room_id: params.roomId,
      created_by_id: params.createdById ?? null,
      created_by_name: params.createdByName ?? '',
    },
    'sfu.recording.session_start_failed'
  );

  if (!data) return null;
  return {
    sessionId: data.session_id,
    startedAtMs: Date.parse(data.started_at) || Date.now(),
    recordingEnabled: Boolean(data.recording_enabled),
  };
}

export async function reportParticipant(
  sessionId: number,
  params: {
    peerId: string;
    displayName: string;
    userId?: number | null;
    isGuest: boolean;
    action: 'join' | 'leave';
  }
): Promise<void> {
  await post(
    `internal/sessions/${sessionId}/participants`,
    {
      peer_id: params.peerId,
      display_name: params.displayName,
      user_id: params.userId ?? null,
      is_guest: params.isGuest,
      action: params.action,
    },
    'sfu.recording.participant_report_failed'
  );
}

export async function reportEvent(
  sessionId: number,
  params: { kind: string; peerId?: string; atMs?: number; payload?: unknown }
): Promise<void> {
  await post(
    `internal/sessions/${sessionId}/events`,
    {
      kind: params.kind,
      peer_id: params.peerId ?? null,
      at_ms: params.atMs ?? null,
      payload: params.payload ?? null,
    },
    'sfu.recording.event_report_failed'
  );
}

/**
 * Сообщить о дописанных дорожках.
 *
 * Отдельно от `finishSession`, потому что дорожка закрывается, когда
 * участник выключил камеру или вышел, — задолго до конца встречи. Рассказать
 * о ней сразу надёжнее: если SFU потом упадёт, до сборки доживёт всё, о чём
 * он успел сообщить.
 */
export async function reportArtifacts(
  sessionId: number,
  artifacts: ArtifactReport[]
): Promise<void> {
  if (artifacts.length === 0) return;
  await post(
    `internal/sessions/${sessionId}/artifacts`,
    { artifacts },
    'sfu.recording.artifacts_report_failed'
  );
}

export async function finishSession(
  sessionId: number,
  artifacts: ArtifactReport[] = []
): Promise<void> {
  await post(
    `internal/sessions/${sessionId}/finish`,
    { artifacts },
    'sfu.recording.session_finish_failed'
  );
}
