/**
 * Конфигурация SFU-сервера
 * Загружает переменные окружения и предоставляет типизированный объект конфигурации.
 */

import { config as dotenvConfig } from 'dotenv';
import { cpus } from 'os';
import type { types as mediasoupTypes } from 'mediasoup';

dotenvConfig();

function envInt(key: string, fallback: number): number {
  const v = process.env[key];
  return v ? parseInt(v, 10) : fallback;
}

function envFloat(key: string, fallback: number): number {
  const v = process.env[key];
  return v ? parseFloat(v) : fallback;
}

function envStr(key: string, fallback: string): string {
  return process.env[key] ?? fallback;
}

function envBool(key: string, fallback: boolean): boolean {
  const raw = process.env[key];
  if (raw === undefined) return fallback;

  switch (raw.trim().toLowerCase()) {
    case '1':
    case 'true':
    case 'yes':
    case 'on':
      return true;
    case '0':
    case 'false':
    case 'no':
    case 'off':
      return false;
    default:
      return fallback;
  }
}

function resolveSfuHost(): string {
  const configuredHost = envStr('SFU_HOST', '0.0.0.0').trim();
  if (!configuredHost) {
    return '0.0.0.0';
  }

  const normalized = configuredHost.toLowerCase();
  if (normalized === 'localhost' || normalized === '127.0.0.1' || normalized === '::1') {
    console.warn(
      `[config] SFU_HOST=${configuredHost} — это loopback-адрес. ` +
        'Переопределяем на 0.0.0.0 для доступности в локальной сети.'
    );
    return '0.0.0.0';
  }

  return configuredHost;
}

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '/';
  return trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
}

function parseList(raw: string): string[] {
  return raw
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function parseAllowedOriginPatterns(): string[] {
  const raw = envStr(
    'SIGNALING_ALLOWED_ORIGINS',
    'https://*.instatunnel.my,http://*.instatunnel.my'
  );
  return parseList(raw);
}

function parseWsPaths(): string[] {
  const raw = envStr('SIGNALING_WS_PATHS', '/ws/sfu,/ws/sfu/');
  const normalized = new Set(parseList(raw).map(normalizePath));
  normalized.add('/ws/sfu');
  normalized.add('/ws/sfu/');
  return Array.from(normalized);
}

/**
 * Парсинг TURN URL-адресов.
 * Поддерживает:
 * - TURN_URLS=turn:global.turn.twilio.com:3478?transport=udp,turns:global.turn.twilio.com:443?transport=tcp
 * - TURN_URL=turn:your-project.metered.live:443?transport=tcp (устаревший формат с одним URL)
 */
function parseTurnUrls(): string[] {
  const urls = parseList(envStr('TURN_URLS', ''));
  const single = envStr('TURN_URL', '').trim();
  if (single) {
    urls.push(single);
  }
  return Array.from(new Set(urls));
}

function parseListenIpEntry(entry: string): mediasoupTypes.TransportListenIp {
  const trimmed = entry.trim();
  if (!trimmed) {
    return { ip: '0.0.0.0' };
  }

  // Формат с квадратными скобками для IPv6: "[::1]:203.0.113.10"
  const bracketMatch = trimmed.match(/^\[([^\]]+)\](?::(.+))?$/);
  if (bracketMatch) {
    return {
      ip: bracketMatch[1] || '::',
      announcedIp: bracketMatch[2] || undefined,
    };
  }

  // Предпочтительный формат для IPv6-безопасного парсинга: "listenIp|announcedIp"
  const pipeIndex = trimmed.indexOf('|');
  if (pipeIndex >= 0) {
    const ip = trimmed.slice(0, pipeIndex).trim();
    const announcedIp = trimmed.slice(pipeIndex + 1).trim();
    return {
      ip: ip || '0.0.0.0',
      announcedIp: announcedIp || undefined,
    };
  }

  // Устаревший формат IPv4: "listenIp:announcedIp"
  const parts = trimmed.split(':');
  if (parts.length === 2) {
    const [ip, announcedIp] = parts;
    return {
      ip: ip || '0.0.0.0',
      announcedIp: announcedIp || undefined,
    };
  }

  // IPv6 или обычный хост/IP без announcedIp.
  return {
    ip: trimmed,
  };
}

/**
 * Парсинг WEBRTC_LISTEN_IPS из переменных окружения.
 * Поддерживаемые форматы:
 * - WEBRTC_LISTEN_IP + WEBRTC_ANNOUNCED_IP
 * - WEBRTC_LISTEN_IPS="ip1:announcedIp1,ip2:announcedIp2" (устаревший IPv4)
 * - WEBRTC_LISTEN_IPS="ip1|announcedIp1,ip2|announcedIp2" (IPv6-безопасный)
 */
