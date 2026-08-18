/**
 * Запись конференции: генерация SDP и пул портов.
 *
 * Именно эти две вещи ломаются молча. Кривой SDP не роняет звонок — ffmpeg
 * просто пишет пустой или битый файл, и выясняется это уже после встречи,
 * когда переснять нечего. Пул портов, выдавший один порт дважды, приводит к
 * тому, что два участника пишутся поверх друг друга.
 *
 * Тесты чистые: ни mediasoup, ни ffmpeg, ни сети здесь нет.
 */
import { describe, expect, it, beforeEach } from '@jest/globals';

import { buildSdp, ports } from '../recording.js';

const audioParams = {
  codecs: [
    {
      mimeType: 'audio/opus',
      payloadType: 111,
      clockRate: 48000,
      channels: 2,
      parameters: { minptime: 10, useinbandfec: 1 },
      rtcpFeedback: [],
    },
  ],
  encodings: [{ ssrc: 22222222 }],
  headerExtensions: [],
  rtcp: {},
} as any;

const videoParams = {
  codecs: [
    {
      mimeType: 'video/VP8',
      payloadType: 96,
      clockRate: 90000,
      parameters: {},
      rtcpFeedback: [],
    },
  ],
  encodings: [{ ssrc: 33333333 }],
  headerExtensions: [],
  rtcp: {},
} as any;

describe('buildSdp', () => {
  it('описывает аудиодорожку так, как её ждёт ffmpeg', () => {
    const sdp = buildSdp({
      kind: 'audio', rtpParameters: audioParams, port: 45000, rtcpPort: 45001,
    });

    expect(sdp).toContain('m=audio 45000 RTP/AVP 111');
    expect(sdp).toContain('a=rtcp:45001');
    // Имя кодека берётся из mimeType без префикса типа: ffmpeg понимает
    // 'opus', а не 'audio/opus'.
    expect(sdp).toContain('a=rtpmap:111 opus/48000/2');
    expect(sdp).toContain('a=fmtp:111 minptime=10;useinbandfec=1');
    expect(sdp).toContain('a=ssrc:22222222 cname:htqweb-recorder');
    expect(sdp.endsWith('\n')).toBe(true);
  });

  it('для видео не приписывает число каналов', () => {
    const sdp = buildSdp({
      kind: 'video', rtpParameters: videoParams, port: 45002, rtcpPort: 45003,
    });

    expect(sdp).toContain('m=video 45002 RTP/AVP 96');
    expect(sdp).toContain('a=rtpmap:96 VP8/90000');
    expect(sdp).not.toMatch(/a=rtpmap:96 VP8\/90000\/\d/);
  });

  it('падает на параметрах без кодека, а не пишет мусорный файл', () => {
    expect(() => buildSdp({
      kind: 'audio',
      rtpParameters: { codecs: [], encodings: [] } as any,
      port: 45000, rtcpPort: 45001,
    })).toThrow(/кодек/);
  });
});

describe('пул RTP-портов', () => {
  beforeEach(() => ports.reset());

  it('выдаёт чётный порт и следующий за ним под RTCP', () => {
    const pair = ports.take();
    expect(pair).not.toBeNull();
    const [rtp, rtcp] = pair!;
    expect(rtp % 2).toBe(0);
    expect(rtcp).toBe(rtp + 1);
  });

  it('никогда не выдаёт один порт дважды', () => {
    const seen = new Set<number>();
    for (let i = 0; i < 20; i += 1) {
      const pair = ports.take();
      expect(pair).not.toBeNull();
      for (const port of pair!) {
        expect(seen.has(port)).toBe(false);
        seen.add(port);
      }
    }
  });

  it('возвращает освобождённые порты в оборот', () => {
    const first = ports.take()!;
    ports.release(first);
    expect(ports.take()).toEqual(first);
  });
});
