import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Header } from '@/components/Header';
import { WebRTCManager, RemoteStream, QualityMetrics, WebRTCError } from '@/lib/webrtc';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { 
  Video, VideoOff, Mic, MicOff, PhoneOff, 
  MonitorPlay, Settings, Activity, ArrowLeft, Copy, Plus, LogIn,
  Volume2, VolumeX
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';
import { UserProfile } from '@/types/userProfile';
import { useToast } from '@/hooks/use-toast';
import { Slider } from '@/components/ui/slider';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { getAccessToken } from '@/lib/auth/profileStorage';

type ConferenceRuntimeConfig = {
  sfu_signaling_url: string;
  sfu_signaling_path?: string;
  ice_servers?: Array<{
    urls: string | string[];
    username?: string;
    credential?: string;
  }>;
};

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
    return {
      url: originFallbackUrl,
      source: 'origin',
      reason: 'backend url is empty',
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(rawBackendUrl);
  } catch {
    return {
      url: originFallbackUrl,
      source: 'origin',
      reason: 'backend url is invalid',
    };
  }

  const protocol = parsed.protocol.toLowerCase();
  if (protocol === 'http:') {
    parsed.protocol = 'ws:';
  } else if (protocol === 'https:') {
    parsed.protocol = 'wss:';
  } else if (protocol !== 'ws:' && protocol !== 'wss:') {
    return {
      url: originFallbackUrl,
      source: 'origin',
      reason: `unsupported protocol: ${parsed.protocol}`,
    };
  }

  const currentHostIsLocal = isLocalOrPrivateHost(window.location.hostname);
  const targetHostIsLocal = isLocalOrPrivateHost(parsed.hostname);
  if (!currentHostIsLocal && targetHostIsLocal) {
    return {
      url: originFallbackUrl,
      source: 'origin',
      reason: 'backend url points to local/private host',
    };
  }

  const currentHost = window.location.hostname.toLowerCase();
  const backendHost = parsed.hostname.toLowerCase();
  const isCurrentTunnel = isKnownTunnelHost(currentHost);
  const isBackendTunnel = isKnownTunnelHost(backendHost);
  if (isCurrentTunnel && isBackendTunnel && currentHost !== backendHost) {
    return {
      url: originFallbackUrl,
      source: 'origin',
      reason: `stale tunnel host from backend (${backendHost})`,
    };
  }

  if (!parsed.pathname || parsed.pathname === '/') {
    parsed.pathname = signalingPath;
  }

  if (window.location.protocol === 'https:' && parsed.protocol === 'ws:') {
    parsed.protocol = 'wss:';
  }

  return {
    url: parsed.toString(),
    source: 'backend',
  };
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
    const urls = rawUrls
      .map((value) => String(value || '').trim())
      .filter(Boolean);
    if (urls.length === 0) {
      continue;
    }

    const entry: RTCIceServer = {
      urls: urls.length === 1 ? urls[0] : urls,
    };
    if (server.username) {
      entry.username = server.username;
    }
    if (server.credential) {
      entry.credential = server.credential;
    }
    normalized.push(entry);
  }

  return normalized.length > 0 ? normalized : undefined;
}

function isCodecCompatibilityError(error: WebRTCError): boolean {
  if (error.code === 'SIGNALING_UNSUPPORTED_CODEC') {
    return true;
  }

  if (error.code !== 'NATIVE_SDP_REJECTION') {
    return false;
  }

  const message = String(error.message || '').toLowerCase();
  return (
    message.includes('codec') ||
    message.includes('h264') ||
    message.includes('vp8') ||
    message.includes('profile-level-id') ||
    message.includes('packetization-mode')
  );
}

function hasLiveVideoTrack(stream: MediaStream | null): boolean {
  return (
    !!stream &&
    stream
      .getVideoTracks()
      .some((track) => track.readyState === 'live' && !track.muted)
  );
}

