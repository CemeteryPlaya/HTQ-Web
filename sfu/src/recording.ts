/**
 * Запись конференции: mediasoup → RTP → ffmpeg → файл.
 *
 * Как это устроено и почему именно так.
 *
 * На каждого producer'а (аудио и видео каждого участника) вешается
 * `PlainTransport` — тот же Router, но вместо WebRTC на выходе обычный
 * RTP на localhost. Его слушает ffmpeg, запущенный дочерним процессом с
 * `-c copy`: он не декодирует и не кодирует, а просто перекладывает пакеты в
 * контейнер. Поэтому живая запись стоит почти ничего по CPU — а тяжёлое
 * (сведение в одно видео, распознавание речи) делает потом Django-воркер.
 *
 * **Почему по дорожке на участника, а не общий микс.** Из этого решения
 * бесплатно следует протокол встречи: аудио каждого человека лежит
 * отдельным файлом, и вопрос «кто это говорит» не нужно решать вовсе —
 * ответ известен из имени файла. Диаризация, самая хрупкая часть любой
 * системы расшифровки, в такой схеме просто не возникает.
 *
 * **Почему `.mkv`, а не `.webm`.** Комната поддерживает VP8 И H264
 * (media-codecs.config.json), а `-c copy` в webm принимает только
 * VP8/VP9/Opus. Matroska принимает всё три. С webm половина записей
 * оказалась бы битой — и молча, потому что ffmpeg ругается уже после того,
 * как встреча закончилась.
 *
 * Всё здесь best-effort: ни одна ошибка записи не должна ронять звонок.
 * Провалы уходят в `fallback()` с `expected: false` — потерянная запись
 * обязана быть видна в метриках, а не только в логе.
 */

import { spawn, type ChildProcess } from 'child_process';
import { mkdirSync, statSync, writeFileSync } from 'fs';
import { join } from 'path';
import { types as mediasoupTypes } from 'mediasoup';

import { config } from './config.js';
import { fallback } from './fallback.js';
import * as api from './recording-api.js';
import type { Room } from './room.js';

/** Адрес, на который PlainTransport шлёт RTP: ffmpeg живёт в том же контейнере. */
const RTP_HOST = '127.0.0.1';

interface TrackRecorder {
  peerId: string;
  kind: 'audio' | 'video';
  transport: mediasoupTypes.PlainTransport;
  consumer: mediasoupTypes.Consumer;
  process: ChildProcess;
  relPath: string;
  absPath: string;
  startedOffsetMs: number;
  ports: number[];
  closed: boolean;
}

interface SessionRecorder {
  roomId: string;
  sessionId: number;
  startedAtMs: number;
  dir: string;
  tracks: Map<string, TrackRecorder>;
  /** Дорожки, уже закрытые и отправленные бэкенду — для финального отчёта. */
  finished: api.ArtifactReport[];
}

const sessions = new Map<string, SessionRecorder>();

// ── Пул UDP-портов ─────────────────────────────────────────────────────────
// Порты выдаются парами (RTP + RTCP) и возвращаются при закрытии дорожки.
// Без пула два одновременных ffmpeg'а сели бы на один порт, и один из них
// молча получил бы чужие пакеты.

const takenPorts = new Set<number>();

/**
 * Пул портов. Экспортируется объектом, а не тремя функциями, чтобы у теста
 * был `reset()` — состояние здесь модульное и между проверками его надо
 * обнулять.
 */
export const ports = {
  /** Пара (RTP, RTCP) или null, если свободных не осталось. */
  take(): [number, number] | null {
    const { rtpPortMin, rtpPortMax } = config.recording;
    // Шаг 2 и чётное начало: RTCP по конвенции идёт на RTP+1.
    for (let port = rtpPortMin + (rtpPortMin % 2); port + 1 <= rtpPortMax; port += 2) {
      if (!takenPorts.has(port) && !takenPorts.has(port + 1)) {
        takenPorts.add(port);
        takenPorts.add(port + 1);
        return [port, port + 1];
      }
    }
    return null;
  },

  release(released: readonly number[]): void {
    for (const port of released) takenPorts.delete(port);
  },

  reset(): void {
    takenPorts.clear();
  },
};