function parseListenIps(): mediasoupTypes.TransportListenIp[] {
  const explicitIp = envStr('WEBRTC_LISTEN_IP', '').trim();
  const explicitAnnouncedIp = envStr('WEBRTC_ANNOUNCED_IP', '').trim();
  if (explicitIp) {
    return [
      {
        ip: explicitIp,
        announcedIp: explicitAnnouncedIp || undefined,
      },
    ];
  }

  const raw = envStr('WEBRTC_LISTEN_IPS', '0.0.0.0');
  return parseList(raw).map((entry) => {
    const parsed = parseListenIpEntry(entry);
    if (!parsed.announcedIp && explicitAnnouncedIp) {
      return {
        ...parsed,
        announcedIp: explicitAnnouncedIp,
      };
    }
    return parsed;
  });
}

/**
 * Строгая валидация: если listenIp — это wildcard (0.0.0.0 / ::) и
 * announcedIp не указан, сервер НЕ СМОЖЕТ сформировать корректные SDP-кандидаты
 * для внешних клиентов — что приведёт к чёрному видео / отсутствию RTP.
 *
 * Выбрасываем фатальную ошибку, чтобы запуск упал явно, а не молча
 * создавал нерабочие соединения.
 */
function validateListenIps(
  listenIps: mediasoupTypes.TransportListenIp[]
): void {
  for (const entry of listenIps) {
    const ip = String(entry.ip || '').trim();
    const announcedIp = String(entry.announcedIp || '').trim();
    const isWildcard = ip === '0.0.0.0' || ip === '::';

    if (isWildcard && !announcedIp) {
      throw new Error(
        `[config] ФАТАЛЬНО: listenIp "${ip}" — это wildcard, но announcedIp не задан. ` +
        'Внешние клиенты получат SDP с "0.0.0.0" в качестве медиа-адреса, ' +
        'что приведёт к чёрному видео / отсутствию RTP. ' +
        'Исправление: установите WEBRTC_ANNOUNCED_IP=<ваш LAN или публичный IP> в sfu/.env и перезапустите.'
      );
    }
  }
}

function parseWebRtcTransportProtocols(
  tcpTunnelMode: boolean
): {
  enableUdp: boolean;
  enableTcp: boolean;
  preferUdp: boolean;
  preferTcp: boolean;
} {
  let enableUdp = envBool('WEBRTC_ENABLE_UDP', true);
  let enableTcp = envBool('WEBRTC_ENABLE_TCP', true);
  let preferUdp = envBool('WEBRTC_PREFER_UDP', false);
  let preferTcp = envBool('WEBRTC_PREFER_TCP', true);

  // TCP_TUNNEL_MODE: TCP-туннель не может пересылать UDP — принудительно только TCP.
  if (tcpTunnelMode) {
    enableUdp = false;
    enableTcp = true;
    preferUdp = false;
    preferTcp = true;
    console.warn(
      '[config] TCP_TUNNEL_MODE=true → UDP отключён, принудительно TCP-only. ' +
      'Это необходимо, т.к. туннель (например Bore) не поддерживает UDP.'
    );
  }

  // Защита от неправильной конфигурации — сервер должен быть доступен.
  if (!enableUdp && !enableTcp) {
    enableTcp = true;
    enableUdp = false;
  }

  return {
    enableUdp,
    enableTcp,
    preferUdp,
    preferTcp,
  };
}

function warnIfSuspiciousBitrate(
  key: string,
  value: number,
  minExpectedBps: number
): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(
      `[config] ФАТАЛЬНО: ${key} должен быть положительным целым числом (битрейт в bps), получено "${value}".`
    );
  }

  if (value < minExpectedBps) {
    const suggestedBps = value * 1000;
    console.warn(
      `[config] ${key}=${value} выглядит слишком низким для bps. ` +
        `mediasoup ожидает биты в секунду; если вы имели в виду kbps, используйте ${suggestedBps}.`
    );
  }
}

// Вычисляется один раз при загрузке модуля, чтобы все ссылки были согласованными.
const _tcpTunnelMode = envBool('TCP_TUNNEL_MODE', false);