function useAudioActivity(stream: MediaStream | null, ringRef: React.RefObject<HTMLDivElement>) {
  useEffect(() => {
    if (!stream || !ringRef.current) return;
    
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack || audioTrack.readyState !== 'live' || audioTrack.muted) {
      if (ringRef.current) ringRef.current.style.borderColor = 'transparent';
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
        
        if (ringRef.current) {
          if (average > 8) {
            ringRef.current.style.borderColor = 'rgba(34, 197, 94, 0.5)'; // green-500/50
          } else {
            ringRef.current.style.borderColor = 'transparent';
          }
        }
        rafId = requestAnimationFrame(updateLoop);
      };

      rafId = requestAnimationFrame(updateLoop);
    } catch (e) {
      console.warn("Audio Context setup failed (expected if no user interaction):", e);
    }

    return () => {
      cancelAnimationFrame(rafId);
      source?.disconnect();
      if (audioCtx?.state !== 'closed') {
        audioCtx?.close().catch(() => {});
      }
      if (ringRef.current) ringRef.current.style.borderColor = 'transparent';
    };
  }, [stream, ringRef]);
}

/**
 * Single Video Tile Component with Premium Discord-like UI
 */
const VideoTile = ({ 
  stream, 
  isLocal = false, 
  displayName, 
  isPrimary = false 
}: { 
  stream: MediaStream | null; 
  isLocal?: boolean; 
  displayName: string;
  isPrimary?: boolean;
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const [volume, setVolume] = useState([100]);
  const [audioPlaybackBlocked, setAudioPlaybackBlocked] = useState(false);

  useAudioActivity(stream, ringRef);

  const hasPlayableTracks =
    !!stream && stream.getTracks().some((track) => track.readyState === 'live');
  const hasLiveVideo =
    !!stream &&
    stream
      .getVideoTracks()
      .some((track) => track.readyState === 'live' && !track.muted);
  const hasLiveAudio =
    !!stream && stream.getAudioTracks().some((track) => track.readyState === 'live');

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
      if (hasLiveVideo && videoEl && videoEl.srcObject !== stream) {
        videoEl.srcObject = stream;
      }
      if (!hasLiveVideo && videoEl) {
        videoEl.srcObject = null;
      }

      if (!isLocal && hasLiveAudio && audioEl && audioEl.srcObject !== stream) {
        audioEl.srcObject = stream;
      }
      if ((!hasLiveAudio || isLocal) && audioEl) {
        audioEl.srcObject = null;
        setAudioPlaybackBlocked(false);
      }

      if (hasLiveVideo && videoEl) {
        videoEl.play().catch(() => {});
      }
      if (!isLocal && hasLiveAudio && audioEl) {
        const playAttempt = audioEl.play();
        playAttempt
          .then(() => {
            setAudioPlaybackBlocked(false);
          })
          .catch(() => {
            setAudioPlaybackBlocked(true);
          });
      }
    };

    syncMedia();

    stream.addEventListener('addtrack', syncMedia);
    stream.addEventListener('removetrack', syncMedia);

    return () => {
      stream.removeEventListener('addtrack', syncMedia);
      stream.removeEventListener('removetrack', syncMedia);
    };
  }, [hasLiveAudio, hasLiveVideo, hasPlayableTracks, isLocal, stream]);

  // Sync volume slider with hidden audio tag
  useEffect(() => {
    if (audioRef.current && !isLocal) {
      audioRef.current.volume = volume[0] / 100;
    }
  }, [volume, isLocal, stream]);

  const handleUnlockAudio = () => {
    if (isLocal || !stream || !hasLiveAudio || !audioRef.current) return;

    if (audioRef.current.srcObject !== stream) {
      audioRef.current.srcObject = stream;
    }

    audioRef.current
      .play()
      .then(() => {
        setAudioPlaybackBlocked(false);
      })
      .catch(() => {
        setAudioPlaybackBlocked(true);
      });
  };

  return (
    <div className={`relative bg-zinc-900 rounded-2xl overflow-hidden flex items-center justify-center ring-1 ring-white/5 shadow-lg group ${isPrimary ? 'col-span-full aspect-video max-h-[75vh]' : 'aspect-video max-h-[40vh]'} transition-all duration-300`}>
      {/* Inner shadow overlay for depth */}
      <div className="absolute inset-0 pointer-events-none rounded-2xl shadow-[inset_0_0_40px_rgba(0,0,0,0.6)] z-10" />

      {/* Speaking indicator border */}
      <div ref={ringRef} className="absolute inset-0 pointer-events-none rounded-2xl border-2 border-transparent transition-colors duration-200 z-20" />

      {stream && hasLiveVideo ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={`w-full h-full object-cover ${isLocal ? 'scale-x-[-1]' : ''}`}
        />
      ) : (
        <div className="flex w-full h-full flex-col items-center justify-center bg-gradient-to-b from-zinc-800 to-zinc-950">
          <div className="w-20 h-20 rounded-full bg-zinc-700/80 ring-4 ring-zinc-800/50 flex items-center justify-center mb-3 shadow-[0_0_30px_rgba(0,0,0,0.3)]">
            <span className="text-3xl font-medium text-white/90 font-display">
              {displayName.charAt(0).toUpperCase()}
            </span>
          </div>
        </div>
      )}
      
      {!isLocal && stream && hasLiveAudio && (
        <audio ref={audioRef} autoPlay playsInline className="hidden" />
      )}

      {!isLocal && stream && hasLiveAudio && audioPlaybackBlocked && (
        <Button
          variant="secondary"
          onClick={handleUnlockAudio}
          className="absolute top-4 right-4 z-30 h-8 px-3 text-xs bg-black/70 hover:bg-black text-white border border-white/10"
        >
          Включить звук
        </Button>
      )}
      
      {/* Name Badge & Volume Control */}
      <div className="absolute bottom-4 left-4 flex items-center gap-2 z-30 transition-transform duration-300 group-hover:-translate-y-1">
        <div className="bg-black/60 backdrop-blur-md px-3 py-1.5 rounded-lg text-xs font-medium text-white shadow-sm ring-1 ring-white/10 flex items-center gap-2">
          {!hasLiveAudio && (
            <MicOff className="w-3.5 h-3.5 text-red-400" />
          )}
          {displayName} {isLocal && <span className="text-muted-foreground opacity-70">(Вы)</span>}
        </div>

        {!isLocal && hasLiveAudio && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7 rounded-md bg-black/60 shadow-sm ring-1 ring-white/10 hover:bg-black/80 text-white transition-opacity opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100">
                {volume[0] === 0 ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 bg-[#1e1f22] border-[#2b2d31] p-3 text-gray-200" side="top" align="start" sideOffset={8}>
              <div className="flex flex-col gap-3 relative z-50">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">Громкость звука</span>
                  <span className="text-xs font-mono text-gray-400">{volume[0]}%</span>
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
        )}
      </div>
    </div>
  );
};