// ── Генерация SDP ──────────────────────────────────────────────────────────

/**
 * SDP-файл, по которому ffmpeg понимает, что за поток к нему приедет.
 *
 * Вынесено отдельной чистой функцией: это единственная часть записи, которую
 * можно проверить тестом без mediasoup, ffmpeg и сети.
 */
export function buildSdp(params: {
  kind: 'audio' | 'video';
  rtpParameters: mediasoupTypes.RtpParameters;
  port: number;
  rtcpPort: number;
}): string {
  const codec = params.rtpParameters.codecs[0];
  if (!codec) throw new Error('rtpParameters без кодека');

  const encoding = params.rtpParameters.encodings?.[0];
  const ssrc = encoding?.ssrc;
  // mimeType вида 'audio/opus' → 'opus'; ffmpeg ждёт голое имя кодека.
  const codecName = codec.mimeType.split('/')[1];
  const media = params.kind === 'audio' ? 'audio' : 'video';
  const channels = params.kind === 'audio' ? `/${codec.channels ?? 2}` : '';

  const lines = [
    'v=0',
    `o=- 0 0 IN IP4 ${RTP_HOST}`,
    's=HTQWeb conference recording',
    `c=IN IP4 ${RTP_HOST}`,
    't=0 0',
    `m=${media} ${params.port} RTP/AVP ${codec.payloadType}`,
    `a=rtcp:${params.rtcpPort}`,
    `a=rtpmap:${codec.payloadType} ${codecName}/${codec.clockRate}${channels}`,
  ];

  const fmtp = Object.entries(codec.parameters ?? {})
    .map(([key, value]) => `${key}=${value}`)
    .join(';');
  if (fmtp) lines.push(`a=fmtp:${codec.payloadType} ${fmtp}`);
  if (ssrc !== undefined) lines.push(`a=ssrc:${ssrc} cname:htqweb-recorder`);
  lines.push('a=recvonly');

  return `${lines.join('\n')}\n`;
}

// ── Жизненный цикл сессии ──────────────────────────────────────────────────

/**
 * Открыть сессию записи для комнаты (идемпотентно).
 *
 * Возвращает `null`, если запись не настроена или бэкенд недоступен: в этом
 * случае звонок продолжается как раньше, просто без журнала.
 */
export async function ensureSession(params: {
  roomId: string;
  createdById?: number | null;
  createdByName?: string;
}): Promise<SessionRecorder | null> {
  const existing = sessions.get(params.roomId);
  if (existing) return existing;
  if (!api.isConfigured()) return null;

  const handle = await api.startSession(params);
  if (!handle) return null;

  // Гонка: пока мы ходили в Django, соседний вход мог завести сессию.
  const raced = sessions.get(params.roomId);
  if (raced) return raced;

  const dir = join(config.recording.rawDir, String(handle.sessionId));
  try {
    mkdirSync(dir, { recursive: true });
  } catch (cause) {
    return fallback('sfu.recording.raw_dir_unwritable', null, {
      reason: 'каталог для дорожек не создан, запись невозможна',
      cause,
      context: { dir },
    });
  }

  const session: SessionRecorder = {
    roomId: params.roomId,
    sessionId: handle.sessionId,
    startedAtMs: handle.startedAtMs,
    dir,
    tracks: new Map(),
    finished: [],
  };
  sessions.set(params.roomId, session);
  return handle.recordingEnabled ? session : null;
}

export function getSession(roomId: string): SessionRecorder | undefined {
  return sessions.get(roomId);
}