export const config = {
  // ── Сервер ──
  port: envInt('SFU_PORT', 4443),
  // Безопасное значение для LAN (слушаем все IPv4-интерфейсы, не только loopback).
  host: resolveSfuHost(),

  // ── Режим TCP-туннеля ──
  // Когда включён:
  //   • UDP отключён (TCP-only туннель, например Bore)
  //   • WebRtcServer создаётся только с TCP listenInfo
  //   • announcedAddress устанавливается на публичный IP
  tcpTunnelMode: _tcpTunnelMode,

  // ── TLS ──
  tls: {
    cert: envStr('TLS_CERT', ''),
    key: envStr('TLS_KEY', ''),
  },

  // ── Mediasoup ──
  mediasoup: {
    numWorkers: envInt('MEDIASOUP_WORKERS', 0) || cpus().length,
    workerSettings: {
      logLevel: 'warn' as mediasoupTypes.WorkerLogLevel,
      logTags: [
        'info',
        'ice',
        'dtls',
        'rtp',
        'srtp',
        'rtcp',
        'rtx',
        'bwe',
        'score',
        'simulcast',
        'svc',
      ] as mediasoupTypes.WorkerLogTag[],
      // ПРИМЕЧАНИЕ: rtcMinPort/rtcMaxPort удалены — портами теперь управляет
      // единый WebRtcServer (WEBRTC_SERVER_PORT). Диапазон портов не нужен.
    },
    listenIps: parseListenIps(),
    webRtcServerPort: envInt('WEBRTC_SERVER_PORT', 44444),
    announcedPort: process.env.WEBRTC_ANNOUNCED_PORT ? envInt('WEBRTC_ANNOUNCED_PORT', 44444) : undefined,
    webRtcTransport: {
      ...parseWebRtcTransportProtocols(_tcpTunnelMode),
      initialAvailableOutgoingBitrate: envInt(
        'WEBRTC_INITIAL_AVAILABLE_OUTGOING_BITRATE',
        envInt('VIDEO_BITRATE_BPS', 1_500_000)
      ),
      maxIncomingBitrate: envInt(
        'WEBRTC_MAX_INCOMING_BITRATE',
        Math.floor(envInt('VIDEO_BITRATE_BPS', 1_500_000) * 1.25)
      ),
    },
  },

  // ── Целевой битрейт ──
  bitrate: {
    videoBps: envInt('VIDEO_BITRATE_BPS', 1_500_000),
    audioBps: envInt('AUDIO_BITRATE_BPS', 64_000),
  },

  // ── Переопределение BWE (оценки пропускной способности) ──
  bwe: {
    intervalMs: envInt('BWE_INTERVAL_MS', 50),
    safetyFactor: envFloat('BWE_SAFETY_FACTOR', 0.85),
    plrThreshold: envFloat('BWE_PLR_THRESHOLD', 0.03),
    degradedBitrateBps: envInt('BWE_DEGRADED_BITRATE_BPS', 8_000_000),
  },

  // ── TURN ──
  turn: {
    url: envStr('TURN_URL', ''),
    urls: parseTurnUrls(),
    username: envStr('TURN_USERNAME', ''),
    credential: envStr('TURN_CREDENTIAL', ''),
  },

  // ── Сигнализация ──
  signaling: {
    requireTls: envBool('SIGNALING_REQUIRE_TLS', true),
    wsPaths: parseWsPaths(),
    disableOriginCheck: envBool('SIGNALING_DISABLE_ORIGIN_CHECK', true),
    allowRequestsWithoutOrigin: envBool('SIGNALING_ALLOW_NO_ORIGIN', true),
    allowedOriginPatterns: parseAllowedOriginPatterns(),
  },
} as const;

// Валидация при загрузке модуля — убивает процесс до создания воркеров.
validateListenIps(config.mediasoup.listenIps);
warnIfSuspiciousBitrate(
  'WEBRTC_INITIAL_AVAILABLE_OUTGOING_BITRATE',
  config.mediasoup.webRtcTransport.initialAvailableOutgoingBitrate,
  100_000
);
warnIfSuspiciousBitrate(
  'WEBRTC_MAX_INCOMING_BITRATE',
  config.mediasoup.webRtcTransport.maxIncomingBitrate,
  100_000
);
warnIfSuspiciousBitrate('VIDEO_BITRATE_BPS', config.bitrate.videoBps, 100_000);
warnIfSuspiciousBitrate('AUDIO_BITRATE_BPS', config.bitrate.audioBps, 16_000);
warnIfSuspiciousBitrate(
  'BWE_DEGRADED_BITRATE_BPS',
  config.bwe.degradedBitrateBps,
  100_000
);
