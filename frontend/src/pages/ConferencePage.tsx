import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '@/components/Header';
import { WebRTCManager, RemoteStream, QualityMetrics, WebRTCError } from '@/lib/webrtc';
import { usePreviewMedia } from '@/lib/webrtc/usePreviewMedia';
import type { ChatMessagePayload, PeerMediaState } from '@/lib/webrtc/MediaEngine';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { 
  Video, VideoOff, Mic, MicOff, PhoneOff, 
  MonitorPlay, Settings, Activity, Copy, Plus, LogIn, Link2,
  Volume2, VolumeX, Users, Shield, Zap, Sparkles, Check,
  Maximize2, Minimize2, Pin, MessageSquare, Send, Share2,
  LayoutGrid, Grid, MonitorUp, Radio, CheckCircle2, Info,
  Sliders, SlidersHorizontal, Lock, Unlock, Crown, UserX,
  UserCheck, Key, Eye, EyeOff, ShieldAlert, Sparkle, Ban
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';
import { UserProfile } from '@/types/userProfile';
import { useToast } from '@/hooks/use-toast';
import { Slider } from '@/components/ui/slider';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { getAccessToken } from '@/lib/auth/profileStorage';
import { readGuestSession } from '@/lib/conference/guestSession';
import { InviteDialog } from '@/components/conference/InviteDialog';
import { useTranslation } from 'react-i18next';
import i18next from '@/i18n';
import { copyText } from '@/lib/clipboard';

type ConferenceRuntimeConfig = {
  sfu_signaling_url: string;
  sfu_signaling_path?: string;
  ice_servers?: Array<{
    urls: string | string[];
    username?: string;
    credential?: string;
  }>;
  enabled?: boolean;
  wt_signaling_url?: string;
  wt_certificate_hashes?: string[];
};

interface ChatMessage {
  id: string;
  sender: string;
  text: string;
  timestamp: string;
  isSelf: boolean;
}

export interface RoomSettings {
  roomTitle: string;
  passwordProtection: boolean;
  passwordPin: string;
  enableWaitingRoom: boolean;
  lockRoom: boolean;
  muteOnEntry: boolean;
  disableVideoOnEntry: boolean;
  allowScreenShare: 'all' | 'host_only';
  allowChat: boolean;
  videoQuality: '1080p' | '720p' | '480p';
  codecPreference: 'auto' | 'vp8' | 'h264';
  maxParticipants: number;
  enableE2EEncryption: boolean;
}

const DEFAULT_ROOM_SETTINGS: RoomSettings = {
  roomTitle: i18next.t('conference.page.defaultRoomTitle'),
  passwordProtection: false,
  passwordPin: '',
  enableWaitingRoom: false,
  lockRoom: false,
  muteOnEntry: false,
  disableVideoOnEntry: false,
  allowScreenShare: 'all',
  allowChat: true,
  videoQuality: '720p',
  codecPreference: 'auto',
  maxParticipants: 25,
  enableE2EEncryption: true,
};

function resolveWebTransportConfig(
  conferenceConfig: ConferenceRuntimeConfig | undefined
): { url: string; certificateHashes?: string[] } | undefined {
  const url = conferenceConfig?.wt_signaling_url?.trim();
  if (!url) return undefined;
  return {
    url,
    certificateHashes: conferenceConfig?.wt_certificate_hashes?.filter(Boolean),
  };
}

function normalizeSignalingPath(rawPath?: string): string {
  const path = (rawPath || '/ws/sfu/').trim() || '/ws/sfu/';
  return path.startsWith('/') ? path : `/${path}`;
}

function isIpV4(hostname: string): boolean {
  return /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
}

function isIpV6(hostname: string): boolean {
  return hostname.includes(':');
}

function isPrivateIpV4(hostname: string): boolean {
  if (!isIpV4(hostname)) return false;
  const [a, b] = hostname.split('.').map(Number);
  if (Number.isNaN(a) || Number.isNaN(b)) return false;
  if (a === 10) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 127) return true;
  return false;
}

function isLocalOrPrivateHost(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  if (!normalized) return true;
  if (normalized === 'localhost') return true;
  if (normalized.endsWith('.localhost')) return true;
  if (normalized === '::1') return true;
  if (isPrivateIpV4(normalized)) return true;
  if (isIpV6(normalized) && (normalized.startsWith('fd') || normalized.startsWith('fc'))) {
    return true;
  }
  return false;
}

function isKnownTunnelHost(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  return (
    normalized.endsWith('.instatunnel.my') ||
    normalized.endsWith('.ngrok-free.app') ||
    normalized.endsWith('.ngrok-free.dev') ||
    normalized.endsWith('.ngrok.app') ||
    normalized.endsWith('.ngrok.io')
  );
}

function needsSecureMediaContext(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.isSecureContext) return false;

  const host = window.location.hostname.toLowerCase();
  const isLoopbackHost =
    host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');

  return !isLoopbackHost;
}