export async function reportParticipant(
  roomId: string,
  params: {
    peerId: string;
    displayName: string;
    userId?: number | null;
    isGuest: boolean;
    action: 'join' | 'leave';
  }
): Promise<void> {
  const session = sessions.get(roomId);
  if (!session) return;
  await api.reportParticipant(session.sessionId, params);
}

export async function reportEvent(
  roomId: string,
  params: { kind: string; peerId?: string; payload?: unknown }
): Promise<void> {
  const session = sessions.get(roomId);
  if (!session) return;
  await api.reportEvent(session.sessionId, {
    ...params,
    atMs: Math.max(0, Date.now() - session.startedAtMs),
  });
}

// ── Захват одной дорожки ───────────────────────────────────────────────────

/**
 * Начать писать producer'а участника.
 *
 * Порядок операций важен: consumer создаётся ПРИОСТАНОВЛЕННЫМ и
 * возобновляется последним, уже после того как ffmpeg поднялся и слушает
 * порт. Иначе первые пакеты уходят в никуда, и запись начинается с
 * повреждённого куска.
 */
export async function attachProducer(
  room: Room,
  peerId: string,
  producer: mediasoupTypes.Producer
): Promise<void> {
  const session = sessions.get(room.id);
  if (!session) return;

  const key = producer.id;
  if (session.tracks.has(key)) return;

  const pair = ports.take();
  if (!pair) {
    fallback('sfu.recording.no_free_rtp_ports', null, {
      reason: 'кончились UDP-порты под запись, дорожка не пишется',
      context: { room: room.id, peerId, kind: producer.kind },
    });
    return;
  }
  const [rtpPort, rtcpPort] = pair;

  let transport: mediasoupTypes.PlainTransport | null = null;
  let consumer: mediasoupTypes.Consumer | null = null;

  try {
    transport = await room.router.createPlainTransport({
      listenIp: { ip: RTP_HOST },
      // rtcpMux=false — ffmpeg ждёт RTCP отдельным портом; comedia=false —
      // адрес получателя мы знаем сами и не выясняем его по входящим
      // пакетам (ffmpeg ничего нам не шлёт, так что выяснять было бы нечем).
      rtcpMux: false,
      comedia: false,
    });
    await transport.connect({ ip: RTP_HOST, port: rtpPort, rtcpPort });

    consumer = await transport.consume({
      producerId: producer.id,
      rtpCapabilities: room.router.rtpCapabilities,
      paused: true,
    });

    const kind = consumer.kind as 'audio' | 'video';
    const relPath = `${kind}-${peerId}-${producer.id}.mkv`;
    const absPath = join(session.dir, relPath);
    const sdpPath = join(session.dir, `${relPath}.sdp`);

    writeFileSync(
      sdpPath,
      buildSdp({ kind, rtpParameters: consumer.rtpParameters, port: rtpPort, rtcpPort }),
      'utf-8'
    );

    const child = spawn(
      config.recording.ffmpegPath,
      [
        '-hide_banner',
        '-loglevel', 'warning',
        '-protocol_whitelist', 'file,udp,rtp',
        // Буфер приёма: без запаса ffmpeg теряет пакеты на всплесках
        // битрейта (кто-то включил демонстрацию экрана).
        '-buffer_size', '2097152',
        '-i', sdpPath,
        '-c', 'copy',
        '-f', 'matroska',
        absPath,
      ],
      { stdio: ['pipe', 'ignore', 'pipe'] }
    );

    child.stderr?.on('data', (chunk: Buffer) => {
      const text = chunk.toString().trim();
      if (text) console.warn(`[recording ${session.sessionId}] ffmpeg: ${text}`);
    });
    child.on('error', (cause) => {
      fallback('sfu.recording.ffmpeg_spawn_failed', null, {
        reason: 'ffmpeg не запустился, дорожка не пишется',
        cause,
        context: { room: room.id, peerId, kind },
      });
    });

    const startedOffsetMs = Math.max(0, Date.now() - session.startedAtMs);
    const track: TrackRecorder = {
      peerId, kind, transport, consumer, process: child,
      relPath, absPath, startedOffsetMs, ports: pair, closed: false,
    };
    session.tracks.set(key, track);

    // Producer закрылся (выключили камеру, вышли) — дописываем файл.
    producer.observer.once('close', () => {
      void detachProducer(room.id, producer.id);
    });

    await consumer.resume();
  } catch (cause) {
    ports.release(pair);
    try { consumer?.close(); } catch { /* уже закрыт */ }
    try { transport?.close(); } catch { /* уже закрыт */ }
    fallback('sfu.recording.attach_failed', null, {
      reason: 'дорожку участника не удалось поставить на запись',
      cause,
      context: { room: room.id, peerId, kind: producer.kind },
    });
  }
}

