import { describe, expect, it } from 'vitest';
import {
  forceH265Params,
  forceVideoBitrate,
  mungeOpusParams,
  preferH265Codec,
} from './SdpMunger';

const SDP_SAMPLE = [
  'v=0',
  'o=- 46117327 2 IN IP4 127.0.0.1',
  's=-',
  't=0 0',
  'm=audio 9 UDP/TLS/RTP/SAVPF 111',
  'a=rtpmap:111 opus/48000/2',
  'a=fmtp:111 minptime=10;useinbandfec=0',
  'm=video 9 UDP/TLS/RTP/SAVPF 96 98',
  'c=IN IP4 0.0.0.0',
  'a=rtpmap:96 H264/90000',
  'a=rtpmap:98 H265/90000',
  '',
].join('\r\n');

describe('SdpMunger', () => {
  it('keeps only stable video codecs in m=video line', () => {
    const munged = preferH265Codec(SDP_SAMPLE);
    expect(munged).toContain('m=video 9 UDP/TLS/RTP/SAVPF 96');
  });

  it('does not force HEVC params anymore', () => {
    const munged = forceH265Params(SDP_SAMPLE);
    expect(munged).toBe(SDP_SAMPLE);
  });

  it('forces Opus studio profile params', () => {
    const munged = mungeOpusParams(SDP_SAMPLE);
    expect(munged).toContain('maxaveragebitrate=192000');
    expect(munged).toContain('stereo=1');
    expect(munged).toContain('cbr=1');
    expect(munged).toContain('useinbandfec=1');
  });

  it('injects target video bitrate lines', () => {
    const munged = forceVideoBitrate(SDP_SAMPLE, 12000);
    expect(munged).toContain('b=AS:12000');
    expect(munged).toContain('b=TIAS:12000000');
  });
});