export const ConferencePage = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const { roomId: roomIdFromUrl } = useParams<{ roomId?: string }>();
  const activeRoomId = (roomIdFromUrl || '').trim();
  const isRoomSelected = activeRoomId.length > 0;

  // Authentication & Profile
  const token = getAccessToken();
  const { data: userProfile } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      const res = await api.get<UserProfile>('users/v1/profile/me');
      return res.data;
    },
    enabled: !!token,
  });

  const { data: conferenceConfig, isLoading: isConferenceConfigLoading } = useQuery({
    queryKey: ['conference-config'],
    queryFn: async () => {
      const res = await api.get<ConferenceRuntimeConfig>('cms/v1/conference/config');
      return res.data;
    },
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
  });
  
  const user = userProfile || null;
  
  // State
  const [manager, setManager] = useState<WebRTCManager | null>(null);
  const [connected, setConnected] = useState(false);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStreams, setRemoteStreams] = useState<RemoteStream[]>([]);
  const [participants, setParticipants] = useState<Map<string, string>>(new Map());
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null);
  const [joinRoomInput, setJoinRoomInput] = useState('');
  const [joinedRoomId, setJoinedRoomId] = useState<string | null>(null);
  
  // Controls
  const [micEnabled, setMicEnabled] = useState(true);
  const [camEnabled, setCamEnabled] = useState(true);
  const [showStats, setShowStats] = useState(false);

  // Initialization & cleanup
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
    navigate(`/room/${newRoomId}`);
  };

  const handleGoToRoom = () => {
    const normalized = joinRoomInput.trim();
    if (!normalized) {
      toast({
        variant: 'destructive',
        description: 'Введите ID комнаты',
      });
      return;
    }

    navigate(`/room/${encodeURIComponent(normalized)}`);
  };

  const handleCopyRoomId = async () => {
    if (!activeRoomId) return;
    try {
      await navigator.clipboard.writeText(activeRoomId);
      toast({ description: 'ID комнаты скопирован' });
    } catch {
      toast({
        variant: 'destructive',
        description: 'Не удалось скопировать ID комнаты',
      });
    }
  };

  const handleJoin = async () => {
    if (!isRoomSelected) {
      toast({
        variant: 'destructive',
        description: 'Сначала создайте комнату или введите ID',
      });
      return;
    }

    if (!user) {
      toast({
        variant: 'destructive',
        description: 'Пользователь не авторизован'
      });
      return;
    }

    if (needsSecureMediaContext()) {
      toast({
        variant: 'destructive',
        description:
          'Для доступа к камере/микрофону откройте конференцию по HTTPS (или через localhost). Текущий адрес по HTTP блокируется браузером.',
      });
      return;
    }

    const signalingUrlResolution = resolveSignalingUrl(conferenceConfig);
    const signalingUrl = signalingUrlResolution.url;
    if (!signalingUrl) {
      toast({
        variant: 'destructive',
        description: 'SFU URL не получен с backend',
      });
      return;
    }
    console.info(
      `[Conference] Signaling URL resolved from ${signalingUrlResolution.source}: ${signalingUrl}` +
        (signalingUrlResolution.reason
          ? ` (fallback reason: ${signalingUrlResolution.reason})`
          : '')
    );
    const runtimeIceServers = resolveRuntimeIceServers(conferenceConfig);

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
        toast({
          description: `${name} присоединился к встрече`
        });
      },
      onParticipantLeft: (peerId: string) => {
        setParticipants(prev => {
          const next = new Map(prev);
          next.delete(peerId);
          return next;
        });
        setRemoteStreams(prev => prev.filter(s => s.peerId !== peerId));
      },
      onQualityMetrics: (newMetrics: QualityMetrics) => {
        setMetrics(newMetrics);
      },
      onInfo: (message: string) => {
        toast({
          description: message,
        });
      },
      onCodecPolicyChanged: (policy: 'balanced' | 'vp8-only') => {
        if (policy === 'vp8-only') {
          toast({
            description: 'Оптимизация видеопотока: переключение на VP8',
          });
        }
      },
      onError: (error: WebRTCError) => {
        if (isCodecCompatibilityError(error)) {
          console.warn('[Conference] Codec compatibility issue detected:', error);
          return;
        }

        if (error.code === 'MEDIA_CAPTURE_FAILURE') {
          const isInsecureOrigin = typeof window !== 'undefined' && !window.isSecureContext;
          const secureContextHint = isInsecureOrigin
            ? ' Откройте страницу по HTTPS (например через ngrok-домен) или включите HTTPS у Vite.'
            : '';
          console.error(error);
          toast({
            variant: 'destructive',
            description: `Ошибка WebRTC: ${error.message}.${secureContextHint}`,
          });
          return;
        }

        console.error(error);
        toast({
          variant: 'destructive',
          description: `Ошибка WebRTC: ${error.message}`
        });
      }
    };

    const createManager = (policy: 'balanced' | 'vp8-only') =>
      new WebRTCManager({
        signalingUrl,
        roomId: activeRoomId,
        displayName: user.firstName ? `${user.firstName} ${user.lastName || ''}` : user.email,
        iceServers: runtimeIceServers,
        initialVideoCodecPolicy: policy,
        autoVp8Fallback: false,
      }, managerEvents);

    let activeManager = createManager('vp8-only');
    setManager(activeManager);
    let joinResult = await activeManager.join();

    if (!joinResult.ok && isCodecCompatibilityError(joinResult.error)) {
      toast({
        description: 'VP8 недоступен у сервера. Пробуем резервный профиль с H.264...',
      });

      const leaveResult = await activeManager.leave();
      if (!leaveResult.ok) {
        console.warn('[Conference] Failed to leave before codec fallback:', leaveResult.error);
      }

      const balancedManager = createManager('balanced');
      activeManager = balancedManager;
      setManager(balancedManager);
      joinResult = await balancedManager.join();
    }

    if (!joinResult.ok) {
      setManager(null);
      const signalingTarget = (() => {
        try {
          const parsed = new URL(signalingUrl);
          return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
        } catch {
          return signalingUrl;
        }
      })();
      const joinErrorDetails =
        joinResult.error.code === 'SIGNALING_CONNECTION_FAILED'
          ? ` [${signalingTarget}]`
          : '';
      toast({
        variant: 'destructive',
        description: `Не удалось подключиться: ${joinResult.error.message}${joinErrorDetails}`
      });
      return;
    }

    setManager(activeManager);
    const joinedStream = joinResult.value;
    const localAudioTrack = joinedStream.getAudioTracks()[0];
    const localVideoTrack = joinedStream.getVideoTracks()[0];

    setLocalStream(joinedStream);
    setMicEnabled(
      !!localAudioTrack &&
        localAudioTrack.readyState === 'live' &&
        localAudioTrack.enabled
    );
    setCamEnabled(
      !!localVideoTrack &&
        localVideoTrack.readyState === 'live' &&
        localVideoTrack.enabled
    );
    if (!localVideoTrack || localVideoTrack.readyState !== 'live') {
      toast({
        description: 'Подключено в аудио-режиме: камера сейчас не используется.',
      });
    }
    setJoinedRoomId(activeRoomId);
  };

  const handleLeave = async () => {
    if (manager) {
      const leaveResult = await manager.leave();
      if (!leaveResult.ok) {
        toast({
          variant: 'destructive',
          description: `Ошибка завершения звонка: ${leaveResult.error.message}`,
        });
      }
      setManager(null);
    }
    setConnected(false);
    setLocalStream(null);
    setRemoteStreams([]);
    setParticipants(new Map());
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
          description: `Ошибка микрофона: ${audioResult.error.message}`,
        });
        return;
      }
      setMicEnabled(nextValue);
    }
  };

  const toggleCam = () => {
    if (manager) {
      const hasVideoTrack =
        !!localStream &&
        localStream
          .getVideoTracks()
          .some((track) => track.readyState === 'live');
      if (!hasVideoTrack) {
        setCamEnabled(false);
        toast({
          description: 'Камера сейчас неактивна. Конференция работает в аудио-режиме.',
        });
        return;
      }

      const nextValue = !camEnabled;
      const videoResult = manager.setVideoEnabled(nextValue);
      if (!videoResult.ok) {
        toast({
          variant: 'destructive',
          description: `Ошибка камеры: ${videoResult.error.message}`,
        });
        return;
      }
      setCamEnabled(nextValue);
    }
  };

  // Group remote streams by peer — memoize to avoid re-creating MediaStream objects
  // on every render, which would break video.srcObject and cause black frames.
  const peers = React.useMemo(() => {
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

      if (latestVideoTrack) {
        combinedStream.addTrack(latestVideoTrack);
      }
      if (latestAudioTrack) {
        combinedStream.addTrack(latestAudioTrack);
      }

      return {
        peerId,
        displayName: peerStreams[0]?.displayName || 'Unknown',
        stream: combinedStream,
      };
    });
  }, [remoteStreams]);

  const primaryRemotePeerId = React.useMemo(() => {
    const peerWithLiveVideo = peers.find((peer) => hasLiveVideoTrack(peer.stream));
    return peerWithLiveVideo?.peerId ?? null;
  }, [peers]);

  const localIsPrimary = peers.length === 0 || !primaryRemotePeerId;
  const hasLocalVideoTrack =
    !!localStream &&
    localStream.getVideoTracks().some((track) => track.readyState === 'live');


  // Main Return Layout
  // When connected, we show a full-screen Discord-style interface (hiding standard Header)
  if (connected) {
    return (
      <div className="h-screen w-full bg-[#111214] text-gray-200 flex flex-col overflow-hidden font-sans">
        {/* Top minimal bar (Optional, for dragging or status) */}
        <div className="flex-none h-12 bg-[#1e1f22] border-b border-[#2b2d31] flex items-center justify-between px-4 shadow-sm z-10">
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="gap-2 py-1 px-3 bg-green-500/10 text-green-500 border-green-500/20 text-xs font-medium">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              Voice Connected
            </Badge>
            {activeRoomId && (
              <span className="text-xs font-mono text-gray-400 bg-black/20 px-2 py-1 rounded">
                Room: {activeRoomId}
              </span>
            )}
            <span className="text-xs font-medium text-gray-400 flex items-center gap-1">
              <Activity className="w-3.5 h-3.5" />
              {metrics ? `${metrics.rttMs}ms` : '---'}
            </span>
          </div>
          <div className="text-sm font-medium text-gray-400">
            {participants.size + 1} в звонке
          </div>
        </div>

        {/* Main Content Area (Sidebar + Grid) */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* Main Video Grid */}
          <div className="flex-1 bg-[#0b0c0d] p-4 md:p-6 overflow-y-auto flex flex-col justify-center items-center relative">
            
            <div className={`w-full max-w-[1600px] grid gap-4 lg:gap-6
              ${peers.length === 0 ? 'grid-cols-1 max-w-4xl' : ''}
              ${peers.length === 1 ? 'grid-cols-1 md:grid-cols-2' : ''}
              ${peers.length >= 2 ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3' : ''}
              place-content-center h-full
            `}>
              {/* Primary speaker / Local if alone */}
              <VideoTile 
                stream={localStream} 
                isLocal={true} 
                displayName={user?.firstName || 'Я'} 
                isPrimary={localIsPrimary && peers.length === 0} 
              />
              
              {/* Remote Peers */}
              {peers.map((peer) => (
                <VideoTile
                  key={peer.peerId}
                  stream={peer.stream}
                  displayName={peer.displayName}
                  isPrimary={peer.peerId === primaryRemotePeerId && peers.length <= 1}
                />
              ))}
            </div>

            {/* Quality Metrics Panel Overlay */}
            {showStats && metrics && (
              <div className="absolute top-4 left-4 right-4 bg-black/80 backdrop-blur-xl border border-white/10 p-5 rounded-2xl shadow-2xl z-50 text-white max-w-4xl mx-auto ring-1 ring-white/5 mx-4">
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <Activity className="w-4 h-4 text-primary" />
                    Статистика подключения (SFU)
                  </div>
                  <Button variant="ghost" size="icon" className="h-6 w-6 text-gray-400 hover:text-white" onClick={() => setShowStats(false)}>
                    <Activity className="h-4 w-4" />
                  </Button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">Target Video</div>
                    <div className={`font-mono text-base ${metrics.starvationMode ? 'text-amber-400' : 'text-emerald-400'}`}>
                      {(metrics.effectiveTargetVideoBitrateBps / 1_000_000).toFixed(2)} Mbps
                    </div>
                  </div>
                  <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">Bitrate (A+V)</div>
                    <div className="font-mono text-base text-gray-200">
                      {((metrics.currentVideoBitrateBps + metrics.currentAudioBitrateBps) / 1_000_000).toFixed(2)} Mbps
                    </div>
                  </div>
                  <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">Codec</div>
                    <div className="font-mono text-base text-blue-400">{metrics.codec || 'VP8/H264'}</div>
                  </div>
                  <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">Packet Loss</div>
                    <div className="font-mono text-base text-rose-400">{(metrics.packetLossRate * 100).toFixed(1)}%</div>
                  </div>
                   <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">Resolution</div>
                    <div className="font-mono text-base text-gray-200">{metrics.width}x{metrics.height}</div>
                  </div>
                  <div className="bg-zinc-900/50 rounded-lg p-3 border border-white/5">
                    <div className="text-gray-400 mb-1 text-[10px] uppercase font-bold tracking-wider">FPS</div>
                    <div className="font-mono text-base text-gray-200">{metrics.fps}</div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right Sidebar - Participants (Discord style) */}
          <div className="w-64 bg-[#2b2d31] border-l border-[#1e1f22] flex flex-col hidden lg:flex rounded-tl-xl shadow-lg relative z-20">
            <div className="p-4 border-b border-[#1e1f22]">
              <h3 className="font-semibold text-xs text-gray-400 uppercase tracking-wider">Участники в голосовом канале</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {/* Local User */}
              <div className="flex items-center gap-3 p-2 rounded hover:bg-[#35373c] transition-colors cursor-pointer group">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center text-sm font-bold text-white">
                    {user?.firstName?.charAt(0) || 'Y'}
                  </div>
                  <div className="absolute -bottom-1 -right-1 w-3.5 h-3.5 bg-green-500 border-2 border-[#2b2d31] rounded-full group-hover:border-[#35373c] transition-colors" />
                </div>
                <div className="flex-1 truncate text-sm font-medium text-gray-200">
                  {user?.firstName || 'Я'}
                </div>
                <div className="flex items-center gap-1 opacity-60">
                  {!micEnabled && <MicOff className="w-3.5 h-3.5 text-red-400" />}
                </div>
              </div>
              
              {/* Remote Users */}
              {Array.from(participants.entries()).map(([peerId, name]) => {
                const isUserMuted = false; // We don't have this specific signal yet for remotes explicitly outside of stream
                return (
                  <div key={peerId} className="flex items-center gap-3 p-2 rounded hover:bg-[#35373c] transition-colors cursor-pointer group">
                    <div className="relative">
                      <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-sm font-bold text-white">
                        {name.charAt(0).toUpperCase()}
                      </div>
                      <div className="absolute -bottom-1 -right-1 w-3.5 h-3.5 bg-green-500 border-2 border-[#2b2d31] rounded-full group-hover:border-[#35373c] transition-colors" />
                    </div>
                    <div className="flex-1 truncate text-sm font-medium text-gray-300">
                      {name}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Floating Bottom Control Bar */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-[#1e1f22]/90 backdrop-blur-xl border border-white/10 rounded-2xl p-2 flex items-center gap-2 shadow-2xl z-40 transition-all hover:bg-[#1e1f22]">
          <div className="flex items-center bg-[#2b2d31] rounded-xl overflow-hidden mr-2">
            <Button 
               variant="ghost"
               onClick={toggleMic}
               className={`h-14 w-16 rounded-none flex flex-col gap-1 items-center justify-center transition-colors
                 ${!micEnabled ? 'text-rose-500 hover:text-rose-400 hover:bg-rose-500/10' : 'text-gray-200 hover:bg-white/5'}
               `}
            >
              {!micEnabled ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
              <span className="text-[10px] font-medium leading-none">{!micEnabled ? 'Unmute' : 'Mute'}</span>
            </Button>
            {hasLocalVideoTrack && (
              <>
                <div className="w-px h-8 bg-white/5" />
                <Button 
                   variant="ghost"
                   onClick={toggleCam}
                   className={`h-14 w-16 rounded-none flex flex-col gap-1 items-center justify-center transition-colors
                     ${!camEnabled ? 'text-rose-500 hover:text-rose-400 hover:bg-rose-500/10' : 'text-gray-200 hover:bg-white/5'}
                   `}
                >
                  {!camEnabled ? <VideoOff className="w-5 h-5" /> : <Video className="w-5 h-5" />}
                  <span className="text-[10px] font-medium leading-none">{!camEnabled ? 'Start Video' : 'Stop Video'}</span>
                </Button>
              </>
            )}
            <div className="w-px h-8 bg-white/5" />
            <Button 
               variant="ghost"
               onClick={() => setShowStats(!showStats)}
               className={`h-14 w-16 rounded-none flex flex-col gap-1 items-center justify-center transition-colors
                 ${showStats ? 'text-emerald-400 hover:bg-emerald-400/10' : 'text-gray-200 hover:bg-white/5'}
               `}
            >
              <Settings className="w-5 h-5" />
              <span className="text-[10px] font-medium leading-none">Stats</span>
            </Button>
          </div>
          
          <Button 
            variant="destructive" 
            onClick={handleLeave}
            className="h-14 px-6 rounded-xl bg-rose-600 hover:bg-rose-700 shadow-lg shadow-rose-900/20 font-medium"
          >
            <PhoneOff className="w-5 h-5 mr-2" />
            Отключиться
          </Button>
        </div>
      </div>
    );
  }

  // Lobby Phase Layout
  return (
    <div className="min-h-screen bg-background flex flex-col relative overflow-hidden">
      {/* Decorative gradients for modern glassmorphism aesthetic */}
      <div className="absolute top-0 left-0 w-full h-96 bg-primary/5 blur-[120px] rounded-full pointer-events-none -translate-y-1/2" />
      <div className="absolute bottom-0 right-0 w-[800px] h-[600px] bg-secondary/5 blur-[150px] rounded-full pointer-events-none translate-y-1/3 translate-x-1/3" />
      
      <Header />
      <main className="flex-1 container mx-auto px-4 sm:px-6 lg:px-8 py-10 flex flex-col items-center justify-center relative z-10">
        
        <div className="w-full max-w-2xl mb-8 self-start md:self-auto">
          <Link
            to="/myprofile"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6 group"
          >
            <ArrowLeft className="h-4 w-4 group-hover:-translate-x-1 transition-transform" />
            Назад в профиль
          </Link>
          <div className="flex flex-col md:flex-row items-start md:items-center gap-5">
            <div className="p-4 bg-gradient-to-br from-primary/20 to-primary/5 rounded-2xl ring-1 ring-primary/20 shadow-[0_0_30px_hsl(var(--primary)/0.15)] flex-shrink-0">
              <Video className="w-10 h-10 text-primary animate-pulse-glow" />
            </div>
            <div>
              <h1 className="text-4xl md:text-5xl font-bold font-display tracking-tight text-foreground bg-clip-text">
                Видеоконференция
              </h1>
              <p className="text-muted-foreground mt-2 text-lg font-medium">
                Защищенная корпоративная видеосвязь с P2P шифрованием
              </p>
            </div>
          </div>
        </div>

        <div className="w-full max-w-2xl flex flex-col gap-6">

          {/* Lobby Card */}
          {!connected && !isRoomSelected && (
            <Card className="glass shadow-elevated border-white/10 dark:bg-zinc-950/50 relative overflow-hidden group">
              {/* Subtle hover gleam */}
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent -translate-x-full group-hover:animate-[shimmer_2s_infinite] pointer-events-none" />
              
              <CardContent className="pt-8 flex flex-col gap-8">
                <div className="flex flex-col items-center justify-center p-8 bg-muted/20 rounded-2xl border border-dashed border-primary/20 text-center gap-4 transition-colors hover:bg-muted/30">
                  <div className="p-5 bg-background shadow-md rounded-2xl text-primary ring-1 ring-border mb-2">
                    <MonitorPlay className="w-12 h-12" />
                  </div>
                  <div>
                    <h3 className="font-bold text-2xl tracking-tight">Подключение к эфиру</h3>
                    <p className="text-muted-foreground mt-3 max-w-lg mx-auto text-[15px] leading-relaxed">
                      Создайте новую изолированную комнату для встречи или присоединитесь по существующему идентификатору. Все каналы надежно защищены.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <Button
                    onClick={handleCreateRoomRoute}
                    size="lg"
                    className="h-14 lg:h-16 text-base font-semibold rounded-xl shadow-lg hover:shadow-primary/25 transition-all w-full flex-1"
                  >
                    <Plus className="w-5 h-5 mr-2" />
                    Новая комната
                  </Button>

                  <div className="flex gap-2">
                    <Input
                      value={joinRoomInput}
                      onChange={(e) => setJoinRoomInput(e.target.value)}
                      placeholder="ID: 12ab-34cd"
                      className="h-14 lg:h-16 rounded-xl bg-background/50 border-white/10 text-center font-mono text-lg font-medium focus-visible:ring-primary focus-visible:border-primary transition-all"
                    />
                    <Button
                      onClick={handleGoToRoom}
                      size="lg"
                      variant="secondary"
                      className="h-14 lg:h-16 px-6 font-semibold rounded-xl w-[100px] shrink-0"
                    >
                      <LogIn className="w-5 h-5" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Room Ready Card */}
          {!connected && isRoomSelected && (
            <Card className="glass shadow-elevated border-white/10 dark:bg-zinc-950/50 w-full relative overflow-hidden group">
               <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent -translate-x-full group-hover:animate-[shimmer_2s_infinite] pointer-events-none" />
              <CardContent className="pt-8 flex flex-col gap-6">
                <div className="flex flex-col items-center justify-center p-8 bg-muted/20 rounded-2xl border border-dashed border-primary/20 text-center gap-4 text-center">
                  <div className="p-4 bg-background shadow-md rounded-full text-green-500 ring-1 ring-border mb-2 relative">
                    <MonitorPlay className="w-12 h-12 relative z-10" />
                    <div className="absolute inset-0 bg-green-500/20 blur-xl rounded-full animate-pulse-glow" />
                  </div>
                  <div className="space-y-3">
                    <h3 className="font-bold text-2xl tracking-tight">Канал готов к эфиру</h3>
                    <div className="inline-flex items-center gap-3 rounded-xl border border-border/50 bg-background/80 shadow-inner px-4 py-2.5 backdrop-blur-sm">
                      <span className="font-mono text-lg text-primary font-bold tracking-wider">{activeRoomId}</span>
                      <div className="w-px h-6 bg-border" />
                      <Button variant="ghost" size="icon" onClick={handleCopyRoomId} className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted">
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                    <p className="text-muted-foreground mt-4 max-w-md mx-auto text-[15px]">
                      Вы заходите в защищенную изолированную среду обмена медиа-потоками P2P.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Button onClick={handleJoin} size="lg" className="w-full text-lg h-16 font-semibold shadow-xl rounded-xl btn-primary">
                    Присоединиться к эфиру
                  </Button>
                  <Button
                    onClick={() => navigate('/conference')}
                    size="lg"
                    variant="outline"
                    className="w-full text-base h-16 font-semibold rounded-xl border-2"
                  >
                    Покинуть зал ожидания
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

        </div>
      </main>
    </div>
  );
};

export default ConferencePage;