/** Корректно дописать файл: ffmpeg должен закрыть контейнер сам. */
function stopFfmpeg(track: TrackRecorder): Promise<void> {
  return new Promise((resolve) => {
    const child = track.process;
    if (child.exitCode !== null || child.signalCode !== null) return resolve();

    // Убить SIGKILL'ом нельзя: Matroska без финального заголовка не
    // открывается. 'q' в stdin — штатная просьба ffmpeg завершиться;
    // SIGTERM — то же самое сигналом. SIGKILL остаётся крайней мерой по
    // таймауту, чтобы зависший процесс не держал сессию вечно.
    const done = () => resolve();
    child.once('close', done);

    try {
      child.stdin?.write('q');
      child.stdin?.end();
    } catch {
      /* stdin уже закрыт — ниже придёт SIGTERM */
    }
    setTimeout(() => { try { child.kill('SIGTERM'); } catch { /* ушёл */ } }, 500);
    setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* ушёл */ } }, 5000);
    setTimeout(done, 6000);
  });
}

export async function detachProducer(roomId: string, producerId: string): Promise<void> {
  const session = sessions.get(roomId);
  if (!session) return;
  const track = session.tracks.get(producerId);
  if (!track || track.closed) return;

  track.closed = true;
  session.tracks.delete(producerId);

  try { track.consumer.close(); } catch { /* уже закрыт */ }
  try { track.transport.close(); } catch { /* уже закрыт */ }
  await stopFfmpeg(track);
  ports.release(track.ports);

  let size = 0;
  try {
    size = statSync(track.absPath).size;
  } catch {
    // Файла нет — ffmpeg не успел ничего написать. Сообщать о пустой
    // дорожке нечего, сборщику она только помешает.
    return;
  }
  if (size === 0) return;

  const artifact: api.ArtifactReport = {
    kind: track.kind === 'audio' ? 'peer_audio' : 'peer_video',
    peer_id: track.peerId,
    rel_path: track.relPath,
    started_offset_ms: track.startedOffsetMs,
    size,
  };
  session.finished.push(artifact);
  await api.reportArtifacts(session.sessionId, [artifact]);
}

/**
 * Комната опустела: дописать всё и закрыть встречу.
 *
 * Полный список дорожек уходит повторно вместе с `finish` намеренно —
 * Django принимает его идемпотентно, а потерянный ответ на промежуточный
 * отчёт не должен стоить участнику места в записи.
 */
export async function closeSession(roomId: string): Promise<void> {
  const session = sessions.get(roomId);
  if (!session) return;

  // Сессию из карты убираем ПОСЛЕ дозакрытия дорожек: detachProducer ищет
  // её там же, и снятая раньше времени запись просто потерялась бы.
  for (const producerId of [...session.tracks.keys()]) {
    await detachProducer(roomId, producerId);
  }
  sessions.delete(roomId);

  await api.finishSession(session.sessionId, session.finished);
}

/** Для тестов и аккуратного завершения процесса. */
export async function closeAll(): Promise<void> {
  for (const roomId of [...sessions.keys()]) {
    await closeSession(roomId);
  }
}