function resolveSignalingUrl(
  conferenceConfig: ConferenceRuntimeConfig | undefined
): { url: string; source: 'backend' | 'origin'; reason?: string } {
  const signalingPath = normalizeSignalingPath(conferenceConfig?.sfu_signaling_path);
  const originFallbackUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${signalingPath}`;
  const rawBackendUrl = conferenceConfig?.sfu_signaling_url?.trim();

  if (!rawBackendUrl) {
    return { url: originFallbackUrl, source: 'origin', reason: 'backend url is empty' };
  }

  let parsed: URL;
  try {
    parsed = new URL(rawBackendUrl);
  } catch {
    return { url: originFallbackUrl, source: 'origin', reason: 'backend url is invalid' };
  }

  const protocol = parsed.protocol.toLowerCase();
  if (protocol === 'http:') {
    parsed.protocol = 'ws:';
  } else if (protocol === 'https:') {
    parsed.protocol = 'wss:';
  } else if (protocol !== 'ws:' && protocol !== 'wss:') {
    return { url: originFallbackUrl, source: 'origin', reason: `unsupported protocol: ${parsed.protocol}` };
  }

  const currentHostIsLocal = isLocalOrPrivateHost(window.location.hostname);
  const targetHostIsLocal = isLocalOrPrivateHost(parsed.hostname);
  if (!currentHostIsLocal && targetHostIsLocal) {
    return { url: originFallbackUrl, source: 'origin', reason: 'backend url points to local/private host' };
  }

  const currentHost = window.location.hostname.toLowerCase();
  const backendHost = parsed.hostname.toLowerCase();
  const isCurrentTunnel = isKnownTunnelHost(currentHost);
  const isBackendTunnel = isKnownTunnelHost(backendHost);
  if (isCurrentTunnel && isBackendTunnel && currentHost !== backendHost) {
    return { url: originFallbackUrl, source: 'origin', reason: `stale tunnel host from backend (${backendHost})` };
  }

  if (!parsed.pathname || parsed.pathname === '/') {
    parsed.pathname = signalingPath;
  }

  if (window.location.protocol === 'https:' && parsed.protocol === 'ws:') {
    parsed.protocol = 'wss:';
  }

  return { url: parsed.toString(), source: 'backend' };
}

function resolveRuntimeIceServers(
  conferenceConfig: ConferenceRuntimeConfig | undefined
): RTCIceServer[] | undefined {
  const runtimeServers = conferenceConfig?.ice_servers;
  if (!Array.isArray(runtimeServers) || runtimeServers.length === 0) {
    return undefined;
  }

  const normalized: RTCIceServer[] = [];
  for (const server of runtimeServers) {
    const rawUrls = Array.isArray(server.urls) ? server.urls : [server.urls];
    const urls = rawUrls.map((value) => String(value || '').trim()).filter(Boolean);
    if (urls.length === 0) continue;

    const entry: RTCIceServer = { urls: urls.length === 1 ? urls[0] : urls };
    if (server.username) entry.username = server.username;
    if (server.credential) entry.credential = server.credential;
    normalized.push(entry);
  }

  return normalized.length > 0 ? normalized : undefined;
}

function isCodecCompatibilityError(error: WebRTCError): boolean {
  if (error.code === 'SIGNALING_UNSUPPORTED_CODEC') return true;
  if (error.code !== 'NATIVE_SDP_REJECTION') return false;

  const message = String(error.message || '').toLowerCase();
  return (
    message.includes('codec') ||
    message.includes('h264') ||
    message.includes('vp8') ||
    message.includes('profile-level-id') ||
    message.includes('packetization-mode')
  );
}

function useAudioActivity(
  stream: MediaStream | null,
  ringRef: React.RefObject<HTMLDivElement | null>,
  onLevelChange?: (level: number) => void,
  /** Счётчик событий треков: без него анализатор не стартует, потому что
   *  удалённый трек в момент монтирования ещё `muted` (см. VideoTile). */
  trackEpoch = 0
) {
  useEffect(() => {
    if (!stream) {
      if (ringRef.current) ringRef.current.style.borderColor = 'transparent';
      onLevelChange?.(0);
      return;
    }
    
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack || audioTrack.readyState !== 'live' || audioTrack.muted || !audioTrack.enabled) {
      if (ringRef.current) ringRef.current.style.borderColor = 'transparent';
      onLevelChange?.(0);
      return;
    }

    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;

    let audioCtx: AudioContext;
    let analyzer: AnalyserNode;
    let source: MediaStreamAudioSourceNode;
    let rafId: number;

    try {
      audioCtx = new AudioContextClass();
      analyzer = audioCtx.createAnalyser();
      analyzer.fftSize = 256;
      analyzer.smoothingTimeConstant = 0.4;
      
      const mediaStream = new MediaStream([audioTrack]);
      source = audioCtx.createMediaStreamSource(mediaStream);
      source.connect(analyzer);

      const dataArray = new Uint8Array(analyzer.frequencyBinCount);

      const updateLoop = () => {
        analyzer.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const average = sum / dataArray.length;
        
        onLevelChange?.(Math.min(100, Math.round((average / 128) * 100)));

        if (ringRef.current) {
          if (average > 8) {
            ringRef.current.style.borderColor = 'rgba(34, 197, 94, 0.8)';
            ringRef.current.style.boxShadow = '0 0 20px rgba(34, 197, 94, 0.3)';
          } else {
            ringRef.current.style.borderColor = 'transparent';
            ringRef.current.style.boxShadow = 'none';
          }
        }
        rafId = requestAnimationFrame(updateLoop);
      };

      rafId = requestAnimationFrame(updateLoop);
    } catch (e) {
      console.warn("Audio Context setup failed:", e);
    }

    return () => {
      cancelAnimationFrame(rafId);
      source?.disconnect();
      if (audioCtx?.state !== 'closed') {
        audioCtx?.close().catch(() => {});
      }
      if (ringRef.current) {
        ringRef.current.style.borderColor = 'transparent';
        ringRef.current.style.boxShadow = 'none';
      }
      onLevelChange?.(0);
    };
  }, [stream, ringRef, onLevelChange, trackEpoch]);
}

/**
 * Single Video Tile Component
 */
const VideoTile = ({ 
  stream, 
  isLocal = false, 
  displayName, 
  isPrimary = false,
  isSpotlighted = false,
  isHost = false,
  micEnabled = true,
  camEnabled = true,
  onSpotlightToggle
}: { 
  stream: MediaStream | null; 
  isLocal?: boolean; 
  displayName: string;
  isPrimary?: boolean;
  isSpotlighted?: boolean;
  isHost?: boolean;
  micEnabled?: boolean;
  camEnabled?: boolean;
  onSpotlightToggle?: () => void;
}) => {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const [volume, setVolume] = useState([100]);
  const [audioPlaybackBlocked, setAudioPlaybackBlocked] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  // «Кадры пошли» берём у самого элемента, а не из `track.muted`: у
  // удалённого трека этот флаг снимается ровно один раз и легко
  // разъезжается с рендером, а `playing`/`emptied` приходят всегда.
  const [videoPlaying, setVideoPlaying] = useState(false);

  // Удалённый трек до первого RTP-пакета всегда `muted`, а consumer'ы SFU
  // приходят на паузе — то есть в момент первого рендера плитки условия
  // ниже заведомо ложны. Пересчитываем их не «когда-нибудь при следующем
  // ререндере», а по событиям самих треков: `trackEpoch` инкрементится в
  // обработчиках mute/unmute/ended (эффект ниже) и входит в зависимости.
  const [trackEpoch, setTrackEpoch] = useState(0);

  const hasPlayableTracks =
    !!stream && stream.getTracks().some((track) => track.readyState === 'live');
  const hasLiveVideo =
    !!stream &&
    stream
      .getVideoTracks()
      .some((track) => track.readyState === 'live' && !track.muted && track.enabled);
  const hasLiveAudio =
    !!stream && stream.getAudioTracks().some((track) => track.readyState === 'live' && !track.muted && track.enabled);

  useAudioActivity(stream, ringRef, setAudioLevel, trackEpoch);

  useEffect(() => {
    if (!stream) return;

    const bump = () => setTrackEpoch((value) => value + 1);
    // Снимок треков: отписываемся ровно от тех, на кого подписались, —
    // состав потока к моменту cleanup уже может смениться.
    const tracks = stream.getTracks();
    tracks.forEach((track) => {
      track.addEventListener('unmute', bump);
      track.addEventListener('mute', bump);
      track.addEventListener('ended', bump);
    });
    // Новый трек в потоке — тоже повод пересобрать подписки.
    stream.addEventListener('addtrack', bump);
    stream.addEventListener('removetrack', bump);

    return () => {
      tracks.forEach((track) => {
        track.removeEventListener('unmute', bump);
        track.removeEventListener('mute', bump);
        track.removeEventListener('ended', bump);
      });
      stream.removeEventListener('addtrack', bump);
      stream.removeEventListener('removetrack', bump);
    };
  }, [stream, trackEpoch]);

  // Привязка потока НЕ должна зависеть от `track.muted`: у удалённого трека
  // он снимается только с первым RTP-пакетом, а до того элемента могло не
  // быть в DOM вовсе — тогда поток так и оставался неподключённым, пока
  // что-нибудь не перемонтирует плитку (например, кнопка «Фокус»).
  // Поэтому привязываем по наличию живого трека нужного вида, а `muted`
  // оставляем только для заглушки «камера отключена».
  const hasVideoTrack =
    !!stream && stream.getVideoTracks().some((track) => track.readyState === 'live');
  const hasAudioTrack =
    !!stream && stream.getAudioTracks().some((track) => track.readyState === 'live');

  // Картинку показываем, когда камера включена ПО ЗАЯВЛЕНИЮ участника и
  // элемент реально проигрывает кадры. Для локальной плитки события
  // `playing` достаточно — своё состояние камеры мы знаем точно.
  const showVideo = !!stream && hasVideoTrack && camEnabled && (videoPlaying || hasLiveVideo);

  useEffect(() => {
    const videoEl = videoRef.current;
    const audioEl = audioRef.current;

    const clearMedia = () => {
      if (videoEl) videoEl.srcObject = null;
      if (audioEl) audioEl.srcObject = null;
      setAudioPlaybackBlocked(false);
    };

    if (!stream || !hasPlayableTracks) {
      clearMedia();
      return;
    }

    const syncMedia = () => {
      if (hasVideoTrack && videoEl && videoEl.srcObject !== stream) {
        videoEl.srcObject = stream;
      }
      if (!hasVideoTrack && videoEl) {
        videoEl.srcObject = null;
      }

      if (!isLocal && hasAudioTrack && audioEl && audioEl.srcObject !== stream) {
        audioEl.srcObject = stream;
      }
      if ((!hasAudioTrack || isLocal) && audioEl) {
        audioEl.srcObject = null;
        setAudioPlaybackBlocked(false);
      }

      if (hasVideoTrack && videoEl) {
        videoEl.play().catch(() => {});
      }
      if (!isLocal && hasAudioTrack && audioEl) {
        const playAttempt = audioEl.play();
        playAttempt
          .then(() => setAudioPlaybackBlocked(false))
          .catch(() => setAudioPlaybackBlocked(true));
      }
    };

    syncMedia();

    stream.addEventListener('addtrack', syncMedia);
    stream.addEventListener('removetrack', syncMedia);

    return () => {
      stream.removeEventListener('addtrack', syncMedia);
      stream.removeEventListener('removetrack', syncMedia);
    };
  }, [hasAudioTrack, hasVideoTrack, hasPlayableTracks, isLocal, stream, trackEpoch]);

  useEffect(() => {
    if (audioRef.current && !isLocal) {
      audioRef.current.volume = volume[0] / 100;
    }
  }, [volume, isLocal, stream]);

  const handleUnlockAudio = () => {
    if (isLocal || !stream || !hasAudioTrack || !audioRef.current) return;
    if (audioRef.current.srcObject !== stream) {
      audioRef.current.srcObject = stream;
    }

    audioRef.current
      .play()
      .then(() => setAudioPlaybackBlocked(false))
      .catch(() => setAudioPlaybackBlocked(true));
  };

  return (
    <div className={`relative bg-gradient-to-b from-zinc-900 to-zinc-950 rounded-2xl overflow-hidden flex items-center justify-center ring-1 ring-white/10 shadow-xl group transition-all duration-300 ${
      isSpotlighted 
        ? 'w-full h-full aspect-video max-h-[80vh]' 
        : isPrimary 
        ? 'col-span-full aspect-video max-h-[75vh]' 
        : 'aspect-video w-full h-full min-h-[180px]'
    }`}>
      <div className="absolute inset-0 pointer-events-none rounded-2xl shadow-[inset_0_0_30px_rgba(0,0,0,0.5)] z-10" />
      <div ref={ringRef} className="absolute inset-0 pointer-events-none rounded-2xl border-2 border-transparent transition-all duration-200 z-20" />

      {/* Элемент рендерим по наличию трека, а не по `muted`: иначе он
          появляется в DOM только после первого кадра, и привязывать поток
          в этот момент уже некому. Заглушка ниже по-прежнему решает по
          `hasLiveVideo` — она про «камера выключена», а не про привязку. */}
      {stream && hasVideoTrack && (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          onPlaying={() => setVideoPlaying(true)}
          onEmptied={() => setVideoPlaying(false)}
          onPause={() => setVideoPlaying(false)}
          className={`w-full h-full object-cover ${isLocal ? 'scale-x-[-1]' : ''} ${
            showVideo ? '' : 'hidden'
          }`}
        />
      )}
      {!showVideo && (
        <div className="flex w-full h-full flex-col items-center justify-center bg-gradient-to-br from-zinc-800 via-zinc-900 to-zinc-950 relative overflow-hidden">
          {audioLevel > 5 && (
            <div 
              className="absolute rounded-full bg-emerald-500/20 blur-2xl transition-all duration-150 animate-pulse pointer-events-none"
              style={{ width: `${100 + audioLevel * 1.5}px`, height: `${100 + audioLevel * 1.5}px` }}
            />
          )}

          <div className="w-20 h-20 md:w-24 md:h-24 rounded-full bg-gradient-to-br from-emerald-600 to-teal-800 ring-4 ring-emerald-500/30 flex items-center justify-center mb-3 shadow-[0_0_30px_rgba(16,185,129,0.25)] relative z-10 transition-transform group-hover:scale-105">
            <span className="text-3xl md:text-4xl font-bold text-white font-display uppercase tracking-wider">
              {displayName.charAt(0) || 'U'}
            </span>
          </div>
          <span className="text-xs text-zinc-400 font-medium">
            {camEnabled ? t('conference.page.videoConnecting') : t('conference.page.cameraOff')}
          </span>
        </div>
      )}

      {!isLocal && stream && hasAudioTrack && (
        <audio ref={audioRef} autoPlay playsInline className="hidden" />
      )}

      {!isLocal && stream && hasAudioTrack && audioPlaybackBlocked && (
        <Button
          variant="secondary"
          size="sm"
          onClick={handleUnlockAudio}
          className="absolute top-4 right-4 z-30 h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg border border-emerald-400/30 font-medium"
        >
          <Volume2 className="w-3.5 h-3.5 mr-1.5 animate-bounce" />
          {t('conference.page.enableSound')}
        </Button>
      )}

      <div className="absolute top-3 right-3 flex items-center gap-1.5 z-30 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-200">
        {onSpotlightToggle && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onSpotlightToggle}
            className={`h-8 w-8 rounded-lg bg-black/60 backdrop-blur-md text-white border border-white/10 hover:bg-black/80 transition-colors ${
              isSpotlighted ? 'text-emerald-400 bg-black/90 border-emerald-500/40' : ''
            }`}
            title={isSpotlighted ? t('conference.page.unspotlight') : t('conference.page.spotlight')}
          >
            <Pin className="w-3.5 h-3.5" />
          </Button>
        )}
      </div>

      <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between z-30 pointer-events-none">
        <div className="bg-black/70 backdrop-blur-md px-3 py-1.5 rounded-xl text-xs font-medium text-white shadow-md border border-white/10 flex items-center gap-2 pointer-events-auto">
          {/* Строго по объявленному состоянию участника: `hasLiveAudio`
              здесь врал — у получателя он говорит лишь «пакеты пошли». */}
          {!micEnabled ? (
            <span className="p-1 rounded bg-rose-500/20 text-rose-400">
              <MicOff className="w-3 h-3" />
            </span>
          ) : (
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          )}
          <span className="truncate max-w-[120px] md:max-w-[180px] font-semibold tracking-wide flex items-center gap-1">
            {displayName} 
            {isHost && (
              <span className="bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] px-1.5 py-0.5 rounded font-bold flex items-center gap-0.5">
                <Crown className="w-2.5 h-2.5" />
                {t('conference.page.host')}
              </span>
            )}
            {isLocal && <span className="text-emerald-400 font-normal opacity-90">{t('conference.page.youParen')}</span>}
          </span>
        </div>

        {/* Регулятор громкости привязан к наличию аудио-трека, а не к
            `hasLiveAudio`: иначе он появлялся только после первых пакетов
            и пропадал у приглушённого собеседника, которого хочется
            заранее сделать потише. */}
        {!isLocal && hasAudioTrack && (
          <div className="pointer-events-auto">
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8 rounded-xl bg-black/70 backdrop-blur-md shadow-md border border-white/10 hover:bg-black/90 text-white transition-opacity opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100">
                  {volume[0] === 0 ? <VolumeX className="w-3.5 h-3.5 text-rose-400" /> : <Volume2 className="w-3.5 h-3.5 text-emerald-400" />}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-48 bg-[#18191c] border-[#2b2d31] p-3 text-gray-200 shadow-2xl rounded-xl" side="top" align="end" sideOffset={8}>
                <div className="flex flex-col gap-2.5 relative z-50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-300">{t('conference.page.volume')}</span>
                    <span className="text-xs font-mono text-emerald-400 font-bold">{volume[0]}%</span>
                  </div>
                  <Slider 
                    value={volume} 
                    onValueChange={setVolume} 
                    max={100} 
                    step={1}
                    className="cursor-pointer"
                  />
                </div>
              </PopoverContent>
            </Popover>
          </div>
        )}
      </div>
    </div>
  );
};

export const ConferencePage = () => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { roomId: roomIdFromUrl } = useParams<{ roomId?: string }>();
  const activeRoomId = (roomIdFromUrl || '').trim();
  const isRoomSelected = activeRoomId.length > 0;

  // Authentication & Profile
  //
  // В комнате могут оказаться двое разных людей: сотрудник платформы и
  // гость, вошедший по ссылке-приглашению. У второго нет ни учётки, ни
  // профиля, ни доступа к /conference/config — всё, что у него есть, это
  // токен на ОДНУ комнату и конфиг, приехавший вместе с ним.
  const token = getAccessToken();
  const guest = useMemo(() => {
    const session = readGuestSession();
    if (!session) return null;
    // Гостевой токен действителен ровно для своей комнаты — открытая
    // вручную чужая ссылка не должна выглядеть как «сейчас войдём».
    return session.roomId === (roomIdFromUrl || '').trim() ? session : null;
  }, [roomIdFromUrl]);
  const isGuest = Boolean(guest) && !token;
  const signalingToken = () => (isGuest ? guest!.token : getAccessToken());
  const { data: userProfile } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      const res = await api.get<UserProfile>('users/v1/profile/me');
      return res.data;
    },
    // У гостя профиля нет: запрос вернул бы 401 и увёл его на страницу
    // входа прямо из звонка.
    enabled: !!token,
  });

  const { data: fetchedConfig } = useQuery({
    queryKey: ['conference-config'],
    queryFn: async () => {
      const res = await api.get<ConferenceRuntimeConfig>('cms/v1/conference/config');
      return res.data;
    },
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
  });
  // Гостю конфиг приезжает вместе с гостевым токеном: сам эндпоинт закрыт
  // платформенным JWT, и открывать его наружу ради адреса сигналинга —
  // лишняя публичная поверхность.
  const conferenceConfig = (isGuest
    ? (guest!.conference as ConferenceRuntimeConfig | undefined)
    : fetchedConfig);
  
  const user = userProfile || null;
  
  // WebRTC State
  const [manager, setManager] = useState<WebRTCManager | null>(null);
  const [connected, setConnected] = useState(false);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStreams, setRemoteStreams] = useState<RemoteStream[]>([]);
  const [participants, setParticipants] = useState<Map<string, string>>(new Map());
  // Микрофон/камера остальных участников — по их собственным объявлениям
  // (сообщение `mediaState`). До первого объявления считаем включёнными.
  const [peerMediaState, setPeerMediaState] = useState<
    Map<string, { micEnabled: boolean; camEnabled: boolean }>
  >(new Map());
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null);
  const [joinRoomInput, setJoinRoomInput] = useState('');
  const [enteredPasswordInput, setEnteredPasswordInput] = useState('');
  const [joinedRoomId, setJoinedRoomId] = useState<string | null>(null);
  
  // Room Settings State (Host Configuration)
  const [isHost, setIsHost] = useState(true); // Creator default as host
  const [roomSettings, setRoomSettings] = useState<RoomSettings>(DEFAULT_ROOM_SETTINGS);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [waitingRoomQueue, setWaitingRoomQueue] = useState<Array<{ peerId: string; name: string }>>([]);

  // Call Controls & UI modes
  const [micEnabled, setMicEnabled] = useState(true);
  const [camEnabled, setCamEnabled] = useState(true);
  const [showStats, setShowStats] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [activeTab, setActiveTab] = useState<'participants' | 'chat'>('participants');
  const [layoutMode, setLayoutMode] = useState<'grid' | 'spotlight'>('grid');
  const [spotlightPeerId, setSpotlightPeerId] = useState<string | null>(null);
  const [callDurationSec, setCallDurationSec] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');

  // Pre-join Media Stream
  const [previewCamEnabled, setPreviewCamEnabled] = useState(true);
  const [previewMicEnabled, setPreviewMicEnabled] = useState(true);
  const [previewAudioLevel, setPreviewAudioLevel] = useState(0);
  // Предпросмотр включается ТОЛЬКО по явному действию. Раньше камера и
  // микрофон захватывались на входе в комнату — человек ещё не решил,
  // заходить ли в разговор, а лампочка камеры уже горела.
  const [inviteOpen, setInviteOpen] = useState(false);
  const [previewActive, setPreviewActive] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);
  const previewRingRef = useRef<HTMLDivElement>(null);

  const handlePreviewFailure = useCallback((err: unknown) => {
    console.warn('Pre-call media preview request failed:', err);
    setPreviewActive(false);
    setPreviewError(
      t('conference.page.mediaPermissionError')
    );
  }, [t]);

  // Захват и — что важнее — освобождение устройств живут в хуке
  // (lib/webrtc/usePreviewMedia.ts): там же лежат тесты на «камера отпущена
  // при уходе со страницы», которые на этой странице не написать.
  const {
    stream: previewStream,
    stop: stopPreviewStream,
  } = usePreviewMedia({
    // isRoomSelected здесь не для красоты: карточка предпросмотра рисуется
    // только на экране комнаты, а эффект захвата разметке не подчиняется —
    // раньше на /conference без комнаты камера включалась молча, вообще без
    // видимого предпросмотра. Условие захвата обязано совпадать с условием
    // показа, иначе они снова разъедутся.
    active: previewActive && isRoomSelected && !connected,
    cam: previewCamEnabled,
    mic: previewMicEnabled,
    onFailure: handlePreviewFailure,
  });

  useAudioActivity(previewStream, previewRingRef, setPreviewAudioLevel);

  // Маршрут комнаты открыт без обязательной авторизации — иначе гость с
  // токеном в sessionStorage до неё бы не добрался. Право находиться здесь
  // проверяется тут: либо рабочая сессия, либо гостевая на ЭТУ комнату.
  // Случайный посетитель отправляется на вход, как и раньше.
  useEffect(() => {
    if (token || isGuest) return;
    navigate('/login', { replace: true, state: { from: location.pathname } });
  }, [token, isGuest, navigate]);

  // Load / Sync Room Settings from localStorage
  useEffect(() => {
    if (activeRoomId) {
      const saved = localStorage.getItem(`conf_settings_${activeRoomId}`);
      if (saved) {
        try {
          setRoomSettings(JSON.parse(saved));
        } catch {
          // ignore
        }
      }
    }
  }, [activeRoomId]);

  const saveRoomSettings = (updated: RoomSettings) => {
    setRoomSettings(updated);
    if (activeRoomId) {
      localStorage.setItem(`conf_settings_${activeRoomId}`, JSON.stringify(updated));
    }
    toast({ description: t('conference.page.settingsSaved') });
  };

  // Preset Template loader
  const applyPreset = (preset: 'webinar' | 'meeting' | 'private') => {
    let updated: RoomSettings = { ...roomSettings };
    if (preset === 'webinar') {
      updated = {
        ...updated,
        muteOnEntry: true,
        disableVideoOnEntry: true,
        allowScreenShare: 'host_only',
        enableWaitingRoom: true,
        videoQuality: '1080p',
      };
      toast({ description: t('conference.page.presetWebinarApplied') });
    } else if (preset === 'meeting') {
      updated = {
        ...updated,
        muteOnEntry: false,
        disableVideoOnEntry: false,
        allowScreenShare: 'all',
        enableWaitingRoom: false,
        videoQuality: '720p',
      };
      toast({ description: t('conference.page.presetMeetingApplied') });
    } else if (preset === 'private') {
      updated = {
        ...updated,
        maxParticipants: 2,
        enableWaitingRoom: true,
        enableE2EEncryption: true,
        videoQuality: '1080p',
      };
      toast({ description: t('conference.page.presetPrivateApplied') });
    }
    saveRoomSettings(updated);
  };


  useEffect(() => {
    if (!previewVideoRef.current) return;
    // Снимаем ссылку вместе с потоком: элемент, оставленный с остановленным
    // MediaStream, держит его в памяти и показывает застывший кадр.
    previewVideoRef.current.srcObject = previewStream;
  }, [previewStream, previewCamEnabled]);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (connected) {
      timer = setInterval(() => {
        setCallDurationSec((prev) => prev + 1);
      }, 1000);
    } else {
      setCallDurationSec(0);
    }
    return () => clearInterval(timer);
  }, [connected]);

  const formattedCallTime = useMemo(() => {
    const mins = Math.floor(callDurationSec / 60);
    const secs = callDurationSec % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }, [callDurationSec]);

  useEffect(() => {
    return () => {
      void manager?.leave();
    };
  }, [manager]);

  useEffect(() => {
    if (!connected) {
      setJoinRoomInput(activeRoomId);
    }
  }, [activeRoomId, connected]);

  useEffect(() => {
    if (!connected || !manager || !joinedRoomId) return;
    if (activeRoomId === joinedRoomId) return;

    void manager.leave();
    setManager(null);
    setConnected(false);
    setLocalStream(null);
    setRemoteStreams([]);
    setParticipants(new Map());
    setJoinedRoomId(null);
  }, [activeRoomId, connected, manager, joinedRoomId]);

  const generateRoomId = (): string => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      const parts = crypto.randomUUID().split('-');
      return `${parts[0]}-${parts[1]}`;
    }
    const randomPart = Math.random().toString(36).slice(2, 8);
    const timePart = Date.now().toString(36).slice(-4);
    return `${randomPart}-${timePart}`;
  };

  const handleCreateRoomRoute = () => {
    const newRoomId = generateRoomId();
    setIsHost(true);
    navigate(`/room/${newRoomId}`);
  };

  const handleGoToRoom = () => {
    const normalized = joinRoomInput.trim();
    if (!normalized) {
      toast({
        variant: 'destructive',
        description: t('conference.page.enterRoomId'),
      });
      return;
    }
    setIsHost(false);
    navigate(`/room/${encodeURIComponent(normalized)}`);
  };

  const handleCopyRoomId = async () => {
    if (!activeRoomId) return;
    try {
      await copyText(activeRoomId);
      toast({ description: t('conference.page.roomIdCopied') });
    } catch {
      toast({
        variant: 'destructive',
        description: t('conference.page.roomIdCopyFailed'),
      });
    }
  };

  // Переключатели только меняют намерение — открыть или отпустить устройство
  // решает эффект предпросмотра выше. Он же переживает случай «выключили
  // камеру, оставили микрофон»: поток пересобирается, камера отпускается
  // по-настоящему.
  const togglePreviewCam = () => setPreviewCamEnabled((on) => !on);
  const togglePreviewMic = () => setPreviewMicEnabled((on) => !on);

  const handleJoin = async () => {
    if (!isRoomSelected) {
      toast({ variant: 'destructive', description: t('conference.page.noRoomYet') });
      return;
    }

    // Гостю профиль не нужен: он представился на странице приглашения, и
    // его имя лежит в гостевой сессии.
    if (!user && !isGuest) {
      toast({ variant: 'destructive', description: t('conference.page.notAuthorised') });
      return;
    }

    // Password validation if room requires PIN
    if (!isHost && roomSettings.passwordProtection && roomSettings.passwordPin) {
      if (enteredPasswordInput.trim() !== roomSettings.passwordPin.trim()) {
        toast({
          variant: 'destructive',
          description: t('conference.page.wrongPin'),
        });
        return;
      }
    }

    // Lock check
    if (!isHost && roomSettings.lockRoom) {
      toast({
        variant: 'destructive',
        description: t('conference.page.roomLocked'),
      });
      return;
    }

    if (needsSecureMediaContext()) {
      toast({
        variant: 'destructive',
        description: t('conference.page.needsSecureContext'),
      });
      return;
    }

    // Устройства предпросмотра отпускаются ДО того, как их запросит
    // MediaEngine: иначе камера окажется занята собственной же вкладкой.
    setPreviewActive(false);
    stopPreviewStream();

    const signalingUrlResolution = resolveSignalingUrl(conferenceConfig);
    const signalingUrl = signalingUrlResolution.url;
    if (!signalingUrl) {
      toast({ variant: 'destructive', description: t('conference.page.noSfuUrl') });
      return;
    }

    const runtimeIceServers = resolveRuntimeIceServers(conferenceConfig);
    const webTransportConfig = resolveWebTransportConfig(conferenceConfig);

    const managerEvents = {
      onConnectionStateChange: (state: string) => {
        setConnected(state === 'connected');
        if (state === 'disconnected') {
          setLocalStream(null);
          setRemoteStreams([]);
          setJoinedRoomId(null);
        }
      },
      onRemoteStream: (stream: RemoteStream) => {
        setRemoteStreams((prev) => {
          const filtered = prev.filter(
            (item) =>
              item.consumerId !== stream.consumerId &&
              !(item.peerId === stream.peerId && item.kind === stream.kind)
          );
          return [...filtered, stream];
        });
      },
      onRemoteStreamRemoved: (consumerId: string) => {
        setRemoteStreams(prev => prev.filter(s => s.consumerId !== consumerId));
      },
      onParticipantJoined: (peerId: string, name: string) => {
        setParticipants(prev => {
          const next = new Map(prev);
          next.set(peerId, name);
          return next;
        });
        toast({ description: t('conference.page.participantJoined', { name }) });
      },
      onParticipantLeft: (peerId: string) => {
        setParticipants(prev => {
          const next = new Map(prev);
          next.delete(peerId);
          return next;
        });
        setRemoteStreams(prev => prev.filter(s => s.peerId !== peerId));
        setPeerMediaState((prev) => {
          const next = new Map(prev);
          next.delete(peerId);
          return next;
        });
      },
      onMediaState: (state: PeerMediaState) => {
        setPeerMediaState((prev) => {
          const next = new Map(prev);
          next.set(state.peerId, {
            micEnabled: state.micEnabled,
            camEnabled: state.camEnabled,
          });
          return next;
        });
      },
      onChatMessage: (message: ChatMessagePayload) => {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `${message.peerId}-${message.sentAt}-${prev.length}`,
            sender: message.displayName,
            text: message.text,
            timestamp: new Date(message.sentAt).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            }),
            isSelf: false,
          },
        ]);
      },
      onQualityMetrics: (newMetrics: QualityMetrics) => {
        setMetrics(newMetrics);
      },
      onInfo: (message: string) => {
        toast({ description: message });
      },
      onCodecPolicyChanged: (policy: 'balanced' | 'vp8-only') => {
        if (policy === 'vp8-only') {
          toast({ description: t('conference.page.switchingToVp8') });
        }
      },
      onError: (error: WebRTCError) => {
        if (isCodecCompatibilityError(error)) return;
        console.error(error);
        toast({
          variant: 'destructive',
          description: t('conference.page.webrtcError', { message: error.message })
        });
      }
    };

    // Determine initial codec policy based on host setting
    const codecPolicyChoice = roomSettings.codecPreference === 'vp8' ? 'vp8-only' : 'balanced';

    const createManager = (policy: 'balanced' | 'vp8-only') =>
      new WebRTCManager({
        signalingUrl,
        authToken: signalingToken,
        webTransport: webTransportConfig,
        roomId: activeRoomId,
        displayName: user
          ? (user.firstName ? `${user.firstName} ${user.lastName || ''}` : user.email)
          : (guest?.displayName || t('conference.page.guest')),
        iceServers: runtimeIceServers,
        initialVideoCodecPolicy: policy,
        autoVp8Fallback: false,
      }, managerEvents);

    let activeManager = createManager(codecPolicyChoice);
    setManager(activeManager);
    let joinResult = await activeManager.join();

    if (!joinResult.ok && isCodecCompatibilityError(joinResult.error)) {
      toast({ description: t('conference.page.tryingH264') });
      await activeManager.leave();
      const balancedManager = createManager('balanced');
      activeManager = balancedManager;
      setManager(balancedManager);
      joinResult = await balancedManager.join();
    }

    if (!joinResult.ok) {
      setManager(null);
      toast({
        variant: 'destructive',
        description: t('conference.page.joinFailed', { message: joinResult.error.message })
      });
      return;
    }

    setManager(activeManager);
    const joinedStream = joinResult.value;
    const localAudioTrack = joinedStream.getAudioTracks()[0];
    const localVideoTrack = joinedStream.getVideoTracks()[0];

    setLocalStream(joinedStream);
    
    // Apply host room policies (mute on entry, disable video on entry)
    const initialMicState = roomSettings.muteOnEntry ? false : previewMicEnabled;
    const initialCamState = roomSettings.disableVideoOnEntry ? false : previewCamEnabled;

    if (localAudioTrack) localAudioTrack.enabled = initialMicState;
    if (localVideoTrack) localVideoTrack.enabled = initialCamState;

    setMicEnabled(initialMicState);
    setCamEnabled(initialCamState);
    setJoinedRoomId(activeRoomId);

    // Объявляем своё состояние комнате: остальные не могут вывести его из
    // потока (при мьюте трек остаётся живым), а вошедшим позже SFU отдаст
    // последнее объявленное значение.
    activeManager.sendMediaState({
      micEnabled: initialMicState,
      camEnabled: initialCamState,
    });

    if (roomSettings.muteOnEntry && !isHost) {
      toast({ description: t('conference.page.muteOnEntryNotice') });
    }
  };

  const handleLeave = async () => {
    if (manager) {
      await manager.leave();
      setManager(null);
    }
    setConnected(false);
    setLocalStream(null);
    setRemoteStreams([]);
    setParticipants(new Map());
    setPeerMediaState(new Map());
    setJoinedRoomId(null);
    setMicEnabled(true);
    setCamEnabled(true);
  };

  const toggleMic = () => {
    if (manager) {
      const nextValue = !micEnabled;
      const audioResult = manager.setAudioEnabled(nextValue);
      if (!audioResult.ok) {
        toast({
          variant: 'destructive',
          description: t('conference.page.micError', { message: audioResult.error.message }),
        });
        return;
      }
      setMicEnabled(nextValue);
      manager.sendMediaState({ micEnabled: nextValue, camEnabled });
    }
  };

  const toggleCam = () => {
    if (manager) {
      const hasVideoTrack =
        !!localStream &&
        localStream.getVideoTracks().some((track) => track.readyState === 'live');
      if (!hasVideoTrack) {
        setCamEnabled(false);
        toast({ description: t('conference.page.audioOnlyNotice') });
        return;
      }

      const nextValue = !camEnabled;
      const videoResult = manager.setVideoEnabled(nextValue);
      if (!videoResult.ok) {
        toast({
          variant: 'destructive',
          description: t('conference.page.camError', { message: videoResult.error.message }),
        });
        return;
      }
      setCamEnabled(nextValue);
      manager.sendMediaState({ micEnabled, camEnabled: nextValue });
    }
  };

  // Host Moderation Actions
  const handleHostMuteAll = () => {
    if (!isHost) return;
    toast({ description: t('conference.page.mutedAll') });
  };

  const handleHostStopAllVideos = () => {
    if (!isHost) return;
    toast({ description: t('conference.page.stoppedAllVideo') });
  };

  const handleHostLockToggle = () => {
    if (!isHost) return;
    const nextState = !roomSettings.lockRoom;
    saveRoomSettings({ ...roomSettings, lockRoom: nextState });
    toast({ description: nextState ? t('conference.page.roomLockedNow') : t('conference.page.roomUnlockedNow') });
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const handleSendChatMessage = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!chatInput.trim()) return;

    if (!roomSettings.allowChat && !isHost) {
      toast({ variant: 'destructive', description: t('conference.page.chatDisabled') });
      return;
    }

    const newMsg: ChatMessage = {
      id: Date.now().toString(),
      sender: user?.firstName || t('conference.page.me'),
      text: chatInput.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      isSelf: true,
    };

    // Своё сообщение показываем сразу, эхо от сервера не ждём: SFU рассылает
    // его остальным участникам и отправителю обратно не возвращает.
    setChatMessages((prev) => [...prev, newMsg]);
    setChatInput('');

    const sendResult = manager?.sendChatMessage(newMsg.text);
    if (sendResult && !sendResult.ok) {
      toast({
        variant: 'destructive',
        description: t('conference.page.messageNotSent'),
      });
    }
  };

  const peers = useMemo(() => {
    const peerIds = Array.from(new Set(remoteStreams.map(s => s.peerId)));
    return peerIds.map(peerId => {
      const peerStreams = remoteStreams.filter(s => s.peerId === peerId);
      const combinedStream = new MediaStream();

      let latestVideoTrack: MediaStreamTrack | null = null;
      let latestAudioTrack: MediaStreamTrack | null = null;

      for (let i = peerStreams.length - 1; i >= 0; i -= 1) {
        const remote = peerStreams[i];
        const track = remote.track;
        if (!track || track.readyState !== 'live') continue;

        if (remote.kind === 'video' && !latestVideoTrack) {
          latestVideoTrack = track;
          continue;
        }

        if (remote.kind === 'audio' && !latestAudioTrack) {
          latestAudioTrack = track;
        }
      }

      if (latestVideoTrack) combinedStream.addTrack(latestVideoTrack);
      if (latestAudioTrack) combinedStream.addTrack(latestAudioTrack);

      return {
        peerId,
        displayName: peerStreams[0]?.displayName || t('conference.media.participant'),
        stream: combinedStream,
      };
    });
  }, [remoteStreams, t]);

  const localDisplayName = user?.firstName || t('conference.page.me');

  // ═══════════════════════════════════════════════════════════
  // ACTIVE CALL INTERFACE (CONNECTED STATE)
  // ═══════════════════════════════════════════════════════════
  if (connected) {
    const isSpotlightActive = layoutMode === 'spotlight' && spotlightPeerId !== null;

    return (
      <TooltipProvider>
        <div className="h-screen w-full bg-[#090a0c] text-gray-100 flex flex-col overflow-hidden font-sans select-none">
          
          {/* Top Bar Header */}
          <header className="h-14 bg-[#141518]/90 backdrop-blur-md border-b border-white/10 px-4 flex items-center justify-between shadow-md z-30 shrink-0">
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="gap-2 py-1 px-3 bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-xs font-semibold rounded-full">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                {t('conference.page.voiceConnected')}
              </Badge>

              {isHost && (
                <Badge variant="secondary" className="gap-1 bg-amber-500/20 text-amber-300 border-amber-500/30 text-xs font-bold">
                  <Crown className="w-3 h-3" /> {t('conference.page.youAreHost')}
                </Badge>
              )}

              {/* Запись ведётся автоматически на каждой встрече, и участники
                  обязаны это видеть — молча писать людей нельзя. Индикатор
                  постоянный: включать/выключать запись из интерфейса нельзя,
                  поэтому и состояния «не пишем» здесь не бывает. */}
              <Badge
                variant="outline"
                title={t('conference.page.recordingTooltip')}
                className="gap-1.5 py-1 px-2.5 bg-rose-500/10 text-rose-300 border-rose-500/30 text-xs font-semibold rounded-full"
              >
                <div className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                {t('conference.page.recording')}
              </Badge>

              {activeRoomId && (
                <button
                  onClick={handleCopyRoomId}
                  className="flex items-center gap-1.5 px-2.5 py-1 bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white rounded-lg text-xs font-mono border border-white/10 transition-colors"
                >
                  <span className="text-gray-400 font-sans text-[11px]">{t('conference.page.roomLabel')}</span>
                  <span className="font-bold text-emerald-400">{activeRoomId}</span>
                  <Copy className="w-3 h-3 ml-1 text-gray-400" />
                </button>
              )}

              <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-gray-400 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">
                <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />
                {formattedCallTime}
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Host Room Settings Dialog Trigger */}
              {isHost && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowSettingsModal(true)}
                      className="h-8 px-3 text-xs bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg font-bold flex items-center gap-1.5"
                    >
                      <SlidersHorizontal className="w-3.5 h-3.5" />
                      {t('conference.page.roomSettings')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('conference.page.roomSettingsHint')}</TooltipContent>
                </Tooltip>
              )}

              {/* View Layout Mode Toggle */}
              <div className="bg-white/5 p-1 rounded-lg border border-white/10 flex items-center gap-1">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setLayoutMode('grid')}
                      className={`h-7 px-2.5 text-xs rounded-md ${layoutMode === 'grid' ? 'bg-emerald-600 text-white shadow-sm' : 'text-gray-400 hover:text-white'}`}
                    >
                      <LayoutGrid className="w-3.5 h-3.5 mr-1" />
                      {t('conference.page.layoutGrid')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('conference.page.layoutGridHint')}</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setLayoutMode('spotlight')}
                      className={`h-7 px-2.5 text-xs rounded-md ${layoutMode === 'spotlight' ? 'bg-emerald-600 text-white shadow-sm' : 'text-gray-400 hover:text-white'}`}
                    >
                      <Pin className="w-3.5 h-3.5 mr-1" />
                      {t('conference.page.layoutSpotlight')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('conference.page.layoutSpotlightHint')}</TooltipContent>
                </Tooltip>
              </div>

              {/* Fullscreen Button */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={toggleFullscreen}
                    className="h-8 w-8 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg"
                  >
                    {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{isFullscreen ? t('conference.page.exitFullscreen') : t('conference.page.enterFullscreen')}</TooltipContent>
              </Tooltip>

              {/* Toggle Sidebar Button */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setShowSidebar(!showSidebar)}
                    className={`h-8 w-8 rounded-lg transition-colors relative ${
                      showSidebar ? 'text-emerald-400 bg-emerald-500/10' : 'text-gray-400 hover:text-white hover:bg-white/10'
                    }`}
                  >
                    <Users className="w-4 h-4" />
                    <span className="absolute -top-1 -right-1 bg-emerald-500 text-black font-bold text-[9px] w-4 h-4 rounded-full flex items-center justify-center">
                      {participants.size + 1}
                    </span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('conference.page.sidePanel')}</TooltipContent>
              </Tooltip>
            </div>
          </header>

          {/* Main Work Area */}
          <div className="flex-1 flex overflow-hidden relative">
            
            {/* Video Container Grid */}
            <main className="flex-1 p-3 md:p-5 flex flex-col items-center justify-center overflow-y-auto relative bg-[#090a0c]">
              
              {/* Spotlight Mode View */}
              {isSpotlightActive ? (
                <div className="w-full h-full flex flex-col gap-4 max-w-7xl">
                  <div className="flex-1 min-h-[60vh] w-full">
                    {spotlightPeerId === 'local' ? (
                      <VideoTile
                        stream={localStream}
                        isLocal={true}
                        displayName={localDisplayName}
                        micEnabled={micEnabled}
                        camEnabled={camEnabled}
                        isSpotlighted={true}
                        isHost={isHost}
                        onSpotlightToggle={() => setSpotlightPeerId(null)}
                      />
                    ) : (
                      (() => {
                        const peer = peers.find((p) => p.peerId === spotlightPeerId);
                        return peer ? (
                          <VideoTile
                            stream={peer.stream}
                            displayName={peer.displayName}
                            micEnabled={peerMediaState.get(peer.peerId)?.micEnabled ?? true}
                            camEnabled={peerMediaState.get(peer.peerId)?.camEnabled ?? true}
                            isSpotlighted={true}
                            onSpotlightToggle={() => setSpotlightPeerId(null)}
                          />
                        ) : null;
                      })()
                    )}
                  </div>

                  <div className="h-28 flex gap-3 overflow-x-auto p-1 scrollbar-thin">
                    {spotlightPeerId !== 'local' && (
                      <div className="w-44 shrink-0 h-full cursor-pointer" onClick={() => setSpotlightPeerId('local')}>
                        <VideoTile
                          stream={localStream}
                          isLocal={true}
                          displayName={localDisplayName}
                          isHost={isHost}
                          micEnabled={micEnabled}
                          camEnabled={camEnabled}
                        />
                      </div>
                    )}
                    {peers
                      .filter((p) => p.peerId !== spotlightPeerId)
                      .map((peer) => (
                        <div key={peer.peerId} className="w-44 shrink-0 h-full cursor-pointer" onClick={() => setSpotlightPeerId(peer.peerId)}>
                          <VideoTile
                            stream={peer.stream}
                            displayName={peer.displayName}
                            micEnabled={peerMediaState.get(peer.peerId)?.micEnabled ?? true}
                            camEnabled={peerMediaState.get(peer.peerId)?.camEnabled ?? true}
                          />
                        </div>
                      ))}
                  </div>
                </div>
              ) : (
                /* Grid Mode Layout */
                <div className={`w-full max-w-[1600px] h-full grid gap-3 md:gap-4 place-content-center items-center ${
                  peers.length === 0 ? 'max-w-4xl grid-cols-1' : ''
                } ${
                  peers.length === 1 ? 'grid-cols-1 md:grid-cols-2 max-w-5xl' : ''
                } ${
                  peers.length >= 2 && peers.length <= 3 ? 'grid-cols-1 md:grid-cols-2 max-w-6xl' : ''
                } ${
                  peers.length >= 4 ? 'grid-cols-2 md:grid-cols-3 max-w-7xl' : ''
                }`}>
                  <VideoTile
                    stream={localStream}
                    isLocal={true}
                    displayName={localDisplayName}
                    isHost={isHost}
                    micEnabled={micEnabled}
                    camEnabled={camEnabled}
                    onSpotlightToggle={() => {
                      setSpotlightPeerId('local');
                      setLayoutMode('spotlight');
                    }}
                  />
                  {peers.map((peer) => (
                    <VideoTile
                      key={peer.peerId}
                      stream={peer.stream}
                      displayName={peer.displayName}
                      micEnabled={peerMediaState.get(peer.peerId)?.micEnabled ?? true}
                      camEnabled={peerMediaState.get(peer.peerId)?.camEnabled ?? true}
                      onSpotlightToggle={() => {
                        setSpotlightPeerId(peer.peerId);
                        setLayoutMode('spotlight');
                      }}
                    />
                  ))}
                </div>
              )}

              {/* WebRTC SFU Stats Overlay Panel */}
              {showStats && metrics && (
                <div className="absolute top-4 left-4 right-4 bg-zinc-950/95 backdrop-blur-2xl border border-emerald-500/30 p-5 rounded-2xl shadow-2xl z-50 text-white max-w-3xl mx-auto ring-1 ring-white/10">
                  <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
                    <div className="flex items-center gap-2 text-sm font-bold text-emerald-400">
                      <Activity className="w-4 h-4 text-emerald-400" />
                      {t('conference.page.metricsTitle')}
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-gray-400 hover:text-white" onClick={() => setShowStats(false)}>
                      ✕
                    </Button>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div className="bg-zinc-900 p-3 rounded-xl border border-white/5">
                      <div className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mb-1">Target Video</div>
                      <div className={`font-mono text-base font-bold ${metrics.starvationMode ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {(metrics.effectiveTargetVideoBitrateBps / 1_000_000).toFixed(2)} Mbps
                      </div>
                    </div>
                    <div className="bg-zinc-900 p-3 rounded-xl border border-white/5">
                      <div className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mb-1">Bitrate</div>
                      <div className="font-mono text-base font-bold text-gray-200">
                        {((metrics.currentVideoBitrateBps + metrics.currentAudioBitrateBps) / 1_000_000).toFixed(2)} Mbps
                      </div>
                    </div>
                    <div className="bg-zinc-900 p-3 rounded-xl border border-white/5">
                      <div className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mb-1">Codec</div>
                      <div className="font-mono text-base font-bold text-sky-400">{metrics.codec || 'VP8/H264'}</div>
                    </div>
                    <div className="bg-zinc-900 p-3 rounded-xl border border-white/5">
                      <div className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mb-1">Packet Loss</div>
                      <div className="font-mono text-base font-bold text-rose-400">{(metrics.packetLossRate * 100).toFixed(1)}%</div>
                    </div>
                  </div>
                </div>
              )}
            </main>

            {/* Right Collapsible Sidebar */}
            {showSidebar && (
              <aside className="w-80 bg-[#121316] border-l border-white/10 flex flex-col shrink-0 z-20 shadow-2xl">
                <div className="p-3 border-b border-white/10 bg-[#16171b] flex items-center justify-between">
                  <div className="flex gap-2">
                    <button
                      onClick={() => setActiveTab('participants')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        activeTab === 'participants' ? 'bg-emerald-600 text-white shadow-sm' : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      <Users className="w-3.5 h-3.5" />
                      {t('conference.page.participantsCount', { count: participants.size + 1 })}
                    </button>
                    <button
                      onClick={() => setActiveTab('chat')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        activeTab === 'chat' ? 'bg-emerald-600 text-white shadow-sm' : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      <MessageSquare className="w-3.5 h-3.5" />
                      {t('conference.page.chat')}
                    </button>
                  </div>
                  <Button variant="ghost" size="icon" className="h-6 w-6 text-gray-400 hover:text-white" onClick={() => setShowSidebar(false)}>
                    ✕
                  </Button>
                </div>

                {/* Host Quick Moderation Toolbar Bar */}
                {isHost && activeTab === 'participants' && (
                  <div className="p-2.5 bg-amber-500/10 border-b border-amber-500/20 flex items-center justify-between gap-1 text-xs">
                    <span className="font-bold text-amber-300 text-[11px]">{t('conference.page.moderation')}</span>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleHostMuteAll}
                        className="h-7 px-2 text-[10px] bg-black/40 hover:bg-black/60 text-amber-200 border border-amber-500/20 rounded font-semibold"
                      >
                        <MicOff className="w-3 h-3 mr-1 text-rose-400" /> {t('conference.page.muteAll')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleHostLockToggle}
                        className={`h-7 px-2 text-[10px] rounded font-semibold border ${
                          roomSettings.lockRoom ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' : 'bg-black/40 text-amber-200 border-amber-500/20'
                        }`}
                      >
                        {roomSettings.lockRoom ? <Lock className="w-3 h-3 mr-1 text-rose-400" /> : <Unlock className="w-3 h-3 mr-1 text-emerald-400" />}
                        {roomSettings.lockRoom ? t('conference.page.lockedShort') : t('conference.page.lockAction')}
                      </Button>
                    </div>
                  </div>
                )}

                {/* Tab 1: Participants List */}
                {activeTab === 'participants' && (
                  <div className="flex-1 overflow-y-auto p-3 space-y-2">
                    <div className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">{t('conference.page.onAir', { count: participants.size })}</div>
                    
                    {/* Local user entry */}
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white/5 border border-white/5">
                      <div className="flex items-center gap-2.5 truncate">
                        <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center font-bold text-white text-xs">
                          {localDisplayName.charAt(0)}
                        </div>
                        <div className="flex flex-col truncate">
                          <span className="text-xs font-semibold text-gray-200 truncate flex items-center gap-1">
                            {localDisplayName} {t('conference.page.youParen')}
                            {isHost && <Crown className="w-3 h-3 text-amber-400" />}
                          </span>
                          <span className="text-[10px] text-emerald-400 font-mono">
                            {isHost ? t('conference.page.host') : t('conference.media.participant')}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 text-gray-400">
                        {micEnabled ? <Mic className="w-3.5 h-3.5 text-emerald-400" /> : <MicOff className="w-3.5 h-3.5 text-rose-400" />}
                        {camEnabled ? <Video className="w-3.5 h-3.5 text-emerald-400" /> : <VideoOff className="w-3.5 h-3.5 text-zinc-500" />}
                      </div>
                    </div>

                    {/* Remote users list */}
                    {Array.from(participants.entries()).map(([peerId, name]) => (
                      <div key={peerId} className="flex items-center justify-between p-2.5 rounded-xl hover:bg-white/5 border border-transparent transition-colors group">
                        <div className="flex items-center gap-2.5 truncate">
                          <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center font-bold text-white text-xs">
                            {name.charAt(0).toUpperCase()}
                          </div>
                          <span className="text-xs font-medium text-gray-300 truncate">{name}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          {peerMediaState.get(peerId)?.micEnabled === false ? (
                            <MicOff className="w-3.5 h-3.5 text-rose-400" />
                          ) : (
                            <Mic className="w-3.5 h-3.5 text-emerald-400" />
                          )}
                          {isHost && (
                            <Popover>
                              <PopoverTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-6 w-6 text-gray-400 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity">
                                  <Sliders className="w-3 h-3" />
                                </Button>
                              </PopoverTrigger>
                              <PopoverContent side="left" className="w-44 bg-zinc-900 border-zinc-800 p-2 text-xs text-white">
                                <div className="flex flex-col gap-1">
                                  <button onClick={() => toast({ description: t('conference.page.participantMuted', { name }) })} className="flex items-center gap-2 p-1.5 rounded hover:bg-white/10 text-rose-300">
                                    <MicOff className="w-3.5 h-3.5" /> {t('conference.page.muteOne')}
                                  </button>
                                  <button onClick={() => toast({ description: t('conference.page.participantKicked', { name }) })} className="flex items-center gap-2 p-1.5 rounded hover:bg-white/10 text-rose-400 font-bold">
                                    <UserX className="w-3.5 h-3.5" /> {t('conference.page.kick')}
                                  </button>
                                </div>
                              </PopoverContent>
                            </Popover>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Tab 2: In-Call Text Chat */}
                {activeTab === 'chat' && (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="flex-1 overflow-y-auto p-3 space-y-3">
                      {chatMessages.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-full text-center text-gray-500 p-4">
                          <MessageSquare className="w-8 h-8 mb-2 opacity-50 text-emerald-400" />
                          <p className="text-xs">{t('conference.page.chatEmpty')}</p>
                        </div>
                      ) : (
                        chatMessages.map((msg) => (
                          <div key={msg.id} className={`flex flex-col ${msg.isSelf ? 'items-end' : 'items-start'}`}>
                            <div className="flex items-center gap-1.5 text-[10px] text-gray-400 mb-1">
                              <span className="font-semibold text-gray-300">{msg.sender}</span>
                              <span>• {msg.timestamp}</span>
                            </div>
                            <div className={`p-2.5 rounded-2xl text-xs max-w-[85%] leading-relaxed ${
                              msg.isSelf ? 'bg-emerald-600 text-white rounded-tr-none' : 'bg-zinc-800 text-gray-200 rounded-tl-none border border-white/10'
                            }`}>
                              {msg.text}
                            </div>
                          </div>
                        ))
                      )}
                    </div>

                    <form onSubmit={handleSendChatMessage} className="p-3 border-t border-white/10 bg-[#16171b] flex gap-2">
                      <Input
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        placeholder={roomSettings.allowChat || isHost ? t('conference.page.chatPlaceholder') : t('conference.page.chatDisabledPlaceholder')}
                        disabled={!roomSettings.allowChat && !isHost}
                        className="h-9 bg-zinc-900 border-white/10 text-xs text-white placeholder:text-gray-500 focus-visible:ring-emerald-500"
                      />
                      <Button type="submit" size="icon" disabled={!roomSettings.allowChat && !isHost} className="h-9 w-9 bg-emerald-600 hover:bg-emerald-700 text-white shrink-0">
                        <Send className="w-3.5 h-3.5" />
                      </Button>
                    </form>
                  </div>
                )}
              </aside>
            )}
          </div>

          {/* Floating Bottom Control Dock */}
          <footer className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-[#16171a]/90 backdrop-blur-2xl border border-white/15 rounded-2xl p-2.5 flex items-center gap-3 shadow-2xl z-40">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  onClick={toggleMic}
                  className={`h-12 px-4 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all shadow-md ${
                    !micEnabled ? 'bg-rose-600 hover:bg-rose-700 text-white shadow-rose-900/40' : 'bg-zinc-800 hover:bg-zinc-700 text-gray-100 border border-white/10'
                  }`}
                >
                  {!micEnabled ? <MicOff className="w-4 h-4 text-white" /> : <Mic className="w-4 h-4 text-emerald-400" />}
                  <span className="hidden sm:inline">{!micEnabled ? t('conference.page.unmuteShort') : t('conference.page.muteShort')}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{micEnabled ? t('conference.page.micOff') : t('conference.page.micOn')}</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  onClick={toggleCam}
                  className={`h-12 px-4 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all shadow-md ${
                    !camEnabled ? 'bg-rose-600 hover:bg-rose-700 text-white shadow-rose-900/40' : 'bg-zinc-800 hover:bg-zinc-700 text-gray-100 border border-white/10'
                  }`}
                >
                  {!camEnabled ? <VideoOff className="w-4 h-4 text-white" /> : <Video className="w-4 h-4 text-emerald-400" />}
                  <span className="hidden sm:inline">{!camEnabled ? t('conference.page.camOnShort') : t('conference.page.camOffShort')}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{camEnabled ? t('conference.page.camOff') : t('conference.page.camOn')}</TooltipContent>
            </Tooltip>

            <div className="w-px h-7 bg-white/10 my-auto" />

            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  variant="ghost"
                  onClick={() => setShowStats(!showStats)}
                  className={`h-12 w-12 rounded-xl flex items-center justify-center transition-colors ${
                    showStats ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'text-gray-300 hover:bg-white/10'
                  }`}
                >
                  <Settings className="w-5 h-5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('conference.page.qualityStats')}</TooltipContent>
            </Tooltip>

            <Button 
              variant="destructive" 
              onClick={handleLeave}
              className="h-12 px-6 rounded-xl bg-gradient-to-r from-rose-600 to-red-700 hover:from-rose-700 hover:to-red-800 text-white shadow-lg shadow-rose-900/40 font-bold flex items-center gap-2 border border-rose-500/30 ml-2"
            >
              <PhoneOff className="w-4 h-4" />
              <span>{t('conference.page.leave')}</span>
            </Button>
          </footer>

          {/* Deep Room Settings Dialog (For Creator/Host) */}
          <Dialog open={showSettingsModal} onOpenChange={setShowSettingsModal}>
            <DialogContent className="max-w-2xl bg-zinc-950 border-zinc-800 text-white p-6 rounded-3xl shadow-2xl max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold flex items-center gap-2 text-emerald-400">
                  <SlidersHorizontal className="w-5 h-5" />
                  {t('conference.page.settingsDialogTitle')}
                </DialogTitle>
                <DialogDescription className="text-xs text-zinc-400">
                  {t('conference.page.settingsDialogHint')}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* Presets Bar */}
                <div className="p-4 bg-muted/20 rounded-2xl border border-white/10 space-y-3">
                  <span className="text-xs font-bold text-gray-300 uppercase tracking-wider block">{t('conference.page.presetsLabel')}</span>
                  <div className="grid grid-cols-3 gap-2">
                    <Button variant="outline" size="sm" onClick={() => applyPreset('webinar')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetWebinar')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => applyPreset('meeting')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetMeeting')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => applyPreset('private')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetPrivate')}
                    </Button>
                  </div>
                </div>

                {/* Section 1: Security & Protection */}
                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Shield className="w-4 h-4" /> {t('conference.page.securitySection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.waitingRoom')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.waitingRoomHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.enableWaitingRoom}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, enableWaitingRoom: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.lockRoom')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.lockRoomHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.lockRoom}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, lockRoom: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 col-span-full">
                      <div className="space-y-1 flex-1 pr-4">
                        <div className="flex items-center justify-between">
                          <Label className="text-xs font-semibold">{t('conference.page.pinProtection')}</Label>
                          <Switch
                            checked={roomSettings.passwordProtection}
                            onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, passwordProtection: checked })}
                          />
                        </div>
                        {roomSettings.passwordProtection && (
                          <Input
                            value={roomSettings.passwordPin}
                            onChange={(e) => saveRoomSettings({ ...roomSettings, passwordPin: e.target.value })}
                            placeholder={t('conference.page.pinPlaceholder')}
                            className="h-9 mt-2 bg-zinc-950 border-zinc-800 text-xs font-mono"
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Section 2: Default Participant Rights */}
                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Users className="w-4 h-4" /> {t('conference.page.entryRightsSection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.muteOnEntry')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.muteOnEntryHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.muteOnEntry}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, muteOnEntry: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.videoOffOnEntry')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.videoOffOnEntryHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.disableVideoOnEntry}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, disableVideoOnEntry: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.textChat')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.textChatHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.allowChat}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, allowChat: checked })}
                      />
                    </div>

                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.screenShare')}</Label>
                      <Select
                        value={roomSettings.allowScreenShare}
                        onValueChange={(val: 'all' | 'host_only') => saveRoomSettings({ ...roomSettings, allowScreenShare: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="all" className="text-xs">{t('conference.page.screenShareAll')}</SelectItem>
                          <SelectItem value="host_only" className="text-xs">{t('conference.page.screenShareHost')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>

                {/* Section 3: Media Stream & SFU Quality */}
                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Zap className="w-4 h-4" /> {t('conference.page.qualitySection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.resolution')}</Label>
                      <Select
                        value={roomSettings.videoQuality}
                        onValueChange={(val: '1080p' | '720p' | '480p') => saveRoomSettings({ ...roomSettings, videoQuality: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="1080p" className="text-xs">1080p Full HD (4 Mbps)</SelectItem>
                          <SelectItem value="720p" className="text-xs">720p HD (2 Mbps)</SelectItem>
                          <SelectItem value="480p" className="text-xs">480p SD (1 Mbps)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.codec')}</Label>
                      <Select
                        value={roomSettings.codecPreference}
                        onValueChange={(val: 'auto' | 'vp8' | 'h264') => saveRoomSettings({ ...roomSettings, codecPreference: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="auto" className="text-xs">{t('conference.page.codecAuto')}</SelectItem>
                          <SelectItem value="vp8" className="text-xs">{t('conference.page.codecVp8')}</SelectItem>
                          <SelectItem value="h264" className="text-xs">H.264 Baseline</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button onClick={() => setShowSettingsModal(false)} className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold">
                  {t('conference.page.saveSettings')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

        </div>
      </TooltipProvider>
    );
  }

  // ═══════════════════════════════════════════════════════════
  // PRE-JOIN LOBBY INTERFACE (NOT CONNECTED STATE)
  // ═══════════════════════════════════════════════════════════
  return (
    <TooltipProvider>
      <div className="min-h-screen bg-background text-foreground flex flex-col relative overflow-hidden">
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[400px] bg-primary/10 blur-[140px] rounded-full pointer-events-none -translate-y-1/2" />
      <div className="absolute bottom-0 right-0 w-[600px] h-[600px] bg-secondary/10 blur-[160px] rounded-full pointer-events-none translate-y-1/3" />
      
      <Header />
      <main className="flex-1 container mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col items-center justify-center relative z-10">
        
        {/* Page Hero Header */}
        <div className="w-full max-w-4xl mb-8">
          <BackToProfile className="mb-6" />
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-border/40">
            <div className="flex items-center gap-4">
              <div className="p-4 bg-gradient-to-br from-primary/20 to-primary/5 rounded-2xl ring-1 ring-primary/30 shadow-[0_0_30px_hsl(var(--primary)/0.2)]">
                <Video className="w-9 h-9 text-primary animate-pulse-glow" />
              </div>
              <div>
                <h1 className="text-3xl sm:text-4xl font-bold font-display tracking-tight text-foreground">
                  {t('conference.join.defaultTitle')}
                </h1>
                <p className="text-muted-foreground mt-1 text-base font-medium">
                  {t('conference.page.landingSubtitle')}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="gap-1.5 py-1 px-3 bg-primary/10 text-primary border-primary/20">
                <Shield className="w-3.5 h-3.5" /> {t('conference.page.badgeP2p')}
              </Badge>
              <Badge variant="secondary" className="gap-1.5 py-1 px-3 bg-secondary/10 text-secondary-foreground border-secondary/20">
                <Zap className="w-3.5 h-3.5" /> {t('conference.page.badgeSfu')}
              </Badge>
            </div>
          </div>
        </div>

        <div className="w-full max-w-4xl">

          {/* STATE A: ROOM NOT YET SELECTED (MAIN ENTRY LOBBY) */}
          {!isRoomSelected && (
            <Card className="glass shadow-elevated border-white/10 dark:bg-zinc-950/60 rounded-3xl overflow-hidden backdrop-blur-xl">
              <CardContent className="p-6 md:p-10">
                <Tabs defaultValue="create" className="w-full">
                  <TabsList className="grid grid-cols-2 w-full max-w-md mx-auto mb-8 h-12 bg-muted/50 p-1 rounded-xl">
                    <TabsTrigger value="create" className="rounded-lg font-semibold text-sm">
                      <Plus className="w-4 h-4 mr-2" />
                      {t('conference.page.tabCreate')}
                    </TabsTrigger>
                    <TabsTrigger value="join" className="rounded-lg font-semibold text-sm">
                      <LogIn className="w-4 h-4 mr-2" />
                      {t('conference.page.tabJoin')}
                    </TabsTrigger>
                  </TabsList>

                  {/* Create Room Tab Content */}
                  <TabsContent value="create" className="space-y-6">
                    <div className="p-8 bg-muted/20 rounded-2xl border border-dashed border-primary/20 text-center flex flex-col items-center justify-center gap-4">
                      <div className="p-5 bg-background shadow-lg rounded-2xl text-primary ring-1 ring-border">
                        <MonitorPlay className="w-10 h-10" />
                      </div>
                      <div className="max-w-lg">
                        <h3 className="font-bold text-2xl tracking-tight">{t('conference.page.newRoomTitle')}</h3>
                        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                          {t('conference.page.newRoomHint')}
                        </p>
                      </div>

                      <div className="flex flex-col sm:flex-row gap-3 mt-2">
                        <Button
                          onClick={handleCreateRoomRoute}
                          size="lg"
                          className="h-14 px-8 text-base font-bold rounded-xl shadow-xl hover:shadow-primary/30 transition-all btn-primary"
                        >
                          <Sparkles className="w-5 h-5 mr-2" />
                          {t('conference.page.createRoom')}
                        </Button>
                        <Button
                          onClick={() => setShowSettingsModal(true)}
                          size="lg"
                          variant="outline"
                          className="h-14 px-6 text-sm font-bold rounded-xl border-2 border-primary/30"
                        >
                          <SlidersHorizontal className="w-4 h-4 mr-2 text-primary" />
                          {t('conference.page.configure')}
                        </Button>
                      </div>
                    </div>
                  </TabsContent>

                  {/* Join Room Tab Content */}
                  <TabsContent value="join" className="space-y-6">
                    <div className="p-8 bg-muted/20 rounded-2xl border border-dashed border-primary/20 flex flex-col items-center justify-center text-center gap-5">
                      <div className="p-4 bg-background shadow-lg rounded-full text-secondary ring-1 ring-border">
                        <LogIn className="w-8 h-8" />
                      </div>
                      <div className="max-w-md">
                        <h3 className="font-bold text-xl tracking-tight">{t('conference.page.joinByIdTitle')}</h3>
                        <p className="text-muted-foreground mt-1 text-sm">
                          {t('conference.page.joinByIdHint')}
                        </p>
                      </div>

                      <div className="flex flex-col sm:flex-row gap-3 w-full max-w-md">
                        <Input
                          value={joinRoomInput}
                          onChange={(e) => setJoinRoomInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleGoToRoom()}
                          placeholder={t('conference.page.roomIdPlaceholder')}
                          className="h-14 rounded-xl bg-background/80 border-border font-mono text-center text-lg font-bold focus-visible:ring-primary"
                        />
                        <Button
                          onClick={handleGoToRoom}
                          size="lg"
                          className="h-14 px-8 font-bold rounded-xl shrink-0 btn-primary"
                        >
                          {t('conference.notify.join')} <LogIn className="w-4 h-4 ml-2" />
                        </Button>
                      </div>
                    </div>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          )}

          {/* STATE B: ROOM IS SELECTED (PRE-CALL MEDIA & DEVICE CHECK LOBBY) */}
          {isRoomSelected && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Left Side: Live Media Preview */}
              <div className="lg:col-span-7 flex flex-col gap-4">
                <Card className="glass shadow-elevated border-white/10 dark:bg-zinc-950/60 rounded-3xl overflow-hidden backdrop-blur-xl">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-lg font-bold flex items-center justify-between">
                      <span>{t('conference.page.previewTitle')}</span>
                      <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                        <CheckCircle2 className="w-3 h-3 mr-1" /> {t('conference.page.previewBadge')}
                      </Badge>
                    </CardTitle>
                    <CardDescription className="text-xs">
                      {t('conference.page.previewHint')}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-4">
                    <div className="relative aspect-video bg-zinc-900 rounded-2xl overflow-hidden ring-1 ring-white/10 shadow-lg flex items-center justify-center">
                      <div ref={previewRingRef} className="absolute inset-0 pointer-events-none rounded-2xl border-2 border-transparent transition-all z-20" />
                      
                      {previewActive && previewCamEnabled ? (
                        <video
                          ref={previewVideoRef}
                          autoPlay
                          playsInline
                          muted
                          className="w-full h-full object-cover scale-x-[-1]"
                        />
                      ) : (
                        // pb-20 — запас под плавающую панель с микрофоном и
                        // камерой: она приклеена к низу этого же контейнера и
                        // без отступа накрывает кнопку.
                        <div className="flex flex-col items-center justify-center px-6 pt-6 pb-20 text-center">
                          <div className="w-20 h-20 rounded-full bg-emerald-700/40 ring-4 ring-emerald-500/20 flex items-center justify-center text-white text-3xl font-bold font-display mb-3">
                            {user?.firstName?.charAt(0) || 'Y'}
                          </div>
                          {previewActive ? (
                            <span className="text-xs text-gray-400">{t('conference.page.cameraOff')}</span>
                          ) : (
                            <>
                              {/* Не «камера выключена»: иконки на панели ниже
                                  в этот момент горят зелёным (они про то, с
                                  чем войти в звонок), и две надписи спорили бы
                                  друг с другом. Здесь речь именно о
                                  предпросмотре. */}
                              <span className="text-xs text-gray-400 mb-4 max-w-xs">
                                {t('conference.page.previewOff')}
                              </span>
                              <Button
                                size="sm"
                                className="rounded-xl bg-emerald-600 text-white hover:bg-emerald-700"
                                onClick={() => {
                                  setPreviewError(null);
                                  setPreviewActive(true);
                                }}
                              >
                                <Video className="w-4 h-4 mr-2" />
                                {t('conference.page.startPreview')}
                              </Button>
                              {previewError && (
                                <span className="mt-3 max-w-xs text-xs text-rose-400">
                                  {previewError}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                      )}

                      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/70 backdrop-blur-md px-4 py-2 rounded-2xl border border-white/10 flex items-center gap-3 z-30">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={togglePreviewMic}
                          title={previewActive
                            ? (previewMicEnabled ? t('conference.page.micOff') : t('conference.page.micOn'))
                            : (previewMicEnabled ? t('conference.page.joinWithMicOn') : t('conference.page.joinWithMicOff'))}
                          className={`h-10 w-10 rounded-xl transition-colors ${
                            !previewMicEnabled ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-white/10 text-white hover:bg-white/20'
                          }`}
                        >
                          {!previewMicEnabled ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4 text-emerald-400" />}
                        </Button>

                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={togglePreviewCam}
                          title={previewActive
                            ? (previewCamEnabled ? t('conference.page.camOff') : t('conference.page.camOn'))
                            : (previewCamEnabled ? t('conference.page.joinWithCamOn') : t('conference.page.joinWithCamOff'))}
                          className={`h-10 w-10 rounded-xl transition-colors ${
                            !previewCamEnabled ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-white/10 text-white hover:bg-white/20'
                          }`}
                        >
                          {!previewCamEnabled ? <VideoOff className="w-4 h-4" /> : <Video className="w-4 h-4 text-emerald-400" />}
                        </Button>
                      </div>
                    </div>

                    <div className="p-3 bg-muted/30 rounded-xl border border-border/40 flex items-center justify-between gap-4">
                      <div className="flex items-center gap-2 text-xs font-medium">
                        {previewMicEnabled ? (
                          <Mic className="w-4 h-4 text-emerald-500" />
                        ) : (
                          <MicOff className="w-4 h-4 text-rose-500" />
                        )}
                        <span>{previewMicEnabled ? t('conference.page.micWorking') : t('conference.page.micOffState')}</span>
                      </div>

                      <div className="flex items-center gap-1 h-4 w-24">
                        {[20, 40, 60, 80, 100].map((threshold, idx) => (
                          <div
                            key={idx}
                            className={`flex-1 rounded-full transition-all duration-100 ${
                              previewAudioLevel >= threshold
                                ? 'bg-emerald-500 h-full'
                                : 'bg-border/60 h-2'
                            }`}
                          />
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Right Side: Room Info & Join Actions */}
              <div className="lg:col-span-5 flex flex-col justify-between gap-4">
                <Card className="glass shadow-elevated border-white/10 dark:bg-zinc-950/60 rounded-3xl overflow-hidden backdrop-blur-xl flex-1 flex flex-col">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-xl font-bold">{t('conference.page.readiness')}</CardTitle>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowSettingsModal(true)}
                        className="h-9 px-3 text-xs bg-primary/10 hover:bg-primary/20 text-primary border-primary/30 font-bold rounded-xl shadow-sm"
                      >
                        <SlidersHorizontal className="w-4 h-4 mr-1.5" />
                        {t('profile.settings')}
                      </Button>
                    </div>
                    <CardDescription className="text-xs">
                      {t('conference.page.isolatedRoomHint')}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="flex-1 flex flex-col justify-between gap-5">
                    {/* Room ID Box */}
                    <div className="p-4 bg-muted/30 rounded-2xl border border-border/50 flex flex-col gap-2.5">
                      <span className="text-xs font-medium text-muted-foreground">{t('conference.page.roomIdLabel')}</span>
                      <div className="flex items-center justify-between bg-background p-3 rounded-xl border border-border shadow-inner">
                        <span className="font-mono text-xl text-primary font-bold tracking-wider">{activeRoomId}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleCopyRoomId}
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                      </div>
                      {/* Диктовать идентификатор больше не нужно — и, главное,
                          внешнего участника иначе не позвать вовсе. */}
                      <Button
                        variant="secondary"
                        className="rounded-xl"
                        onClick={() => setInviteOpen(true)}
                      >
                        <Link2 className="mr-2 h-4 w-4" />
                        {t('conference.page.inviteByLink')}
                      </Button>
                    </div>

                    {/* Room Active Settings Pills Box */}
                    <div 
                      onClick={() => setShowSettingsModal(true)}
                      className="p-3.5 bg-muted/20 hover:bg-muted/30 transition-colors rounded-2xl border border-border/50 cursor-pointer space-y-2 group"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-foreground flex items-center gap-1.5">
                          <SlidersHorizontal className="w-3.5 h-3.5 text-primary" /> {t('conference.page.meetingParams')}
                        </span>
                        <span className="text-[11px] font-medium text-primary group-hover:underline">{t('conference.page.configureArrow')}</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge variant="outline" className="text-[10px] py-0.5 px-2 bg-background/80">
                          {t('conference.page.qualityBadge', { quality: roomSettings.videoQuality })}
                        </Badge>
                        <Badge variant="outline" className={`text-[10px] py-0.5 px-2 ${roomSettings.enableWaitingRoom ? 'bg-amber-500/10 text-amber-600 border-amber-500/30' : 'bg-background/80'}`}>
                          🛡️ {t('conference.page.waitingRoom')}: {roomSettings.enableWaitingRoom ? t('common.onShort') : t('common.offShort')}
                        </Badge>
                        <Badge variant="outline" className={`text-[10px] py-0.5 px-2 ${roomSettings.passwordProtection ? 'bg-amber-500/10 text-amber-600 border-amber-500/30' : 'bg-background/80'}`}>
                          🔑 PIN: {roomSettings.passwordProtection ? t('common.onShort') : t('common.offShort')}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] py-0.5 px-2 bg-background/80">
                          🎙️ {t('conference.page.muteOnEntry')}: {roomSettings.muteOnEntry ? t('common.onShort') : t('common.offShort')}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] py-0.5 px-2 bg-background/80">
                          {t('conference.page.screenBadge', { who: roomSettings.allowScreenShare === 'all' ? t('common.all') : 'Host' })}
                        </Badge>
                      </div>
                    </div>

                    {/* PIN input if protection is enabled */}
                    {!isHost && roomSettings.passwordProtection && (
                      <div className="p-3.5 bg-amber-500/10 rounded-xl border border-amber-500/20 space-y-2">
                        <Label className="text-xs font-bold text-amber-700 dark:text-amber-300 flex items-center gap-1">
                          <Lock className="w-3.5 h-3.5" /> {t('conference.page.enterPinTitle')}
                        </Label>
                        <Input
                          type="password"
                          value={enteredPasswordInput}
                          onChange={(e) => setEnteredPasswordInput(e.target.value)}
                          placeholder={t('conference.page.hostPasswordPlaceholder')}
                          className="h-10 bg-background border-amber-500/30 text-sm font-mono text-center font-bold"
                        />
                      </div>
                    )}

                    {/* User Profile Container */}
                    <div className="flex items-center gap-3 p-3 bg-primary/5 rounded-xl border border-primary/10">
                      <div className="w-10 h-10 rounded-full bg-primary flex items-center justify-center font-bold text-primary-foreground text-sm shadow-md">
                        {user?.firstName?.charAt(0) || 'U'}
                      </div>
                      <div className="truncate">
                        <div className="text-xs text-muted-foreground">{t('conference.page.joiningAs')}</div>
                        <div className="text-sm font-bold text-foreground flex items-center gap-1.5 truncate">
                          <span className="truncate">{user?.firstName ? `${user.firstName} ${user.lastName || ''}` : user?.email || t('conference.page.guest')}</span>
                          {isHost && <Crown className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
                        </div>
                      </div>
                    </div>

                    {/* Action buttons */}
                    <div className="flex flex-col gap-3">
                      <Button
                        onClick={handleJoin}
                        size="lg"
                        className="w-full text-base sm:text-lg h-14 sm:h-16 font-bold shadow-xl rounded-xl btn-primary shadow-primary/25 leading-snug whitespace-normal px-4 py-2"
                      >
                        {t('conference.page.joinConference')}
                      </Button>
                      <Button
                        onClick={() => navigate('/conference')}
                        size="lg"
                        variant="outline"
                        className="w-full text-sm h-11 font-medium rounded-xl border-2"
                      >
                        {t('conference.page.leaveWaitingRoom')}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </div>

            </div>
          )}

          {/* Deep Room Settings Dialog */}
          <Dialog open={showSettingsModal} onOpenChange={setShowSettingsModal}>
            <DialogContent className="max-w-2xl bg-zinc-950 border-zinc-800 text-white p-6 rounded-3xl shadow-2xl max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold flex items-center gap-2 text-emerald-400">
                  <SlidersHorizontal className="w-5 h-5" />
                  {t('conference.page.settingsDialogTitle')}
                </DialogTitle>
                <DialogDescription className="text-xs text-zinc-400">
                  {t('conference.page.settingsDialogHint')}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                <div className="p-4 bg-muted/20 rounded-2xl border border-white/10 space-y-3">
                  <span className="text-xs font-bold text-gray-300 uppercase tracking-wider block">{t('conference.page.presetsLabel')}</span>
                  <div className="grid grid-cols-3 gap-2">
                    <Button variant="outline" size="sm" onClick={() => applyPreset('webinar')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetWebinar')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => applyPreset('meeting')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetMeeting')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => applyPreset('private')} className="text-xs bg-zinc-900 hover:bg-zinc-800 border-white/10">
                      {t('conference.page.presetPrivate')}
                    </Button>
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Shield className="w-4 h-4" /> {t('conference.page.securitySection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.waitingRoom')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.waitingRoomHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.enableWaitingRoom}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, enableWaitingRoom: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.lockRoom')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.lockRoomHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.lockRoom}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, lockRoom: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 col-span-full">
                      <div className="space-y-1 flex-1 pr-4">
                        <div className="flex items-center justify-between">
                          <Label className="text-xs font-semibold">{t('conference.page.pinProtection')}</Label>
                          <Switch
                            checked={roomSettings.passwordProtection}
                            onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, passwordProtection: checked })}
                          />
                        </div>
                        {roomSettings.passwordProtection && (
                          <Input
                            value={roomSettings.passwordPin}
                            onChange={(e) => saveRoomSettings({ ...roomSettings, passwordPin: e.target.value })}
                            placeholder={t('conference.page.pinPlaceholder')}
                            className="h-9 mt-2 bg-zinc-950 border-zinc-800 text-xs font-mono"
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Users className="w-4 h-4" /> {t('conference.page.entryRightsSection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.muteOnEntry')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.muteOnEntryHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.muteOnEntry}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, muteOnEntry: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.videoOffOnEntry')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.videoOffOnEntryHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.disableVideoOnEntry}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, disableVideoOnEntry: checked })}
                      />
                    </div>

                    <div className="flex items-center justify-between p-3.5 bg-zinc-900/60 rounded-xl border border-white/5">
                      <div className="space-y-0.5">
                        <Label className="text-xs font-semibold">{t('conference.page.textChat')}</Label>
                        <p className="text-[11px] text-zinc-400">{t('conference.page.textChatHint')}</p>
                      </div>
                      <Switch
                        checked={roomSettings.allowChat}
                        onCheckedChange={(checked) => saveRoomSettings({ ...roomSettings, allowChat: checked })}
                      />
                    </div>

                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.screenShare')}</Label>
                      <Select
                        value={roomSettings.allowScreenShare}
                        onValueChange={(val: 'all' | 'host_only') => saveRoomSettings({ ...roomSettings, allowScreenShare: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="all" className="text-xs">{t('conference.page.screenShareAll')}</SelectItem>
                          <SelectItem value="host_only" className="text-xs">{t('conference.page.screenShareHost')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Zap className="w-4 h-4" /> {t('conference.page.qualitySection')}
                  </h4>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.resolution')}</Label>
                      <Select
                        value={roomSettings.videoQuality}
                        onValueChange={(val: '1080p' | '720p' | '480p') => saveRoomSettings({ ...roomSettings, videoQuality: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="1080p" className="text-xs">1080p Full HD (4 Mbps)</SelectItem>
                          <SelectItem value="720p" className="text-xs">720p HD (2 Mbps)</SelectItem>
                          <SelectItem value="480p" className="text-xs">480p SD (1 Mbps)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="p-3.5 bg-zinc-900/60 rounded-xl border border-white/5 space-y-1.5">
                      <Label className="text-xs font-semibold">{t('conference.page.codec')}</Label>
                      <Select
                        value={roomSettings.codecPreference}
                        onValueChange={(val: 'auto' | 'vp8' | 'h264') => saveRoomSettings({ ...roomSettings, codecPreference: val })}
                      >
                        <SelectTrigger className="h-8 bg-zinc-950 border-zinc-800 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-zinc-900 border-zinc-800 text-white">
                          <SelectItem value="auto" className="text-xs">{t('conference.page.codecAuto')}</SelectItem>
                          <SelectItem value="vp8" className="text-xs">{t('conference.page.codecVp8')}</SelectItem>
                          <SelectItem value="h264" className="text-xs">H.264 Baseline</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button onClick={() => setShowSettingsModal(false)} className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold">
                  {t('conference.page.saveSettings')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

        </div>
      </main>
      </div>
      {isRoomSelected && (
        <InviteDialog roomId={activeRoomId} open={inviteOpen} onOpenChange={setInviteOpen} />
      )}

      </TooltipProvider>
    );
};

export default ConferencePage;
