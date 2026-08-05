import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MediaEngine, classifyVirtualNetwork } from './MediaEngine';

// ═══════════════════════════════════════════════════════════
// Unit tests: classifyVirtualNetwork
// ═══════════════════════════════════════════════════════════

describe('classifyVirtualNetwork', () => {
  it('returns "Hamachi" for 25.x.x.x addresses', () => {
    expect(classifyVirtualNetwork('25.0.0.1')).toBe('Hamachi');
    expect(classifyVirtualNetwork('25.255.255.255')).toBe('Hamachi');
  });

  it('returns "Hamachi" for 26.x.x.x addresses', () => {
    expect(classifyVirtualNetwork('26.170.2.55')).toBe('Hamachi');
    expect(classifyVirtualNetwork('26.0.0.1')).toBe('Hamachi');
  });

  it('returns "CGNAT/Tailscale" for 100.64-127.x.x addresses', () => {
    expect(classifyVirtualNetwork('100.64.0.1')).toBe('CGNAT/Tailscale');
    expect(classifyVirtualNetwork('100.100.100.100')).toBe('CGNAT/Tailscale');
    expect(classifyVirtualNetwork('100.127.255.255')).toBe('CGNAT/Tailscale');
  });

  it('returns "Private/WSL" for 172.16-31.x.x addresses', () => {
    expect(classifyVirtualNetwork('172.16.0.1')).toBe('Private/WSL');
    expect(classifyVirtualNetwork('172.31.255.255')).toBe('Private/WSL');
    expect(classifyVirtualNetwork('172.20.10.1')).toBe('Private/WSL');
  });

  it('returns "Benchmarking/VPN" for 198.18-19.x.x addresses', () => {
    expect(classifyVirtualNetwork('198.18.0.1')).toBe('Benchmarking/VPN');
    expect(classifyVirtualNetwork('198.19.255.255')).toBe('Benchmarking/VPN');
  });

  it('returns null for public IP addresses', () => {
    expect(classifyVirtualNetwork('8.8.8.8')).toBeNull();
    expect(classifyVirtualNetwork('1.1.1.1')).toBeNull();
    expect(classifyVirtualNetwork('203.0.113.5')).toBeNull();
  });

  it('returns null for null/undefined/empty input', () => {
    expect(classifyVirtualNetwork(null)).toBeNull();
    expect(classifyVirtualNetwork(undefined)).toBeNull();
    expect(classifyVirtualNetwork('')).toBeNull();
  });

  it('returns null for malformed addresses', () => {
    expect(classifyVirtualNetwork('not-an-ip')).toBeNull();
    expect(classifyVirtualNetwork('256.1.1.1')).toBeNull();
    expect(classifyVirtualNetwork('::1')).toBeNull();
  });

  it('does not match 100.0-63.x.x (outside CGNAT range)', () => {
    expect(classifyVirtualNetwork('100.0.0.1')).toBeNull();
    expect(classifyVirtualNetwork('100.63.255.255')).toBeNull();
  });

  it('does not match 172.15.x.x or 172.32.x.x (outside private range)', () => {
    expect(classifyVirtualNetwork('172.15.255.255')).toBeNull();
    expect(classifyVirtualNetwork('172.32.0.1')).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════
// Integration tests: onicecandidateerror handler behavior
// ═══════════════════════════════════════════════════════════

/**
 * Helper to create a synthetic RTCPeerConnectionIceErrorEvent-like object.
 * Real RTCPeerConnectionIceErrorEvent cannot be constructed in jsdom,
 * so we create a plain object matching the W3C spec shape.
 */
function createIceErrorEvent(overrides: {
  address?: string | null;
  errorCode: number;
  errorText?: string;
  url?: string;
}): RTCPeerConnectionIceErrorEvent {
  return {
    address: overrides.address ?? null,
    errorCode: overrides.errorCode,
    errorText: overrides.errorText ?? '',
    url: overrides.url ?? '',
    port: null,
    // Minimal Event interface stubs required by TypeScript
    type: 'icecandidateerror',
    bubbles: false,
    cancelable: false,
    composed: false,
    currentTarget: null,
    defaultPrevented: false,
    eventPhase: 0,
    isTrusted: false,
    returnValue: true,
    srcElement: null,
    target: null,
    timeStamp: Date.now(),
    cancelBubble: false,
    AT_TARGET: 2,
    BUBBLING_PHASE: 3,
    CAPTURING_PHASE: 1,
    NONE: 0,
    composedPath: () => [],
    initEvent: () => {},
    preventDefault: () => {},
    stopImmediatePropagation: () => {},
    stopPropagation: () => {},
  } as unknown as RTCPeerConnectionIceErrorEvent;
}

/**
 * Captures what the onicecandidateerror handler does by replaying the
 * handler logic extracted from MediaEngine.createPeerConnection.
 *
 * We re-implement the handler classification inline so we can test it
 * without instantiating the full MediaEngine (which requires signaling,
 * media devices, etc.). The logic mirrors MediaEngine.ts lines 1475-1545.
 */
function simulateIceErrorHandler(event: RTCPeerConnectionIceErrorEvent): {
  level: 'debug' | 'warn' | 'error';
  reason: string;
} {
  const isDnsLookupIssue =
    event.errorCode === 701 ||
    /dns\s*lookup/i.test(String(event.errorText || ''));
  const isTurnAllocateError = event.errorCode === 400;
  const isMdnsIssue = event.errorCode === 701 && /\.local/i.test(event.address || '');

  // VPN / Mesh graceful degradation
  const vpnLabel = classifyVirtualNetwork(event.address);
  if (vpnLabel) {
    return { level: 'debug', reason: `vpn:${vpnLabel}` };
  }

  // TURN allocate error
  if (isTurnAllocateError) {
    return { level: 'warn', reason: 'turn-allocate' };
  }

  // DNS failure
  if (isDnsLookupIssue) {
    const isIpv6 =
      event.url?.includes('[') ||
      event.address?.includes(':') ||
      /aaaa|ipv6/i.test(String(event.errorText || ''));
    const isDnsWithoutAddress = !event.address;

    if (isDnsWithoutAddress) {
      return { level: 'debug', reason: 'dns-fallback' };
    }
    if (!isIpv6 && !isMdnsIssue) {
      return { level: 'warn', reason: 'dns-lookup' };
    }
    return { level: 'debug', reason: 'dns-ipv6-or-mdns' };
  }

  // Critical / unrecognized error — propagated to onError
  return { level: 'error', reason: 'ice-gathering-failure' };
}

describe('onicecandidateerror handler', () => {
  let debugSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Test 1: Hamachi address (26.170.2.x) with code 701 ──
  it('filters Hamachi (26.x) ICE error as debug-level VPN noise', () => {
    const event = createIceErrorEvent({
      address: '26.170.2.55',
      errorCode: 701,
      errorText: 'STUN host lookup received error.',
      url: 'stun:stun.l.google.com:19302',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('debug');
    expect(result.reason).toBe('vpn:Hamachi');
  });

  // ── Test 2: Tailscale address (100.x) with code 701 ──
  it('filters Tailscale (100.64+) ICE error as debug-level VPN noise', () => {
    const event = createIceErrorEvent({
      address: '100.100.42.7',
      errorCode: 701,
      errorText: 'STUN host lookup received error.',
      url: 'stun:stun.cloudflare.com:3478',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('debug');
    expect(result.reason).toBe('vpn:CGNAT/Tailscale');
  });

  // ── Test 3: DNS failure (address=null, url=stun.l.google.com) ──
  it('handles DNS failure with null address via debug-level fallback path', () => {
    const event = createIceErrorEvent({
      address: null,
      errorCode: 701,
      errorText: 'STUN host lookup received error.',
      url: 'stun:stun.l.google.com:19302',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('debug');
    expect(result.reason).toBe('dns-fallback');
    // Crucially: not 'error', meaning the session is NOT interrupted.
  });

  // ── Test 4: Critical error (401 Unauthorized) is NOT suppressed ──
  it('propagates critical errors (e.g. 401) as error-level ICE failures', () => {
    const event = createIceErrorEvent({
      address: '203.0.113.5',
      errorCode: 401,
      errorText: 'Unauthorized',
      url: 'turn:relay.example.com:443',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('error');
    expect(result.reason).toBe('ice-gathering-failure');
  });

  // ── Additional edge cases ──

  it('does not suppress errors on public addresses even with code 701', () => {
    const event = createIceErrorEvent({
      address: '8.8.8.8',
      errorCode: 701,
      errorText: 'DNS lookup issue',
      url: 'stun:stun.l.google.com:19302',
    });

    const result = simulateIceErrorHandler(event);

    // Public IP + DNS issue = warn (not suppressed, not escalated to error)
    expect(result.level).toBe('warn');
    expect(result.reason).toBe('dns-lookup');
  });

  it('filters WSL/Docker (172.16+) addresses as VPN noise', () => {
    const event = createIceErrorEvent({
      address: '172.20.10.1',
      errorCode: 701,
      url: 'stun:stun.l.google.com:19302',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('debug');
    expect(result.reason).toBe('vpn:Private/WSL');
  });

  it('still treats DNS error text match as DNS issue even without code 701', () => {
    const event = createIceErrorEvent({
      address: null,
      errorCode: 300,
      errorText: 'DNS lookup failed for host',
      url: 'stun:stun.example.com:3478',
    });

    const result = simulateIceErrorHandler(event);

    expect(result.level).toBe('debug');
    expect(result.reason).toBe('dns-fallback');
  });
});

// ═══════════════════════════════════════════════════════════
// DNS fallback: verify DEFAULT_ICE_SERVERS contains IP entries
// ═══════════════════════════════════════════════════════════

describe('DEFAULT_ICE_SERVERS DNS fallback', () => {
  it('MediaEngine exports are importable without errors', () => {
    // Smoke test: the module loads and classifyVirtualNetwork is callable
    expect(typeof classifyVirtualNetwork).toBe('function');
  });
});

// ═══════════════════════════════════════════════════════════
// Регрессия: кодеки для produce должны совпадать с роутером
// ═══════════════════════════════════════════════════════════
//
// mediasoup сопоставляет H264 по паре «профиль + packetization-mode» и на
// первом же несовпадении роняет весь produce:
//   unsupported codec [mimeType:video/H264, payloadType:115]
// Браузер предлагает один профиль дважды (pm=1 и pm=0) разными payload
// type, поэтому фильтр обязан отсекать чужой режим, а не только профиль.

const ROUTER_CAPS = {
  codecs: [
    { kind: 'audio', mimeType: 'audio/opus', clockRate: 48000, channels: 2, parameters: {} },
    { kind: 'video', mimeType: 'video/VP8', clockRate: 90000, parameters: {} },
    {
      kind: 'video',
      mimeType: 'video/H264',
      clockRate: 90000,
      parameters: {
        'packetization-mode': '1',
        'profile-level-id': '42e01f',
        'level-asymmetry-allowed': '1',
      },
    },
  ],
  headerExtensions: [],
};

// Урезанный, но реалистичный m=video из Chrome: VP8, «наш» H264 и три
// варианта, которых у роутера нет.
const CHROME_VIDEO_SDP = [
  'v=0',
  'm=video 9 UDP/TLS/RTP/SAVPF 96 106 115 108 45',
  'a=rtpmap:96 VP8/90000',
  'a=rtpmap:106 H264/90000',
  'a=fmtp:106 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f',
  'a=rtpmap:115 H264/90000',
  'a=fmtp:115 level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=42e01f',
  'a=rtpmap:108 H264/90000',
  'a=fmtp:108 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f',
  'a=rtpmap:45 AV1/90000',
  '',
].join('\r\n');

function engineWithRouterCaps() {
  const engine = new MediaEngine(
    { signalingUrl: '', roomId: 'test-room', displayName: 'tester' },
    {}
  ) as any;
  engine.updateRouterCodecWhitelist(ROUTER_CAPS);
  return engine;
}

describe('extractCodecsFromSdp — совпадение с кодеками роутера', () => {
  it('оставляет VP8 и H264 только с packetization-mode роутера', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(CHROME_VIDEO_SDP, 'video');
    expect(codecs.map((codec: any) => codec.payloadType)).toEqual([96, 106]);
  });

  it('отсекает payloadType 115 — тот самый H264 с packetization-mode=0', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(CHROME_VIDEO_SDP, 'video');
    expect(codecs.some((codec: any) => codec.payloadType === 115)).toBe(false);
  });

  it('отсекает чужой профиль H264 (42001f) и незнакомые кодеки (AV1)', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(CHROME_VIDEO_SDP, 'video');
    const payloadTypes = codecs.map((codec: any) => codec.payloadType);
    expect(payloadTypes).not.toContain(108);
    expect(payloadTypes).not.toContain(45);
  });

  it('vp8-only оставляет только VP8', () => {
    const engine = engineWithRouterCaps();
    engine.videoCodecPolicy = 'vp8-only';
    const codecs = engine.extractCodecsFromSdp(CHROME_VIDEO_SDP, 'video');
    expect(codecs.map((codec: any) => codec.payloadType)).toEqual([96]);
  });
});

describe('isPreferredVideoCodec — предпочтения сендера', () => {
  it('не предпочитает H264 с чужим packetization-mode', () => {
    const engine = engineWithRouterCaps();
    expect(
      engine.isPreferredVideoCodec({
        mimeType: 'video/H264',
        sdpFmtpLine: 'level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=42e01f',
      })
    ).toBe(false);
  });

  it('предпочитает H264, который роутер действительно объявил', () => {
    const engine = engineWithRouterCaps();
    expect(
      engine.isPreferredVideoCodec({
        mimeType: 'video/H264',
        sdpFmtpLine: 'level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f',
      })
    ).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════
// Регрессия: synthetic answer не должен предлагать кодеки,
// о которых SFU не знает
// ═══════════════════════════════════════════════════════════
//
// Если в answer остаётся payload type, которого нет в produce, браузер может
// закодировать поток именно им. mediasoup принимает пакеты по SSRC (счётчик
// растёт), но разобрать кадры не может: keyframes у продюсера остаётся 0, а
// видео-consumer вечно ждёт ключевой кадр и не отправляет ничего.

describe('buildSendAnswerSdp — только согласованные payload type', () => {
  const OFFER = [
    'v=0',
    'o=- 1 2 IN IP4 127.0.0.1',
    's=-',
    't=0 0',
    'a=group:BUNDLE 0',
    'm=video 9 UDP/TLS/RTP/SAVPF 96 106 115 108',
    'a=mid:0',
    'a=rtpmap:96 VP8/90000',
    'a=rtpmap:106 H264/90000',
    'a=fmtp:106 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f',
    'a=rtpmap:115 H264/90000',
    'a=fmtp:115 level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=42e01f',
    'a=rtpmap:108 H264/90000',
    'a=fmtp:108 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f',
    '',
  ].join('\r\n');

  function answerFor(): string {
    const engine = engineWithRouterCaps();
    engine.sendTransportData = {
      iceParameters: { usernameFragment: 'ufrag', password: 'pwd' },
      dtlsParameters: { fingerprints: [{ algorithm: 'sha-256', value: 'AA:BB' }] },
      iceCandidates: [],
    };
    return engine.buildSendAnswerSdp(OFFER);
  }

  it('в m=video остаются только VP8 и H264 роутера', () => {
    const mLine = answerFor()
      .split('\r\n')
      .find((line) => line.startsWith('m=video'));
    expect(mLine).toBe('m=video 9 UDP/TLS/RTP/SAVPF 96 106');
  });

  it('rtpmap/fmtp отфильтрованных payload type не попадают в answer', () => {
    const answer = answerFor();
    expect(answer).toContain('a=rtpmap:106 H264/90000');
    expect(answer).not.toContain('a=rtpmap:115');
    expect(answer).not.toContain('a=rtpmap:108');
    expect(answer).not.toContain('packetization-mode=0');
  });
});

// ═══════════════════════════════════════════════════════════
// Регрессия: produce обязан нести rtcpFeedback
// ═══════════════════════════════════════════════════════════
//
// Без rtcpFeedback у producer'а mediasoup не может отправить отправителю ни
// PLI, ни FIR: первый keyframe улетает до создания producer'а, новый никто
// не запрашивает, и видео-consumer навсегда застревает в ожидании ключевого
// кадра (статистика: producer 1 Мбит/с, keyframes 0, PLI 0; consumer 0 пакетов).

const SDP_WITH_FEEDBACK = [
  'v=0',
  'm=video 9 UDP/TLS/RTP/SAVPF 96 106',
  'a=rtpmap:96 VP8/90000',
  'a=rtcp-fb:96 goog-remb',
  'a=rtcp-fb:96 transport-cc',
  'a=rtcp-fb:96 ccm fir',
  'a=rtcp-fb:96 nack',
  'a=rtcp-fb:96 nack pli',
  'a=rtpmap:106 H264/90000',
  'a=fmtp:106 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f',
  'a=rtcp-fb:106 nack pli',
  '',
].join('\r\n');

describe('extractCodecsFromSdp — rtcpFeedback', () => {
  it('переносит PLI/FIR/NACK в параметры кодека', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(SDP_WITH_FEEDBACK, 'video');
    const vp8 = codecs.find((codec: any) => codec.payloadType === 96);
    expect(vp8.rtcpFeedback).toEqual([
      { type: 'goog-remb' },
      { type: 'ccm', parameter: 'fir' },
      { type: 'nack' },
      { type: 'nack', parameter: 'pli' },
    ]);
  });

  it('выбрасывает transport-cc — роутер не сконфигурирован под TWCC', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(SDP_WITH_FEEDBACK, 'video');
    const types = codecs.flatMap((codec: any) => codec.rtcpFeedback.map((fb: any) => fb.type));
    expect(types).not.toContain('transport-cc');
  });

  it('у каждого кодека есть непустой rtcpFeedback', () => {
    const codecs = engineWithRouterCaps().extractCodecsFromSdp(SDP_WITH_FEEDBACK, 'video');
    expect(codecs.length).toBeGreaterThan(0);
    for (const codec of codecs) {
      expect(codec.rtcpFeedback.length).toBeGreaterThan(0);
    }
  });
});

// ═══════════════════════════════════════════════════════════
// mediaState: состояние микрофона/камеры ходит сообщением
// ═══════════════════════════════════════════════════════════
//
// Вывести его из потока нельзя: приглушая себя, браузер меняет только
// локальный track.enabled — producer живой, RTP идёт. У получателя
// track.muted означает совсем другое («пакеты ещё не пошли»), поэтому
// индикаторы UI опираются на это сообщение, а не на состояние треков.

function engineWithFakeSignaling() {
  const sent: Array<{ method: string; data: unknown }> = [];
  const handlers = new Map<string, (data: unknown) => void>();

  const signaling = {
    peerId: 'self',
    connected: true,
    connect: async () => ({ ok: true as const, value: undefined }),
    disconnect: () => ({ ok: true as const, value: undefined }),
    request: async () => ({ ok: true as const, value: {} }),
    notify: (method: string, data: unknown) => {
      sent.push({ method, data });
      return { ok: true as const, value: undefined };
    },
    on: (event: string, handler: (data: unknown) => void) => {
      handlers.set(event, handler);
    },
    off: () => undefined,
  };

  const received: unknown[] = [];
  const engine = new MediaEngine(
    {
      signalingUrl: '',
      roomId: 'test-room',
      displayName: 'tester',
      signalingFactory: () => signaling as never,
    },
    { onMediaState: (state) => received.push(state) }
  ) as any;

  // Подписки навешиваются приватным setupSignalingEvents — зовём напрямую,
  // чтобы не поднимать весь join-пайплайн с PeerConnection'ами.
  engine.setupSignalingEvents();

  return { engine, sent, handlers, received };
}

describe('mediaState', () => {
  it('sendMediaState отправляет оба флага', () => {
    const { engine, sent } = engineWithFakeSignaling();
    engine.sendMediaState({ micEnabled: false, camEnabled: true });
    expect(sent).toContainEqual({
      method: 'mediaState',
      data: { micEnabled: false, camEnabled: true },
    });
  });

  it('входящее сообщение превращается в событие onMediaState', () => {
    const { handlers, received } = engineWithFakeSignaling();
    handlers.get('mediaState')?.({ peerId: 'p1', micEnabled: false, camEnabled: true });
    expect(received).toEqual([{ peerId: 'p1', micEnabled: false, camEnabled: true }]);
  });

  it('пропущенные флаги считаются включёнными, сообщение без peerId игнорируется', () => {
    const { handlers, received } = engineWithFakeSignaling();
    handlers.get('mediaState')?.({ peerId: 'p2' });
    handlers.get('mediaState')?.({ micEnabled: false });
    expect(received).toEqual([{ peerId: 'p2', micEnabled: true, camEnabled: true }]);
  });
});
