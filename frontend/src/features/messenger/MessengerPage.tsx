/**
 * MessengerPage — full-page messenger UI.
 *
 * Layout: split-panel with chat list on the left and active chat on the right.
 * Accessible from /messenger route and linked from ProfileSidebar + BottomNav.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
    MessageCircle, Send, Search, Plus, ArrowLeft,
    Users, Lock, User, Loader2, Check, CheckCheck, Trash2, Paperclip, FileText, Download, Music, X,
    Mic, Square, Play, Pause, Image as ImageIcon, Film,
    Reply as ReplyIcon, Pencil, UserPlus, UserMinus, ShieldCheck,
} from 'lucide-react';
import { toast } from 'sonner';
import { isAxiosError } from 'axios';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { messengerApi } from './api/messengerApi';
import { useMessengerSocket, type PresenceMap } from './hooks/useMessengerSocket';
import { decodeMessageText } from './messageContent';
import type { DecodedMessage } from './messageContent';
import type { ChatRoom, ChatMessage, ChatUser } from './types';

// ---------------------------------------------------------------------------
//  Helper: encode plaintext to base64 for sending (non-E2EE rooms)
// ---------------------------------------------------------------------------
function encodeMessageText(payload: any): string {
    const jsonStr = JSON.stringify(payload);
    const bytes = new TextEncoder().encode(jsonStr);
    const binString = Array.from(bytes, (byte) => String.fromCodePoint(byte)).join("");
    return btoa(binString);
}

// ---------------------------------------------------------------------------
//  Helper: get other user in direct chat
// ---------------------------------------------------------------------------
/** Numeric id from a ChatUser regardless of whether it arrived as ``user_id``
 * (frontend canonical) or just ``id`` (raw replica row). Without this fallback
 * a single missing alias on either side collapses comparisons to
 * ``undefined !== undefined`` (false) and the whole UI degenerates. */
function uidOf(u: { user_id?: number; id?: number } | null | undefined): number | undefined {
    return u?.user_id ?? u?.id;
}

/** A participant row as the API actually returns it: `{user_id, role,
 *  last_read_message_id, user, unread_count}`. The declared `ChatMembership`
 *  still describes the pre-microservice shape (`id`, no `user_id`), so code
 *  that needs the real fields narrows through this instead of `any`. */
type ParticipantRow = {
    user_id?: number;
    role?: string;
    user?: ChatUser | null;
    unread_count?: number;
};

function participantRows(room: ChatRoom | null | undefined): ParticipantRow[] {
    return (room?.participants ?? []) as unknown as ParticipantRow[];
}

function getOtherMember(room: ChatRoom, myUserId: number | undefined) {
    if (myUserId == null) return null;
    const other = room.participants.find((m) => uidOf(m) !== myUserId && uidOf(m.user) !== myUserId);
    return other?.user || null;
}

// ---------------------------------------------------------------------------
//  Helper: format time
// ---------------------------------------------------------------------------
//  Per-bubble meta — time-only (HH:mm). The calendar day is now rendered as
//  a separator chip between message groups (see formatDaySeparator below),
//  so the bubble footer stays visually clean.
function formatTime(dateStr: string): string {
    return new Date(dateStr).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
    });
}

/** «был(а) в сети …» из ISO-времени последнего оффлайна (presence-сервис). */
function formatLastSeen(iso: string | null | undefined): string {
    if (!iso) return 'не в сети';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'не в сети';
    const mins = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
    if (mins < 1) return 'был(а) только что';
    if (mins < 60) return `был(а) ${mins} мин назад`;
    const sameDay = d.toDateString() === new Date().toDateString();
    if (sameDay) return `был(а) в ${formatTime(iso)}`;
    return `был(а) ${d.toLocaleDateString()} ${formatTime(iso)}`;
}

//  Room-list preview — today shows HH:mm, older days collapse to "dd MMM"
//  so the user can still tell whether a chat was active today vs. last week.
function formatRoomLastTime(dateStr: string): string {
    const d = new Date(dateStr);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

// ---------------------------------------------------------------------------
//  Helper: day separator label
// ---------------------------------------------------------------------------
//  · today              → "Сегодня"
//  · yesterday          → "Вчера"
//  · ≤ 7 days back      → weekday name      (Понедельник, Вторник…)
//  · same calendar year → "DD MMMM"         (12 марта)
//  · older              → "DD.MM.YYYY"      (12.03.2024)
function dayOf(d: Date): number {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function isSameLocalDay(a: string, b: string): boolean {
    return new Date(a).toDateString() === new Date(b).toDateString();
}

function formatDaySeparator(
    dateStr: string,
    locale: string,
    todayLabel: string,
    yesterdayLabel: string,
): string {
    const d = new Date(dateStr);
    const now = new Date();
    const dayDiff = Math.round((dayOf(now) - dayOf(d)) / 86_400_000);

    if (dayDiff === 0) return todayLabel;
    if (dayDiff === 1) return yesterdayLabel;
    if (dayDiff > 1 && dayDiff < 7) {
        const wd = d.toLocaleDateString(locale, { weekday: 'long' });
        return wd.charAt(0).toUpperCase() + wd.slice(1);
    }
    if (d.getFullYear() === now.getFullYear()) {
        return d.toLocaleDateString(locale, { day: 'numeric', month: 'long' });
    }
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    return `${dd}.${mm}.${d.getFullYear()}`;
}

// ---------------------------------------------------------------------------
//  Voice-message player — WhatsApp/Telegram style
// ---------------------------------------------------------------------------
//  Compact bubble with a circular Play/Pause button, waveform visualisation
//  (Telegram-style peaks), playback-rate cycler (1x → 1.5x → 2x) and a
//  global registry so starting one voice message pauses all others.

// Module-level registry: every mounted player registers its <audio>. When
// any player starts, the others are paused — same UX as Telegram.
const _activePlayers = new Set<HTMLAudioElement>();
function pauseAllExcept(except: HTMLAudioElement) {
    _activePlayers.forEach((a) => {
        if (a !== except && !a.paused) {
            try { a.pause(); } catch { /* ignore */ }
        }
    });
}

// Cache decoded waveform peaks per source URL so re-renders / re-mounts
// don't re-decode the same audio file. Keyed on the raw src string.
const _waveformCache = new Map<string, number[]>();
const WAVEFORM_BARS = 40;

async function decodeWaveform(src: string): Promise<number[] | null> {
    if (_waveformCache.has(src)) return _waveformCache.get(src)!;
    try {
        // No credentials — the URL is signed (sig+exp). Sending cookies
        // would force a CORS preflight that MinIO's 302 redirect target
        // can't satisfy, and the fetch would fail before the bitstream
        // reaches decodeAudioData.
        const res = await fetch(src);
        if (!res.ok) return null;
        const buf = await res.arrayBuffer();
        const Ctx = (window.AudioContext || (window as any).webkitAudioContext);
        if (!Ctx) return null;
        const ctx: AudioContext = new Ctx();
        const audioBuf = await ctx.decodeAudioData(buf.slice(0));
        const channel = audioBuf.getChannelData(0);
        // Downsample by taking the max(abs(...)) of each bucket. Keeps
        // visual peaks where the speaker actually said something.
        const bucket = Math.floor(channel.length / WAVEFORM_BARS) || 1;
        const peaks: number[] = [];
        let max = 0;
        for (let b = 0; b < WAVEFORM_BARS; b++) {
            let peak = 0;
            const start = b * bucket;
            const end = Math.min(start + bucket, channel.length);
            for (let i = start; i < end; i++) {
                const v = Math.abs(channel[i]);
                if (v > peak) peak = v;
            }
            peaks.push(peak);
            if (peak > max) max = peak;
        }
        // Normalise so the tallest bar reaches 1.0.
        const normalised = max > 0 ? peaks.map((p) => p / max) : peaks;
        try { ctx.close(); } catch { /* ignore */ }
        _waveformCache.set(src, normalised);
        return normalised;
    } catch {
        return null;
    }
}

const PLAYBACK_RATES = [1, 1.5, 2] as const;
const AUDIO_RATE_STORAGE_KEY = 'htq.messenger.audioRate';

function readStoredRateIdx(): number {
    if (typeof window === 'undefined') return 0;
    const raw = window.localStorage.getItem(AUDIO_RATE_STORAGE_KEY);
    const v = raw === null ? NaN : Number(raw);
    if (!Number.isFinite(v) || v < 0 || v >= PLAYBACK_RATES.length) return 0;
    return Math.floor(v);
}

interface VoiceMessagePlayerProps {
    src: string;
    filename?: string;
    isMine: boolean;
}

const VoiceMessagePlayer: React.FC<VoiceMessagePlayerProps> = ({ src, filename, isMine }) => {
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [seeking, setSeeking] = useState(false);
    // Persist user's chosen speed so a refresh / next session starts at
    // the same rate (Telegram-style sticky preference).
    const [rateIdx, setRateIdx] = useState<number>(() => readStoredRateIdx());
    const [peaks, setPeaks] = useState<number[] | null>(null);

    // Decode the waveform once per src — cached at module level.
    useEffect(() => {
        let cancelled = false;
        decodeWaveform(src).then((p) => { if (!cancelled) setPeaks(p); });
        return () => { cancelled = true; };
    }, [src]);

    // Register / deregister the <audio> with the global "one-at-a-time"
    // playback registry so starting another voice message pauses this one.
    useEffect(() => {
        const a = audioRef.current;
        if (!a) return;
        _activePlayers.add(a);
        return () => { _activePlayers.delete(a); };
    }, []);

    // Apply the current playback rate whenever the user cycles it +
    // persist the choice so every player on next load starts at the
    // same speed (sticky across sessions, like Telegram).
    useEffect(() => {
        const a = audioRef.current;
        if (a) a.playbackRate = PLAYBACK_RATES[rateIdx];
        try {
            window.localStorage.setItem(AUDIO_RATE_STORAGE_KEY, String(rateIdx));
        } catch {
            /* private mode / quota — best effort */
        }
    }, [rateIdx]);

    // MediaRecorder-produced WebM/Opus files often arrive with `duration =
    // Infinity` because the writer didn't fill in the duration header.
    // Forcing a long seek and bouncing back makes the browser scan the
    // bitstream and compute a real duration.
    const forceDurationProbe = () => {
        const a = audioRef.current;
        if (!a) return;
        if (!Number.isFinite(a.duration) || a.duration === 0) {
            const onSeeked = () => {
                a.removeEventListener('seeked', onSeeked);
                a.currentTime = 0;
            };
            try {
                a.addEventListener('seeked', onSeeked);
                a.currentTime = 1e9;
            } catch {
                /* ignore — some browsers throw on out-of-range seek */
            }
        }
    };

    const togglePlay = () => {
        const a = audioRef.current;
        if (!a) return;
        if (a.paused) {
            pauseAllExcept(a);
            a.play().catch(() => { /* user-gesture errors are non-fatal */ });
        } else {
            a.pause();
        }
    };

    const fmt = (sec: number): string => {
        if (!Number.isFinite(sec) || sec < 0) return '0:00';
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60).toString().padStart(2, '0');
        return `${m}:${s}`;
    };

    const buttonBg = isMine
        ? 'bg-primary-foreground/15 hover:bg-primary-foreground/25 text-primary-foreground'
        : 'bg-primary text-primary-foreground hover:bg-primary/90';
    const trackBg = isMine ? 'bg-primary-foreground/20' : 'bg-muted';
    const trackFill = isMine ? 'bg-primary-foreground' : 'bg-primary';
    const labelColor = isMine ? 'text-primary-foreground/70' : 'text-muted-foreground';

    const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 0;
    const progressPct = safeDuration ? (currentTime / safeDuration) * 100 : 0;

    // Seek to a clicked position on the waveform / track.
    const seekToFraction = (frac: number) => {
        const a = audioRef.current;
        if (!a || !safeDuration) return;
        const clamped = Math.max(0, Math.min(1, frac));
        const t = clamped * safeDuration;
        a.currentTime = t;
        setCurrentTime(t);
    };

    const onTrackPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        setSeeking(true);
        const rect = e.currentTarget.getBoundingClientRect();
        seekToFraction((e.clientX - rect.left) / rect.width);
    };
    const onTrackPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
        if (!seeking) return;
        const rect = e.currentTarget.getBoundingClientRect();
        seekToFraction((e.clientX - rect.left) / rect.width);
    };
    const onTrackPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
        try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
        setSeeking(false);
    };

    // Waveform view — fall back to a thin progress track if decode failed.
    const waveform = peaks ? (
        <div
            className="relative flex items-center gap-[2px] h-7 flex-1 cursor-pointer touch-none select-none"
            onPointerDown={onTrackPointerDown}
            onPointerMove={onTrackPointerMove}
            onPointerUp={onTrackPointerUp}
            onPointerCancel={onTrackPointerUp}
            role="slider"
            aria-valuemin={0}
            aria-valuemax={safeDuration}
            aria-valuenow={currentTime}
        >
            {peaks.map((p, i) => {
                const filled = (i / peaks.length) * 100 < progressPct;
                // Floor at 15% of the row so silent stretches still draw a tick.
                const heightPct = Math.max(15, p * 100);
                return (
                    <div
                        key={i}
                        className={`flex-1 rounded-sm transition-colors ${filled ? trackFill : trackBg}`}
                        style={{ height: `${heightPct}%` }}
                    />
                );
            })}
        </div>
    ) : (
        <div
            className={`relative h-1.5 rounded-full flex-1 cursor-pointer ${trackBg}`}
            onPointerDown={onTrackPointerDown}
            onPointerMove={onTrackPointerMove}
            onPointerUp={onTrackPointerUp}
            onPointerCancel={onTrackPointerUp}
        >
            <div
                className={`absolute inset-y-0 left-0 rounded-full ${trackFill}`}
                style={{ width: `${progressPct}%` }}
            />
        </div>
    );

    return (
        <div className="flex items-center gap-3 min-w-[240px] max-w-[340px]">
            <button
                type="button"
                onClick={togglePlay}
                className={`flex-shrink-0 h-10 w-10 rounded-full flex items-center justify-center transition-colors ${buttonBg}`}
                aria-label={isPlaying ? 'Пауза' : 'Воспроизвести'}
            >
                {isPlaying
                    ? <Pause className="h-4 w-4 fill-current" />
                    : <Play className="h-4 w-4 fill-current translate-x-[1px]" />}
            </button>

            <div className="flex flex-col gap-1 flex-1 min-w-0">
                {waveform}
                <div className={`text-[11px] tabular-nums ${labelColor}`}>
                    {fmt(currentTime)} / {safeDuration ? fmt(safeDuration) : '--:--'}
                </div>
            </div>

            {/* Speed cycler — only visible when audio actually loaded. */}
            {safeDuration > 0 && (
                <button
                    type="button"
                    onClick={() => setRateIdx((i) => (i + 1) % PLAYBACK_RATES.length)}
                    className={`flex-shrink-0 text-[11px] font-semibold px-2 py-1 rounded-md tabular-nums transition-colors ${
                        isMine
                            ? 'bg-primary-foreground/15 hover:bg-primary-foreground/25 text-primary-foreground'
                            : 'bg-muted hover:bg-muted/70 text-foreground'
                    }`}
                    title="Скорость воспроизведения"
                    aria-label="Скорость воспроизведения"
                >
                    {PLAYBACK_RATES[rateIdx]}x
                </button>
            )}

            <a
                href={src}
                target="_blank"
                rel="noreferrer"
                download={filename}
                className={`flex-shrink-0 p-1.5 rounded-full transition-colors ${
                    isMine ? 'hover:bg-primary-foreground/15' : 'hover:bg-muted'
                }`}
                title="Скачать"
            >
                <Download className={`h-4 w-4 ${labelColor}`} />
            </a>

            <audio
                ref={audioRef}
                src={src}
                preload="metadata"
                onLoadedMetadata={(e) => {
                    setDuration(e.currentTarget.duration);
                    if (!Number.isFinite(e.currentTarget.duration)) forceDurationProbe();
                }}
                onDurationChange={(e) => setDuration(e.currentTarget.duration)}
                onTimeUpdate={(e) => {
                    if (!seeking) setCurrentTime(e.currentTarget.currentTime);
                }}
                onPlay={(e) => {
                    pauseAllExcept(e.currentTarget);
                    setIsPlaying(true);
                }}
                onPause={() => setIsPlaying(false)}
                onEnded={() => {
                    setIsPlaying(false);
                    setCurrentTime(0);
                }}
            />
        </div>
    );
};


// ---------------------------------------------------------------------------
//  Image attachment — inline thumb + click-to-zoom lightbox
// ---------------------------------------------------------------------------
//  Renders the picture directly inside the message bubble (WhatsApp /
//  Telegram style). Falls back to the generic file card if the image
//  fails to load — typically a signed URL that expired before the user
//  scrolled to it. The lightbox covers the viewport with a darkened
//  backdrop; click anywhere outside the image or hit Esc to close.
interface ChatImageAttachmentProps {
    src: string;
    /** Optional ≤ 256×256 thumbnail URL. When provided, the bubble renders
     *  this lightweight preview; the lightbox always opens ``src`` (original). */
    thumbSrc?: string | null;
    filename?: string;
    width?: number | null;
    height?: number | null;
}

const ChatImageAttachment: React.FC<ChatImageAttachmentProps> = ({
    src,
    thumbSrc,
    filename,
    width,
    height,
}) => {
    const [zoom, setZoom] = useState(false);
    const [errored, setErrored] = useState(false);
    const previewSrc = thumbSrc || src;
    // Reserve aspect-ratio space so the chat bubble doesn't shift when the
    // image finishes loading. Fall back to 4:3 when intrinsic size is unknown
    // (legacy rows uploaded before migration 006_chat_attachment_thumbs).
    const aspect =
        width && height && width > 0 && height > 0
            ? `${width} / ${height}`
            : '4 / 3';

    useEffect(() => {
        if (!zoom) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setZoom(false); };
        window.addEventListener('keydown', onKey);
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = '';
        };
    }, [zoom]);

    if (errored) {
        return (
            <div className="flex items-center gap-2 bg-background/20 p-2 rounded-lg">
                <FileText className="h-5 w-5 opacity-70" />
                <span className="text-sm font-medium truncate max-w-[150px]" title={filename}>
                    {filename || 'Изображение'}
                </span>
                <a
                    href={src}
                    target="_blank"
                    rel="noreferrer"
                    download={filename}
                    className="ml-2 p-1.5 bg-background/30 rounded-full hover:bg-background/50 transition-colors"
                    title="Скачать"
                >
                    <Download className="h-4 w-4" />
                </a>
            </div>
        );
    }

    return (
        <>
            <button
                type="button"
                onClick={() => setZoom(true)}
                className="block w-[280px] max-w-full rounded-lg overflow-hidden bg-background/10 cursor-zoom-in"
                style={{ aspectRatio: aspect, maxHeight: 320 }}
                aria-label={filename || 'Открыть изображение'}
            >
                <img
                    src={previewSrc}
                    alt={filename || ''}
                    loading="lazy"
                    decoding="async"
                    width={width ?? undefined}
                    height={height ?? undefined}
                    onError={() => {
                        // Thumbnail might be missing for legacy rows or transient
                        // S3 errors — fall through to a file-card UI rather than
                        // showing a broken image.
                        setErrored(true);
                    }}
                    className="object-cover w-full h-full block"
                />
            </button>
            {zoom && (
                <div
                    className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
                    onClick={() => setZoom(false)}
                >
                    <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setZoom(false); }}
                        className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
                        aria-label="Закрыть"
                    >
                        <X className="h-5 w-5 text-white" />
                    </button>
                    <a
                        href={src}
                        download={filename}
                        onClick={(e) => e.stopPropagation()}
                        className="absolute top-4 right-16 p-2 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
                        title="Скачать"
                    >
                        <Download className="h-5 w-5 text-white" />
                    </a>
                    <img
                        src={src}
                        alt={filename || ''}
                        onClick={(e) => e.stopPropagation()}
                        className="max-w-full max-h-full object-contain rounded-lg cursor-default"
                    />
                </div>
            )}
        </>
    );
};


// ---------------------------------------------------------------------------
//  Small 48×48 thumb for the in-chat search results list
// ---------------------------------------------------------------------------
//  Used by the side-sheet search panel when a result has an image
//  attachment. Falls back to a neutral image icon on load error.
const SearchResultThumb: React.FC<{ src: string; filename?: string }> = ({ src, filename }) => {
    const [errored, setErrored] = useState(false);
    if (errored) {
        return (
            <div className="h-12 w-12 flex-shrink-0 rounded-md bg-muted flex items-center justify-center">
                <ImageIcon className="h-5 w-5 text-muted-foreground" />
            </div>
        );
    }
    return (
        <img
            src={src}
            alt={filename || ''}
            loading="lazy"
            decoding="async"
            onError={() => setErrored(true)}
            className="h-12 w-12 flex-shrink-0 rounded-md object-cover bg-muted"
        />
    );
};


// ---------------------------------------------------------------------------
//  In-chat search panel (text + media kind + date range)
// ---------------------------------------------------------------------------
//  Slides in from the right as a Sheet. The user types a query / picks a
//  media filter / sets a date range; results are fetched server-side via
//  `searchMessages`. Clicking a result jumps to the bubble in the main
//  thread via `onJump(id)`.
//
//  Debounce: 300ms — keeps PostgreSQL ILIKE quiet while the user is mid-typing.

type MediaKind = 'all' | 'images' | 'audio' | 'documents' | 'video';

const MEDIA_OPTIONS: { id: MediaKind; label: string }[] = [
    { id: 'all',       label: 'Все' },
    { id: 'images',    label: 'Картинки' },
    { id: 'audio',     label: 'Аудио' },
    { id: 'documents', label: 'Документы' },
    { id: 'video',     label: 'Видео' },
];

interface ChatSearchSheetProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    roomId: number;
    onJump: (messageId: string) => void;
}

const ChatSearchSheet: React.FC<ChatSearchSheetProps> = ({ open, onOpenChange, roomId, onJump }) => {
    const [text, setText] = useState('');
    const [kind, setKind] = useState<MediaKind>('all');
    const [since, setSince] = useState<string>('');
    const [until, setUntil] = useState<string>('');

    // Debounce free-text so each keystroke doesn't fire a request.
    const [debouncedText, setDebouncedText] = useState('');
    useEffect(() => {
        const t = window.setTimeout(() => setDebouncedText(text), 300);
        return () => window.clearTimeout(t);
    }, [text]);

    // Reset transient state every time the sheet is reopened.
    useEffect(() => {
        if (!open) return;
        setText('');
        setDebouncedText('');
        setKind('all');
        setSince('');
        setUntil('');
    }, [open]);

    const hasAnyFilter = !!debouncedText || kind !== 'all' || !!since || !!until;

    const { data: results, isFetching } = useQuery({
        queryKey: ['messenger-search', roomId, debouncedText, kind, since, until] as const,
        queryFn: () => messengerApi.searchMessages(roomId, {
            q: debouncedText || undefined,
            data_type: kind === 'all' ? undefined : kind,
            // Convert date-only inputs into full ISO datetimes at local-day boundaries.
            since: since ? new Date(`${since}T00:00:00`).toISOString() : undefined,
            until: until ? new Date(`${until}T23:59:59.999`).toISOString() : undefined,
            limit: 100,
        }),
        enabled: open && hasAnyFilter,
        staleTime: 5_000,
    });

    const fmtDate = (iso: string) => {
        const d = new Date(iso);
        return d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="w-full sm:max-w-md flex flex-col p-0">
                <SheetHeader className="p-4 border-b">
                    <SheetTitle>Поиск в чате</SheetTitle>
                </SheetHeader>

                <div className="p-4 space-y-3 border-b">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <input
                            type="text"
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            placeholder="Текст сообщения, имя файла..."
                            className="w-full pl-9 pr-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                            autoFocus
                        />
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                        {MEDIA_OPTIONS.map((opt) => (
                            <button
                                key={opt.id}
                                type="button"
                                onClick={() => setKind(opt.id)}
                                className={`text-xs px-3 py-1.5 rounded-full transition-colors ${
                                    kind === opt.id
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-accent text-muted-foreground hover:bg-accent/80'
                                }`}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                            С
                            <input
                                type="date"
                                value={since}
                                onChange={(e) => setSince(e.target.value)}
                                className="px-2 py-1.5 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                            />
                        </label>
                        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                            По
                            <input
                                type="date"
                                value={until}
                                onChange={(e) => setUntil(e.target.value)}
                                className="px-2 py-1.5 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                            />
                        </label>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2">
                    {!hasAnyFilter && (
                        <p className="text-sm text-muted-foreground text-center py-8 px-4">
                            Введите запрос, выберите тип медиа или укажите даты.
                        </p>
                    )}
                    {hasAnyFilter && isFetching && (
                        <div className="flex justify-center py-8">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    )}
                    {hasAnyFilter && !isFetching && (results?.length ?? 0) === 0 && (
                        <p className="text-sm text-muted-foreground text-center py-8 px-4">
                            Ничего не найдено.
                        </p>
                    )}
                    {hasAnyFilter && !isFetching && (results?.length ?? 0) > 0 && (
                        <ul className="divide-y">
                            {results!.map((m) => {
                                const att = m.attachments?.[0];
                                const ct = att?.content_type || '';
                                const isImage = ct.startsWith('image/');
                                const isVideo = ct.startsWith('video/');
                                const isAudio = ct.startsWith('audio/');
                                let preview: React.ReactNode = '';
                                if (att) {
                                    const Icon = isImage ? ImageIcon
                                        : isVideo ? Film
                                        : isAudio ? Music
                                        : FileText;
                                    preview = (
                                        <span className="flex items-center gap-1.5 truncate">
                                            <Icon className="h-4 w-4 opacity-60 flex-shrink-0" />
                                            <span className="truncate">{att.filename}</span>
                                        </span>
                                    );
                                } else {
                                    try {
                                        const parsed = JSON.parse(m.content || '{}');
                                        preview = parsed.text || parsed.body || m.content || '—';
                                    } catch {
                                        preview = m.content || '—';
                                    }
                                }
                                return (
                                    <li key={m.id}>
                                        <button
                                            type="button"
                                            onClick={() => onJump(m.id)}
                                            className="w-full flex gap-3 text-left p-3 hover:bg-accent/30 transition-colors rounded-md items-start"
                                        >
                                            {/* Real thumbnail for images — falls back to the
                                                kind icon when the row is pre-migration-006 or
                                                the thumb fetch fails. */}
                                            {isImage && att && (
                                                <SearchResultThumb
                                                    src={att.thumbnail_url || att.url}
                                                    filename={att.filename}
                                                />
                                            )}
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                                    <span className="truncate font-medium text-foreground">
                                                        {(m.sender as any)?.full_name || m.sender?.username || 'Система'}
                                                    </span>
                                                    <span className="flex-shrink-0">{fmtDate(m.created_at)}</span>
                                                </div>
                                                <div className="text-sm truncate">
                                                    {preview}
                                                </div>
                                            </div>
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    );
};


// ---------------------------------------------------------------------------
//  Chat info dialog — mini contact / group card
// ---------------------------------------------------------------------------
//  Opens on avatar/name tap in the chat header. For a DM it shows the
//  other participant's profile fields (name, position, online status,
//  username/email). For a group it shows the group title and a scrollable
//  participant list with roles and online dots.

interface ChatInfoDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    room: ChatRoom;
    myUid: number | undefined;
    displayName: string;
    /** Optional editor callback for group rooms. When provided the dialog
     *  exposes a "Изменить фото" button; the parent owns the upload + PATCH. */
    onGroupAvatarChange?: (file: File) => void | Promise<void>;
    /** True while the avatar upload/patch is in-flight. Disables the button. */
    isUploadingGroupAvatar?: boolean;
    /** Live presence map (socket-patched) — green dots / "был в сети". */
    presence?: PresenceMap;
}

const ChatInfoDialog: React.FC<ChatInfoDialogProps> = ({
    open,
    onOpenChange,
    room,
    myUid,
    displayName,
    onGroupAvatarChange,
    isUploadingGroupAvatar = false,
    presence = {},
}) => {
    const queryClient = useQueryClient();
    // «Добавить участников» — поиск по реестру пользователей, как в форме
    // создания группы. Доступно только админу группы (canManage ниже).
    const [addQuery, setAddQuery] = useState('');
    const [addOpen, setAddOpen] = useState(false);
    const { data: addCandidates = [] } = useQuery({
        queryKey: ['messenger-add-search', room.id, addQuery],
        queryFn: () => messengerApi.searchUsers(addQuery),
        enabled: addOpen,
    });

    const invalidateRooms = () =>
        queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
    const membershipError = (err: unknown) => {
        const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
        toast.error(typeof detail === 'string' ? detail : 'Не удалось изменить состав группы');
    };

    const addMutation = useMutation({
        mutationFn: (userId: number) => messengerApi.addParticipants(room.id, [userId]),
        onSuccess: () => { invalidateRooms(); toast.success('Участник добавлен'); },
        onError: membershipError,
    });
    const removeMutation = useMutation({
        mutationFn: (userId: number) => messengerApi.removeParticipant(room.id, userId),
        onSuccess: () => { invalidateRooms(); toast.success('Участник исключён'); },
        onError: membershipError,
    });
    const roleMutation = useMutation({
        mutationFn: ({ userId, role }: { userId: number; role: 'admin' | 'member' }) =>
            messengerApi.setParticipantRole(room.id, userId, role),
        onSuccess: invalidateRooms,
        onError: membershipError,
    });
    const isDirect = room.room_type === 'direct' || room.room_type === 'secret';
    const isGroup = room.room_type === 'group';
    // Only admins can edit the photo. Read role off the caller's own
    // participant row.
    const myParticipant = room.participants.find(
        (p: any) => (p.user_id ?? p.user?.id) === myUid,
    ) as any;
    const canEditGroup = isGroup && myParticipant?.role === 'admin' && !!onGroupAvatarChange;
    // Управление составом — тот же гейт, что и на бэке (только admin группы).
    const canManage = isGroup && myParticipant?.role === 'admin';
    const memberIds = new Set(room.participants.map((p: any) => p.user_id ?? p.user?.id));

    const otherUser: any = isDirect
        ? (() => {
            const m = room.participants.find((p: any) => (p.user_id ?? p.user?.id) !== myUid);
            return m?.user || m;
        })()
        : null;

    const fmtName = (u: any): string => {
        if (!u) return '—';
        if (u.full_name) return u.full_name;
        const fl = [u.first_name, u.last_name].filter(Boolean).join(' ');
        return fl || u.username || `User #${u.id ?? u.user_id ?? ''}`;
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        {room.room_type === 'secret' && <Lock className="h-4 w-4 text-secondary" />}
                        {displayName}
                    </DialogTitle>
                    <DialogDescription>
                        {room.room_type === 'group'
                            ? `Группа · ${room.participants.length} участников`
                            : room.room_type === 'secret'
                                ? 'Секретный чат · E2EE'
                                : 'Личный чат'}
                    </DialogDescription>
                </DialogHeader>

                {isDirect && otherUser && (
                    <div className="flex flex-col items-center gap-3 py-2">
                        {otherUser.avatar_url ? (
                            <img
                                src={otherUser.avatar_url}
                                alt={fmtName(otherUser)}
                                className="w-24 h-24 rounded-full object-cover"
                            />
                        ) : (
                            <div className="w-24 h-24 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                                <span className="font-bold text-primary/60 text-3xl">
                                    {fmtName(otherUser).charAt(0)}
                                </span>
                            </div>
                        )}
                        <div className="text-center">
                            <p className="text-lg font-semibold">{fmtName(otherUser)}</p>
                            {otherUser.position_title && (
                                <p className="text-sm text-muted-foreground">{otherUser.position_title}</p>
                            )}
                            {otherUser.department_name && (
                                <p className="text-xs text-muted-foreground">{otherUser.department_name}</p>
                            )}
                            {(() => {
                                // Live presence из Redis (см. useMessengerSocket) — поле
                                // otherUser.is_online осталось от старой реплики и
                                // всегда пустое.
                                const uid = otherUser.id ?? otherUser.user_id;
                                const st = uid != null ? presence[uid] : undefined;
                                return (
                                    <p className={`text-xs mt-1 ${st?.online ? 'text-green-600' : 'text-muted-foreground'}`}>
                                        {st?.online ? '🟢 В сети' : formatLastSeen(st?.last_seen)}
                                    </p>
                                );
                            })()}
                        </div>
                        <dl className="w-full grid grid-cols-[80px_1fr] gap-x-3 gap-y-1.5 text-sm mt-2">
                            {otherUser.username && (
                                <>
                                    <dt className="text-muted-foreground">Логин</dt>
                                    <dd className="font-medium truncate">{otherUser.username}</dd>
                                </>
                            )}
                            {otherUser.email && (
                                <>
                                    <dt className="text-muted-foreground">Email</dt>
                                    <dd className="font-medium truncate">{otherUser.email}</dd>
                                </>
                            )}
                            {otherUser.phone && (
                                <>
                                    <dt className="text-muted-foreground">Телефон</dt>
                                    <dd className="font-medium truncate">{otherUser.phone}</dd>
                                </>
                            )}
                        </dl>
                    </div>
                )}

                {!isDirect && (
                    <div className="space-y-3">
                        <div className="flex flex-col items-center gap-2 py-2">
                            {/* Group avatar: render the stored photo when present,
                                otherwise the Users placeholder. Admins get a file
                                input overlay to change/upload the photo. */}
                            <div className="relative">
                                {(room as any).avatar_url ? (
                                    <img
                                        src={(room as any).avatar_url}
                                        alt=""
                                        className="w-20 h-20 rounded-full object-cover"
                                    />
                                ) : (
                                    <div className="w-20 h-20 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                                        <Users className="h-9 w-9 text-primary/60" />
                                    </div>
                                )}
                                {canEditGroup && (
                                    <label
                                        className={`absolute inset-0 rounded-full flex items-center justify-center cursor-pointer transition-opacity ${
                                            isUploadingGroupAvatar
                                                ? 'bg-background/60 opacity-100'
                                                : 'bg-background/40 opacity-0 hover:opacity-100'
                                        }`}
                                        title="Изменить фото группы"
                                    >
                                        {isUploadingGroupAvatar ? (
                                            <Loader2 className="h-6 w-6 animate-spin text-foreground" />
                                        ) : (
                                            <span className="text-xs font-medium text-foreground">
                                                Изменить
                                            </span>
                                        )}
                                        <input
                                            type="file"
                                            accept="image/*"
                                            className="absolute inset-0 opacity-0 cursor-pointer"
                                            disabled={isUploadingGroupAvatar}
                                            onChange={(e) => {
                                                const f = e.target.files?.[0];
                                                if (f) onGroupAvatarChange?.(f);
                                                // Reset input so picking the same file twice still fires.
                                                e.currentTarget.value = '';
                                            }}
                                        />
                                    </label>
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Участники</p>
                                {canManage && (
                                    <button
                                        type="button"
                                        onClick={() => { setAddOpen(!addOpen); setAddQuery(''); }}
                                        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                                    >
                                        <UserPlus className="h-3.5 w-3.5" />
                                        {addOpen ? 'Скрыть' : 'Добавить'}
                                    </button>
                                )}
                            </div>

                            {/* Приглашение в существующую группу — до membership_service
                                (2026-07-28) состав фиксировался при создании навсегда. */}
                            {canManage && addOpen && (
                                <div className="mb-3 border rounded-lg p-2 bg-accent/20">
                                    <input
                                        type="text"
                                        value={addQuery}
                                        onChange={(e) => setAddQuery(e.target.value)}
                                        placeholder="Поиск сотрудников..."
                                        className="w-full mb-2 px-3 py-1.5 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                                    />
                                    <ul className="max-h-40 overflow-y-auto divide-y">
                                        {addCandidates
                                            .filter((u) => !memberIds.has(uidOf(u)))
                                            .map((u) => (
                                                <li key={u.id} className="flex items-center gap-2 py-1.5">
                                                    <span className="flex-1 text-sm truncate">{u.full_name || u.username}</span>
                                                    <button
                                                        type="button"
                                                        disabled={addMutation.isPending}
                                                        onClick={() => {
                                                            const uid = uidOf(u);
                                                            if (uid != null) addMutation.mutate(uid);
                                                        }}
                                                        className="p-1.5 rounded-full hover:bg-primary/10 text-primary disabled:opacity-50"
                                                        title="Добавить в группу"
                                                    >
                                                        <UserPlus className="h-4 w-4" />
                                                    </button>
                                                </li>
                                            ))}
                                        {addCandidates.filter((u) => !memberIds.has(uidOf(u))).length === 0 && (
                                            <li className="py-2 text-xs text-muted-foreground text-center">
                                                Все найденные уже в группе
                                            </li>
                                        )}
                                    </ul>
                                </div>
                            )}

                            <ul className="max-h-72 overflow-y-auto divide-y border rounded-lg">
                                {room.participants.map((p: any) => {
                                    const u = p.user || p;
                                    const uid = p.user_id ?? u.id;
                                    const name = fmtName(u);
                                    const isSelf = uid === myUid;
                                    const online = uid != null && presence[uid]?.online;
                                    return (
                                        <li
                                            key={uid}
                                            className="flex items-center gap-3 p-2"
                                        >
                                            <div className="relative flex-shrink-0">
                                                {u.avatar_url ? (
                                                    <img src={u.avatar_url} alt="" className="w-9 h-9 rounded-full object-cover" />
                                                ) : (
                                                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                                                        <span className="font-bold text-primary/60 text-sm">
                                                            {name.charAt(0)}
                                                        </span>
                                                    </div>
                                                )}
                                                {online && (
                                                    <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-green-500 ring-2 ring-card" title="В сети" />
                                                )}
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <p className="text-sm font-medium truncate">
                                                    {name}
                                                    {isSelf && (
                                                        <span className="ml-1 text-xs text-muted-foreground">(вы)</span>
                                                    )}
                                                </p>
                                                {u.position_title && (
                                                    <p className="text-xs text-muted-foreground truncate">{u.position_title}</p>
                                                )}
                                            </div>
                                            {p.role === 'admin' && (
                                                <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded bg-accent text-muted-foreground">
                                                    админ
                                                </span>
                                            )}
                                            {canManage && !isSelf && (
                                                <div className="flex items-center gap-0.5">
                                                    <button
                                                        type="button"
                                                        disabled={roleMutation.isPending}
                                                        onClick={() => roleMutation.mutate({
                                                            userId: uid,
                                                            role: p.role === 'admin' ? 'member' : 'admin',
                                                        })}
                                                        className={`p-1.5 rounded-full transition-colors disabled:opacity-50 ${p.role === 'admin' ? 'text-primary hover:bg-primary/10' : 'text-muted-foreground hover:bg-accent'}`}
                                                        title={p.role === 'admin' ? 'Снять права админа' : 'Назначить админом'}
                                                    >
                                                        <ShieldCheck className="h-4 w-4" />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={removeMutation.isPending}
                                                        onClick={() => {
                                                            if (confirm(`Исключить ${name} из группы?`)) {
                                                                removeMutation.mutate(uid);
                                                            }
                                                        }}
                                                        className="p-1.5 rounded-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
                                                        title="Исключить из группы"
                                                    >
                                                        <UserMinus className="h-4 w-4" />
                                                    </button>
                                                </div>
                                            )}
                                        </li>
                                    );
                                })}
                            </ul>
                        </div>
                    </div>
                )}

                <div className="text-xs text-muted-foreground text-center pt-2">
                    Создан {new Date(room.created_at).toLocaleString()}
                </div>
            </DialogContent>
        </Dialog>
    );
};


// ---------------------------------------------------------------------------
//  Main Component
// ---------------------------------------------------------------------------

const MessengerPage: React.FC = () => {
    const { t, i18n } = useTranslation();
    const queryClient = useQueryClient();

    const [activeRoomId, setActiveRoomId] = useState<number | null>(null);
    // Sidebar room/contact filter — separate from the NewChat search.
    const [roomsFilter, setRoomsFilter] = useState('');
    const [showNewChat, setShowNewChat] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [isGroupMode, setIsGroupMode] = useState(false);
    const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
    const [groupTitle, setGroupTitle] = useState('');
    // Optional group avatar file picked before the room is created. Held in
    // memory until the create-room mutation succeeds; then uploaded via the
    // attachments endpoint and attached to the room with PATCH /rooms/{id}.
    const [groupAvatarFile, setGroupAvatarFile] = useState<File | null>(null);
    const [groupAvatarPreview, setGroupAvatarPreview] = useState<string | null>(null);
    const [messageText, setMessageText] = useState('');
    const [mobileShowChat, setMobileShowChat] = useState(false);
    const [uploadingFile, setUploadingFile] = useState<boolean>(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [searchOpen, setSearchOpen] = useState(false);
    const [infoOpen, setInfoOpen] = useState(false);
    // Ответ и редактирование — взаимоисключающие режимы композера.
    const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
    const [editingMsg, setEditingMsg] = useState<ChatMessage | null>(null);
    // Voice recording state. The MediaRecorder ref is kept across renders so
    // the stop handler can flush its remaining chunks before we build the
    // final blob.
    const [isRecording, setIsRecording] = useState(false);
    const [recordingDuration, setRecordingDuration] = useState(0);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const recordedChunksRef = useRef<Blob[]>([]);
    const recordingTimerRef = useRef<number | null>(null);
    const recordingStartRef = useRef<number>(0);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    // Scroll container ref — used to inspect/set scrollTop so we can
    // implement the "stick-to-bottom unless the user scrolled up" rule.
    const messagesScrollRef = useRef<HTMLDivElement>(null);
    // Tracks whether the viewport is currently anchored at the bottom of
    // the chat. While true, new messages auto-scroll into view; once the
    // user scrolls up the position is preserved across refetches /
    // socket pushes until they manually return to the bottom.
    const pinnedToBottomRef = useRef(true);
    // Remember which room we last scrolled for, so switching chats forces
    // a one-time jump to the latest message regardless of the pin state.
    const lastScrolledRoomRef = useRef<number | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // --- Data queries ---
    const { data: me } = useQuery({
        queryKey: ['messenger-me'],
        queryFn: messengerApi.getMe,
    });

    // Socket.IO drives real-time updates; polling stays as a slow safety net.
    useMessengerSocket(activeRoomId);

    const { data: rooms = [], isLoading: roomsLoading } = useQuery({
        queryKey: ['messenger-rooms'],
        queryFn: messengerApi.getRooms,
        refetchInterval: 30000,
    });

    // Присутствие всех собеседников пачкой. Ключ ['messenger-presence'] общий
    // с сокет-хуком: user_online/user_offline патчат его точечно, а этот
    // запрос раз в минуту сверяет картину целиком (само-чинится после
    // пропущенных событий). Поле is_online из старой реплики мертво — байдж
    // берётся ТОЛЬКО отсюда.
    const { data: presence = {} } = useQuery<PresenceMap>({
        queryKey: ['messenger-presence'],
        queryFn: async () => {
            const ids = new Set<number>();
            rooms.forEach((r) => participantRows(r).forEach((p) => {
                const uid = p.user_id ?? p.user?.id;
                if (uid != null) ids.add(uid);
            }));
            if (ids.size === 0) return {};
            const raw = await messengerApi.getPresence([...ids]);
            const map: PresenceMap = {};
            for (const [k, v] of Object.entries(raw)) map[Number(k)] = v;
            return map;
        },
        enabled: rooms.length > 0,
        refetchInterval: 60000,
    });

    const { data: messages = [], isLoading: msgsLoading } = useQuery({
        queryKey: ['messenger-messages', activeRoomId],
        queryFn: () => activeRoomId ? messengerApi.getMessages(activeRoomId) : [],
        enabled: !!activeRoomId,
        refetchInterval: 30000,
    });

    // The API returns newest-first (``ORDER BY created_at DESC``) for
    // pagination, but the UI is conventionally oldest-at-top / newest-at-
    // bottom. Reverse once so all downstream code (rendering, mark-read,
    // read-receipt index math) works in chronological order.
    const orderedMessages = React.useMemo(() => [...messages].reverse(), [messages]);

    const { data: searchResults = [], isLoading: searchLoading } = useQuery({
        queryKey: ['messenger-search', searchQuery],
        queryFn: () => messengerApi.searchUsers(searchQuery),
        enabled: showNewChat,
    });

    // Filter the sidebar's room list by the user's query. Matches against
    // both the room name (covers groups) and every participant's visible
    // identity (covers DMs — those don't carry a `name`). Works fully
    // client-side — sidebar list is small, no need to round-trip.
    //
    // `getRoomDisplayName` is declared further down in this component, so
    // referencing it here would hit a temporal-dead-zone error; we inline
    // the relevant pieces of its logic instead.
    /** Detects a bot DM: a direct room where the other participant carries
     *  ``is_bot=true``. Used to (a) pin bot DMs to the top of the chat
     *  list, and (b) render the BOT badge in the bubble/header. */
    const isBotRoom = React.useCallback((room: ChatRoom): boolean => {
        if (room.room_type !== 'direct') return false;
        return room.participants.some((p: any) => {
            const u = p?.user || p;
            return Boolean(u?.is_bot);
        });
    }, []);

    const filteredRooms = React.useMemo(() => {
        const q = roomsFilter.trim().toLowerCase();
        const matched = q
            ? rooms.filter((room) => {
                if (room.name && room.name.toLowerCase().includes(q)) return true;
                return room.participants.some((p: any) => {
                    const u = p.user || p;
                    const fields = [
                        u.full_name,
                        u.first_name,
                        u.last_name,
                        u.username,
                        u.email,
                        u.position_title,
                    ];
                    return fields.some(
                        (f: string | undefined) => !!f && f.toLowerCase().includes(q),
                    );
                });
              })
            : rooms;
        // Pin bot DMs to the top so notifications are always one tap away,
        // then preserve the server-provided order (last_message recency).
        return [...matched].sort((a, b) => {
            const aBot = isBotRoom(a) ? 1 : 0;
            const bBot = isBotRoom(b) ? 1 : 0;
            return bBot - aBot;
        });
    }, [rooms, roomsFilter, isBotRoom]);

    // If the filter is set AND nothing matched in existing rooms, query
    // the user directory so the user can start a chat with someone they
    // haven't talked to yet. Debounced via the staleTime + enabled gate.
    const directoryQuery = useQuery({
        queryKey: ['messenger-sidebar-contacts', roomsFilter],
        queryFn: () => messengerApi.searchUsers(roomsFilter),
        enabled: roomsFilter.trim().length > 0 && filteredRooms.length === 0,
        staleTime: 5_000,
    });

    // Auto-mark-read whenever the active chat shows a new latest message.
    // Telegram-style: opening a chat or receiving a message while it's open
    // both clear the unread badge. Fire-and-forget — failures recover the
    // next time the user opens the chat.
    const lastMessageId = orderedMessages.length
        ? orderedMessages[orderedMessages.length - 1]?.id
        : null;
    useEffect(() => {
        if (!activeRoomId || !lastMessageId) return;
        messengerApi
            .markRead(activeRoomId, String(lastMessageId))
            .then(() => {
                queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
            })
            .catch(() => { /* ignore — best-effort */ });
    }, [activeRoomId, lastMessageId, queryClient]);

    // --- Mutations ---
    const sendMutation = useMutation({
        mutationFn: (payload: { text?: string; attachment_ids?: string[] }) => {
            if (!activeRoomId) throw new Error('No active room');
            return messengerApi.sendMessage({
                room_id: activeRoomId,
                content: JSON.stringify({ text: payload.text || '' }),
                is_encrypted: false,
                attachment_ids: payload.attachment_ids || [],
                reply_to: replyTo ? String(replyTo.id) : undefined,
            });
        },
        onSuccess: () => {
            setReplyTo(null);
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', activeRoomId] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        },
        onError: () => toast.error('Ошибка отправки'),
    });

    const editMutation = useMutation({
        mutationFn: ({ id, text }: { id: string; text: string }) =>
            messengerApi.editMessage(id, JSON.stringify({ text })),
        onSuccess: (updated) => {
            setEditingMsg(null);
            setMessageText('');
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', updated.room_id] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        },
        onError: (err: unknown) => {
            const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
            toast.error(typeof detail === 'string' ? detail : 'Не удалось изменить сообщение');
        },
    });

    const deleteMsgMutation = useMutation({
        mutationFn: (id: string) => messengerApi.deleteMessage(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', activeRoomId] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        },
        onError: (err: unknown) => {
            const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
            toast.error(typeof detail === 'string' ? detail : 'Не удалось удалить сообщение');
        },
    });

    const createRoomMutation = useMutation({
        mutationFn: async (data: { room_type: 'direct' | 'group', member_user_ids: number[], title?: string }) => {
            // The API rejects the whole payload (422) if a single id is not a
            // number, so drop anything unusable here rather than letting the
            // request fail as a whole.
            const participantIds = data.member_user_ids.filter(
                (id): id is number => typeof id === 'number' && Number.isFinite(id),
            );
            if (participantIds.length === 0) {
                throw new Error('Не выбран ни один участник');
            }
            const room = await messengerApi.createRoom({
                room_type: data.room_type,
                participant_ids: participantIds,
                name: data.title,
            } as any);
            // For groups: upload the optional avatar file picked in the form,
            // then PATCH the room with the resulting signed URL. We do this
            // post-create because the attachment storage path is keyed by
            // the room's storage_key, which only exists once the row is saved.
            if (data.room_type === 'group' && groupAvatarFile) {
                try {
                    const att = await messengerApi.uploadGroupAvatar(room.id, groupAvatarFile);
                    if (att?.url) {
                        const patched = await messengerApi.updateRoom(room.id, { avatar_url: att.url });
                        return patched;
                    }
                } catch (err) {
                    // Don't block the room creation on an avatar hiccup — the
                    // user can still set a photo later via the info dialog.
                    console.warn('group avatar upload failed', err);
                }
            }
            return room;
        },
        onSuccess: (room: ChatRoom) => {
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
            setActiveRoomId(room.id);
            setShowNewChat(false);
            setSearchQuery('');
            setIsGroupMode(false);
            setSelectedUserIds([]);
            setGroupTitle('');
            setGroupAvatarFile(null);
            if (groupAvatarPreview) {
                URL.revokeObjectURL(groupAvatarPreview);
                setGroupAvatarPreview(null);
            }
            setMobileShowChat(true);
        },
        onError: (err: unknown) => {
            // Without this the mutation failed silently and the "new chat"
            // panel just sat there, looking like a dead button.
            const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
            const message = err instanceof Error ? err.message : '';
            toast.error(
                typeof detail === 'string'
                    ? detail
                    : message || 'Не удалось создать чат',
            );
        },
    });

    const updateRoomMutation = useMutation({
        mutationFn: ({ roomId, payload }: { roomId: number; payload: { name?: string | null; avatar_url?: string | null } }) =>
            messengerApi.updateRoom(roomId, payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        },
        onError: () => toast.error('Не удалось обновить чат'),
    });

    // DELETE /rooms/{id} does one of two things depending on who asks and
    // what kind of room it is (see backend room_lifecycle): the owner of a
    // group deletes it for everyone; anyone else — and either side of a
    // direct chat — just drops it from their own list. The response says
    // which happened, so the toast can be honest about it.
    const deleteRoomMutation = useMutation({
        mutationFn: (roomId: number) => messengerApi.deleteRoom(roomId),
        onSuccess: (res) => {
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
            setActiveRoomId(null);
            toast.success(
                res?.result === 'deleted'
                    ? 'Чат удалён для всех участников'
                    : 'Чат убран из вашего списка',
            );
        },
        onError: () => toast.error('Ошибка удаления чата'),
    });

    // --- Smart auto-scroll ---
    // Rules (WhatsApp / Telegram parity):
    //   1. Switching rooms → instant jump to the newest message.
    //   2. New tail message arrives AND the user is currently at the
    //      bottom → smooth-scroll into view.
    //   3. User scrolled up → leave their position alone. Background
    //      refetches / socket pushes must not yank the viewport.
    useEffect(() => {
        const lastSeenRoom = lastScrolledRoomRef.current;
        const roomChanged = activeRoomId !== null && activeRoomId !== lastSeenRoom;
        if (roomChanged) {
            // First paint into a new room — force-pin to bottom without
            // animation so the chat doesn't briefly show the oldest
            // message before sliding down.
            lastScrolledRoomRef.current = activeRoomId;
            pinnedToBottomRef.current = true;
            requestAnimationFrame(() => {
                const sc = messagesScrollRef.current;
                if (sc) sc.scrollTop = sc.scrollHeight;
            });
            return;
        }
        if (!pinnedToBottomRef.current) return;
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [orderedMessages, activeRoomId]);

    // Recompute pinned state on every user-driven scroll. 80px slack so
    // tiny rubber-band offsets don't accidentally unpin.
    const onMessagesScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
        const el = e.currentTarget;
        const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        pinnedToBottomRef.current = distanceFromBottom < 80;
    }, []);

    // --- Send handler ---
    const handleSend = useCallback(async () => {
        const text = messageText.trim();
        if ((!text && !selectedFile) || sendMutation.isPending || uploadingFile) return;

        // Режим редактирования: тот же композер, но PATCH вместо POST.
        if (editingMsg) {
            if (!text || editMutation.isPending) return;
            editMutation.mutate({ id: String(editingMsg.id), text });
            return;
        }

        // Sending our own message always re-anchors the view to the
        // bottom, even if the user had scrolled up just before tapping
        // Send. Mirrors the universal messenger convention.
        pinnedToBottomRef.current = true;

        if (selectedFile) {
            setUploadingFile(true);
            try {
                if (!activeRoomId) throw new Error('No active room');
                const res = await messengerApi.uploadAttachment(activeRoomId, selectedFile);
                sendMutation.mutate({
                    text,
                    attachment_ids: [res.id],
                });
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
                setMessageText('');
            } catch (err) {
                toast.error('Ошибка загрузки файла');
            } finally {
                setUploadingFile(false);
            }
        } else {
            sendMutation.mutate({ text });
            setMessageText('');
        }
    }, [activeRoomId, messageText, selectedFile, sendMutation, uploadingFile, editingMsg, editMutation]);

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            setSelectedFile(file);
        }
    };

    // ── Voice recording ────────────────────────────────────────────────
    // Pick the best Opus-capable container the browser supports. Firefox
    // gives us native ogg; Chromium falls back to webm/opus, but we still
    // present the resulting file as `.ogg` per product requirement — the
    // bytes inside are valid Opus either way and audio players probe by
    // magic bytes, so most consumers accept the mismatch silently.
    const pickRecorderMime = (): { mime: string; ext: string } => {
        if (typeof MediaRecorder === 'undefined') return { mime: '', ext: 'ogg' };
        const candidates = [
            'audio/ogg;codecs=opus',
            'audio/webm;codecs=opus',
            'audio/webm',
        ];
        for (const m of candidates) {
            if (MediaRecorder.isTypeSupported(m)) return { mime: m, ext: 'ogg' };
        }
        return { mime: '', ext: 'ogg' };
    };

    const stopRecordingTimer = () => {
        if (recordingTimerRef.current !== null) {
            window.clearInterval(recordingTimerRef.current);
            recordingTimerRef.current = null;
        }
    };

    const cleanupRecorder = () => {
        const rec = mediaRecorderRef.current;
        if (rec) {
            try {
                rec.stream.getTracks().forEach((t) => t.stop());
            } catch {
                /* ignore */
            }
        }
        mediaRecorderRef.current = null;
        recordedChunksRef.current = [];
        stopRecordingTimer();
        setIsRecording(false);
        setRecordingDuration(0);
    };

    const startRecording = useCallback(async () => {
        if (isRecording || uploadingFile || sendMutation.isPending) return;
        if (!navigator.mediaDevices?.getUserMedia) {
            toast.error(t('messenger.audio.unsupported', 'Запись не поддерживается этим браузером'));
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const { mime } = pickRecorderMime();
            const recorder = mime
                ? new MediaRecorder(stream, { mimeType: mime })
                : new MediaRecorder(stream);
            recordedChunksRef.current = [];
            recorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) recordedChunksRef.current.push(e.data);
            };
            recorder.onerror = () => {
                cleanupRecorder();
                toast.error(t('messenger.audio.error', 'Ошибка записи аудио'));
            };
            mediaRecorderRef.current = recorder;
            recordingStartRef.current = Date.now();
            recorder.start(250); // emit chunks every 250ms
            setIsRecording(true);
            setRecordingDuration(0);
            recordingTimerRef.current = window.setInterval(() => {
                setRecordingDuration(
                    Math.floor((Date.now() - recordingStartRef.current) / 1000),
                );
            }, 500);
        } catch (err) {
            cleanupRecorder();
            toast.error(t('messenger.audio.permission', 'Нет доступа к микрофону'));
        }
    }, [isRecording, sendMutation.isPending, t, uploadingFile]);

    const finishRecording = useCallback(() => {
        const recorder = mediaRecorderRef.current;
        if (!recorder || recorder.state === 'inactive') {
            cleanupRecorder();
            return;
        }
        // Capture the chunks we already have and any final pending chunk.
        recorder.onstop = () => {
            const chunks = recordedChunksRef.current;
            const realMime = recorder.mimeType || 'audio/ogg';
            // Always present the file as .ogg per product requirement; the
            // codec stays whatever MediaRecorder produced.
            const blob = new Blob(chunks, { type: realMime });
            if (blob.size > 0) {
                const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const file = new File([blob], `voice-${ts}.ogg`, { type: realMime });
                setSelectedFile(file);
            }
            cleanupRecorder();
        };
        try {
            recorder.stop();
        } catch {
            cleanupRecorder();
        }
    }, []);

    const cancelRecording = useCallback(() => {
        const recorder = mediaRecorderRef.current;
        if (recorder && recorder.state !== 'inactive') {
            // Override onstop so the chunks are dropped, not turned into a file.
            recorder.onstop = () => cleanupRecorder();
            try {
                recorder.stop();
                return;
            } catch {
                /* fall through */
            }
        }
        cleanupRecorder();
    }, []);

    // Stop the mic if the page unmounts mid-recording.
    useEffect(() => {
        return () => cleanupRecorder();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const formatRecordingDuration = (sec: number): string => {
        const m = Math.floor(sec / 60).toString().padStart(2, '0');
        const s = (sec % 60).toString().padStart(2, '0');
        return `${m}:${s}`;
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    // --- Active room ---
    const activeRoom = rooms.find(r => r.id === activeRoomId) || null;

    const myUid = uidOf(me as any);
    // Своя роль в открытой комнате — гейт для админских действий (удаление
    // чужих сообщений в группе). Совпадает с проверкой на бэке.
    const myRoleInActiveRoom = participantRows(activeRoom)
        .find((p) => (p.user_id ?? p.user?.id) === myUid)?.role;

    const getRoomDisplayName = (room: ChatRoom) => {
        if (room.name) return room.name;
        if (me && (room.room_type === 'direct' || room.room_type === 'secret')) {
            const other = getOtherMember(room, myUid);
            // ``full_name`` is what the messenger schema computes; legacy
            // payloads might only carry username/first_name. Fall through.
            return (
                (other as any)?.full_name ||
                other?.username ||
                other?.first_name ||
                'Чат'
            );
        }
        return `Чат #${room.id}`;
    };

    const getRoomAvatar = (room: ChatRoom) => {
        if (me && room.room_type === 'direct') {
            const other = getOtherMember(room, myUid);
            return other?.avatar_url || '';
        }
        return room.avatar_url;
    };

    /** Renders both the inline thumb (when last message is an image) and
     *  the textual preview. ``React.ReactNode`` so the consumer can drop it
     *  straight into the row layout. */
    const getLastMessagePreview = (room: ChatRoom): React.ReactNode => {
        if (!room.last_message) return 'Нет сообщений';
        const last = room.last_message;
        const senderUid = (last as any).sender_id ?? uidOf(last.sender);
        const isMine = senderUid != null && myUid != null && senderUid === myUid;

        const decoded = decodeMessageText(last);
        let thumbSrc: string | null = null;
        let body: string;
        if (typeof decoded === 'object') {
            const isImage = decoded.mime_type?.startsWith('image/') || decoded.data_type === 'images';
            if (isImage) {
                thumbSrc = decoded.thumb_url || decoded.file_url || null;
            }
            const kindLabel = decoded.mime_type?.startsWith('image/')
                ? '🖼 Изображение'
                : decoded.mime_type?.startsWith('video/')
                ? '🎬 Видео'
                : decoded.mime_type?.startsWith('audio/')
                ? '🎤 Голосовое сообщение'
                : `📎 ${decoded.file_name || 'Вложение'}`;
            body = decoded.text?.trim() ? `${kindLabel}: ${decoded.text}` : kindLabel;
        } else {
            body = (decoded as string).substring(0, 60);
        }

        // ``Вы: `` prefix for messages the current user authored. Group rooms
        // also get a sender prefix so the recipient sees who wrote what
        // without opening the chat. Direct chats stay unprefixed for the
        // other person — the column is small and the chat title already
        // identifies them.
        let prefix = '';
        if (isMine) {
            prefix = 'Вы: ';
        } else if (room.room_type === 'group' && last.sender) {
            const author = (last.sender as any)?.full_name || last.sender.username || '';
            const short = author.split(/\s+/)[0];
            if (short) prefix = `${short}: `;
        }

        if (thumbSrc) {
            return (
                <span className="inline-flex items-center gap-1.5 min-w-0 max-w-full">
                    <img
                        src={thumbSrc}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                        className="h-5 w-5 flex-shrink-0 rounded object-cover bg-muted"
                    />
                    <span className="truncate">{prefix}{body}</span>
                </span>
            );
        }
        return `${prefix}${body}`;
    };

    // =========================================================================
    //  RENDER
    // =========================================================================

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-0 sm:px-4 py-2 sm:py-6 pb-24 sm:pb-6 max-w-6xl flex flex-col">
                <div className="mb-3 px-4 sm:px-0">
                    <BackToProfile className="mb-0 text-xs" />
                </div>
                <div className="bg-card rounded-xl border shadow-sm overflow-hidden flex" style={{ height: 'calc(100dvh - 170px)', minHeight: '420px' }}>

                    {/* ===== LEFT PANEL: Chat List ===== */}
                    <div className={`w-full sm:w-80 lg:w-96 border-r flex flex-col ${mobileShowChat ? 'hidden sm:flex' : 'flex'}`}>
                        {/* Header */}
                        <div className="p-4 border-b flex items-center justify-between bg-card">
                            <h2 className="font-display text-lg font-bold flex items-center gap-2">
                                <MessageCircle className="h-5 w-5 text-primary" />
                                Сообщения
                            </h2>
                            <button
                                onClick={() => {
                                    setShowNewChat(!showNewChat);
                                    setSearchQuery('');
                                    setIsGroupMode(false);
                                    setSelectedUserIds([]);
                                    setGroupTitle('');
                                }}
                                className="p-2 rounded-lg hover:bg-accent transition-colors"
                                title="Новый чат"
                            >
                                <Plus className="h-5 w-5" />
                            </button>
                        </div>

                        {/* Sidebar search — filters existing chats; falls back
                            to a directory lookup so the user can start a new
                            DM with anyone they don't have a chat with yet. */}
                        <div className="p-3 border-b bg-card">
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                <input
                                    type="text"
                                    value={roomsFilter}
                                    onChange={(e) => setRoomsFilter(e.target.value)}
                                    placeholder="Поиск чатов и контактов..."
                                    className="w-full pl-9 pr-8 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                                />
                                {roomsFilter && (
                                    <button
                                        type="button"
                                        onClick={() => setRoomsFilter('')}
                                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-accent transition-colors"
                                        title="Очистить"
                                    >
                                        <X className="h-3.5 w-3.5 text-muted-foreground" />
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* New Chat — employee list with optional search filter */}
                        {showNewChat && (
                            <div className="flex flex-col border-b bg-accent/30 overflow-hidden" style={{ maxHeight: '60%' }}>
                                {/* Search filter */}
                                <div className="p-3 pb-2 flex flex-col gap-3">
                                    <div className="flex justify-between items-center">
                                        <button
                                            onClick={() => {
                                                setIsGroupMode(!isGroupMode);
                                                setSelectedUserIds([]);
                                                setGroupTitle('');
                                                setGroupAvatarFile(null);
                                                if (groupAvatarPreview) URL.revokeObjectURL(groupAvatarPreview);
                                                setGroupAvatarPreview(null);
                                            }}
                                            className={`text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${isGroupMode ? 'bg-primary text-primary-foreground' : 'bg-primary/10 text-primary hover:bg-primary/20'}`}
                                        >
                                            {isGroupMode ? 'Отмена группы' : 'Создать группу'}
                                        </button>
                                        {isGroupMode && selectedUserIds.length > 0 && (
                                            <button
                                                onClick={() => createRoomMutation.mutate({ room_type: 'group', member_user_ids: selectedUserIds, title: groupTitle })}
                                                disabled={!groupTitle.trim() || createRoomMutation.isPending}
                                                className="text-xs px-3 py-1.5 rounded-full bg-green-500 text-white font-medium hover:bg-green-600 focus:outline-none disabled:opacity-50"
                                            >
                                                Создать ({selectedUserIds.length + 1})
                                            </button>
                                        )}
                                    </div>

                                    {isGroupMode && (
                                        <>
                                            <div className="flex items-center gap-3">
                                                {/* Avatar picker — square label that acts as the
                                                    file <input>'s trigger. Preview shows the
                                                    picked file via an object URL. */}
                                                <label className="relative cursor-pointer flex-shrink-0">
                                                    {groupAvatarPreview ? (
                                                        <img
                                                            src={groupAvatarPreview}
                                                            alt=""
                                                            className="w-12 h-12 rounded-full object-cover ring-2 ring-primary/30"
                                                        />
                                                    ) : (
                                                        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center text-primary border-2 border-dashed border-primary/40">
                                                            <Users className="h-5 w-5" />
                                                        </div>
                                                    )}
                                                    <input
                                                        type="file"
                                                        accept="image/*"
                                                        onChange={(e) => {
                                                            const f = e.target.files?.[0] || null;
                                                            setGroupAvatarFile(f);
                                                            if (groupAvatarPreview) URL.revokeObjectURL(groupAvatarPreview);
                                                            setGroupAvatarPreview(f ? URL.createObjectURL(f) : null);
                                                        }}
                                                        className="absolute inset-0 opacity-0 cursor-pointer"
                                                    />
                                                </label>
                                                <input
                                                    type="text"
                                                    placeholder="Название группы..."
                                                    value={groupTitle}
                                                    onChange={(e) => setGroupTitle(e.target.value)}
                                                    className="flex-1 px-3 py-2 rounded-lg bg-background border text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/40"
                                                />
                                            </div>
                                            {groupAvatarFile && (
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setGroupAvatarFile(null);
                                                        if (groupAvatarPreview) URL.revokeObjectURL(groupAvatarPreview);
                                                        setGroupAvatarPreview(null);
                                                    }}
                                                    className="text-xs text-muted-foreground hover:text-foreground w-fit"
                                                >
                                                    Убрать фото
                                                </button>
                                            )}
                                        </>
                                    )}

                                    <div className="relative">
                                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                        <input
                                            type="text"
                                            placeholder={isGroupMode ? "Поиск участников..." : "Фильтр..."}
                                            value={searchQuery}
                                            onChange={(e) => setSearchQuery(e.target.value)}
                                            className="w-full pl-9 pr-8 py-2 rounded-xl bg-background border text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow"
                                        />
                                        {searchQuery && (
                                            <button
                                                onClick={() => setSearchQuery('')}
                                                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded-full hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                                            >
                                                <span className="text-xs font-bold">✕</span>
                                            </button>
                                        )}
                                    </div>
                                </div>

                                {/* Scrollable employee list */}
                                <div className="flex-1 overflow-y-auto">
                                    {searchLoading ? (
                                        <div className="flex items-center justify-center py-8">
                                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                        </div>
                                    ) : searchResults.filter(u => uidOf(u) !== myUid).length > 0 ? (
                                        <div className="py-1">
                                            <p className="px-4 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                                Сотрудники · {searchResults.filter(u => uidOf(u) !== myUid).length}
                                            </p>
                                            {searchResults.filter(u => uidOf(u) !== myUid).map(user => {
                                                // `/users/search` returns the platform user brief
                                                // (`id`, no `user_id` alias) — read the id through
                                                // uidOf, never off `.user_id` directly, or every
                                                // click below builds `participant_ids: [null]`.
                                                const targetUid = uidOf(user);
                                                const isSelected = targetUid != null && selectedUserIds.includes(targetUid);
                                                return (
                                                    <button
                                                        key={targetUid ?? user.username}
                                                        onClick={() => {
                                                            if (targetUid == null) return;
                                                            if (isGroupMode) {
                                                                setSelectedUserIds(prev =>
                                                                    prev.includes(targetUid)
                                                                        ? prev.filter(id => id !== targetUid)
                                                                        : [...prev, targetUid]
                                                                );
                                                            } else {
                                                                createRoomMutation.mutate({ room_type: 'direct', member_user_ids: [targetUid] });
                                                            }
                                                        }}
                                                        className={`w-full flex items-center gap-3 px-4 py-2.5 transition-colors text-left group ${isSelected ? 'bg-primary/10 hover:bg-primary/20' : 'hover:bg-background/60'}`}
                                                    >
                                                        {user.avatar_url ? (
                                                            <img
                                                                src={user.avatar_url}
                                                                alt=""
                                                                className="w-9 h-9 rounded-full object-cover flex-shrink-0"
                                                            />
                                                        ) : (
                                                            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center text-primary font-bold text-sm flex-shrink-0 group-hover:from-primary/30 group-hover:to-primary/10 transition-all">
                                                                {user.full_name.charAt(0).toUpperCase()}
                                                            </div>
                                                        )}
                                                        <div className="flex-1 min-w-0">
                                                            <p className="text-sm font-medium truncate">{user.full_name}</p>
                                                            <p className="text-xs text-muted-foreground truncate">
                                                                {[user.position_title, user.department_name].filter(Boolean).join(' · ') || user.username}
                                                            </p>
                                                        </div>
                                                        {isGroupMode && (
                                                            <div className={`w-5 h-5 rounded-md border flex items-center justify-center flex-shrink-0 transition-colors ${isSelected ? 'bg-primary border-primary text-primary-foreground' : 'border-input bg-background group-hover:border-primary/50'}`}>
                                                                {isSelected && <Check className="h-3 w-3" />}
                                                            </div>
                                                        )}
                                                        {!isGroupMode && targetUid != null && presence[targetUid]?.online && (
                                                            <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" title="В сети" />
                                                        )}
                                                    </button>
                                                )
                                            })}
                                        </div>
                                    ) : (
                                        <div className="px-4 py-6 text-center text-muted-foreground">
                                            <User className="h-8 w-8 mx-auto mb-2 opacity-30" />
                                            <p className="text-sm">Никого не найдено</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Room List */}
                        <div className="flex-1 overflow-y-auto">
                            {roomsLoading ? (
                                <div className="flex items-center justify-center h-32">
                                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                </div>
                            ) : rooms.length === 0 ? (
                                <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8 text-center">
                                    <MessageCircle className="h-12 w-12 mb-3 opacity-30" />
                                    <p className="text-sm font-medium">Нет чатов</p>
                                    <p className="text-xs mt-1">Нажмите + чтобы начать</p>
                                </div>
                            ) : (
                                filteredRooms.map(room => {
                                    const isActive = room.id === activeRoomId;
                                    const unread = room.participants.find(m => uidOf(m) === myUid)?.unread_count || 0;

                                    return (
                                        <button
                                            key={room.id}
                                            onClick={() => { setActiveRoomId(room.id); setMobileShowChat(true); }}
                                            className={`w-full flex items-center gap-3 p-3 sm:p-4 border-b transition-colors text-left ${isActive ? 'bg-primary/5 border-l-2 border-l-primary' : 'hover:bg-accent/50'
                                                }`}
                                        >
                                            {/* Avatar */}
                                            <div className="relative flex-shrink-0">
                                                {getRoomAvatar(room) ? (
                                                    <img src={getRoomAvatar(room)} alt="" className="w-11 h-11 rounded-full object-cover" />
                                                ) : (
                                                    <div className="w-11 h-11 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                                                        {room.room_type === 'group' ? (
                                                            <Users className="h-5 w-5 text-primary/60" />
                                                        ) : room.room_type === 'secret' ? (
                                                            <Lock className="h-5 w-5 text-primary/60" />
                                                        ) : (
                                                            <span className="font-bold text-primary/60">
                                                                {getRoomDisplayName(room).charAt(0)}
                                                            </span>
                                                        )}
                                                    </div>
                                                )}
                                                {/* Онлайн-индикатор — из presence-карты (Redis + сокет),
                                                    поле other.is_online осталось от снесённой реплики
                                                    и всегда undefined. */}
                                                {room.room_type === 'direct' && me && (() => {
                                                    const other = getOtherMember(room, myUid);
                                                    const uid = uidOf(other);
                                                    return uid != null && presence[uid]?.online ? (
                                                        <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-500 rounded-full border-2 border-card" />
                                                    ) : null;
                                                })()}
                                            </div>

                                            {/* Info */}
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between">
                                                    <p className="font-medium text-sm truncate flex items-center gap-1.5">
                                                        {room.room_type === 'secret' && <Lock className="inline h-3 w-3 text-secondary" />}
                                                        <span className="truncate">{getRoomDisplayName(room)}</span>
                                                        {isBotRoom(room) && (
                                                            <span className="inline-flex items-center px-1 py-px rounded text-[9px] font-bold tracking-wide bg-primary/15 text-primary flex-shrink-0">
                                                                BOT
                                                            </span>
                                                        )}
                                                    </p>
                                                    {room.last_message && (
                                                        <span className="text-xs text-muted-foreground ml-2 flex-shrink-0">
                                                            {formatRoomLastTime(room.last_message.created_at)}
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="flex items-center justify-between mt-0.5">
                                                    <p className="text-xs text-muted-foreground truncate max-w-[180px]">
                                                        {getLastMessagePreview(room)}
                                                    </p>
                                                    {unread > 0 && (
                                                        <span className="ml-2 px-1.5 py-0.5 rounded-full bg-primary text-primary-foreground text-[10px] font-bold min-w-[18px] text-center">
                                                            {unread}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </button>
                                    );
                                })
                            )}

                            {/* Contacts not yet in any chat — surfaced only
                                when the filter is set and matched no rooms.
                                Click → spin up (or jump into) a direct chat. */}
                            {roomsFilter.trim() && filteredRooms.length === 0 && !roomsLoading && (
                                <div className="border-t bg-accent/20">
                                    <div className="px-4 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                                        Контакты
                                    </div>
                                    {directoryQuery.isFetching && (
                                        <div className="flex items-center justify-center py-4">
                                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                                        </div>
                                    )}
                                    {!directoryQuery.isFetching && (directoryQuery.data?.length ?? 0) === 0 && (
                                        <p className="px-4 py-4 text-sm text-muted-foreground">
                                            Ничего не найдено.
                                        </p>
                                    )}
                                    {!directoryQuery.isFetching && (directoryQuery.data ?? []).map((u: any) => {
                                        const uid = u.user_id ?? u.id;
                                        if (uid === myUid) return null;
                                        const name = u.full_name || [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username;
                                        return (
                                            <button
                                                key={uid}
                                                onClick={() => {
                                                    createRoomMutation.mutate({
                                                        room_type: 'direct',
                                                        member_user_ids: [uid],
                                                    });
                                                    setRoomsFilter('');
                                                }}
                                                className="w-full flex items-center gap-3 p-3 hover:bg-accent/50 transition-colors text-left"
                                            >
                                                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center flex-shrink-0">
                                                    {u.avatar_url ? (
                                                        <img src={u.avatar_url} alt="" className="w-9 h-9 rounded-full object-cover" />
                                                    ) : (
                                                        <span className="font-bold text-primary/60 text-sm">
                                                            {(name || '?').charAt(0)}
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="flex-1 min-w-0">
                                                    <p className="text-sm font-medium truncate">{name}</p>
                                                    {u.position_title && (
                                                        <p className="text-xs text-muted-foreground truncate">
                                                            {u.position_title}
                                                        </p>
                                                    )}
                                                </div>
                                                {uid != null && presence[uid]?.online && (
                                                    <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" title="В сети" />
                                                )}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* ===== RIGHT PANEL: Chat Room ===== */}
                    {/* ``min-w-0`` is critical — without it a long unbroken
                        token in a message stretches this column past 75% and
                        pushes the left chat list / right-side actions out of
                        view. */}
                    <div className={`flex-1 flex flex-col min-w-0 ${!mobileShowChat ? 'hidden sm:flex' : 'flex'}`}>
                        {activeRoom ? (
                            <>
                                {/* Chat Header */}
                                <div className="p-4 border-b flex items-center gap-3 bg-card">
                                    <button
                                        onClick={() => setMobileShowChat(false)}
                                        className="sm:hidden p-1 rounded hover:bg-accent"
                                    >
                                        <ArrowLeft className="h-5 w-5" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setInfoOpen(true)}
                                        className="flex items-center gap-3 -m-1 p-1 rounded-lg hover:bg-accent/50 transition-colors min-w-0"
                                        title="Информация о чате"
                                    >
                                        {/* Show the same avatar that the room-list row shows.
                                            Falls back to a kind-specific placeholder (secret →
                                            Lock, group → Users, direct → first letter). */}
                                        {getRoomAvatar(activeRoom) ? (
                                            <img
                                                src={getRoomAvatar(activeRoom)}
                                                alt=""
                                                className="w-9 h-9 rounded-full object-cover flex-shrink-0"
                                            />
                                        ) : (
                                            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center flex-shrink-0">
                                                {activeRoom.room_type === 'secret' ? (
                                                    <Lock className="h-4 w-4 text-primary/60" />
                                                ) : activeRoom.room_type === 'group' ? (
                                                    <Users className="h-4 w-4 text-primary/60" />
                                                ) : (
                                                    <span className="font-bold text-primary/60 text-sm">
                                                        {getRoomDisplayName(activeRoom).charAt(0)}
                                                    </span>
                                                )}
                                            </div>
                                        )}
                                        <div className="text-left min-w-0">
                                            <p className="font-medium text-sm truncate flex items-center gap-1.5">
                                                {activeRoom.room_type === 'secret' && (
                                                    <Lock className="inline h-3 w-3 text-secondary" />
                                                )}
                                                <span className="truncate">{getRoomDisplayName(activeRoom)}</span>
                                                {isBotRoom(activeRoom) && (
                                                    <span className="inline-flex items-center px-1 py-px rounded text-[9px] font-bold tracking-wide bg-primary/15 text-primary flex-shrink-0">
                                                        BOT
                                                    </span>
                                                )}
                                            </p>
                                        <p className="text-xs text-muted-foreground">
                                            {activeRoom.room_type === 'secret'
                                                ? 'Секретный чат · E2EE'
                                                : activeRoom.room_type === 'group'
                                                    ? `${activeRoom.participants.length} участников`
                                                    : (() => {
                                                        const other = me ? getOtherMember(activeRoom, myUid) : null;
                                                        const uid = uidOf(other);
                                                        const st = uid != null ? presence[uid] : undefined;
                                                        if (st?.online) return '🟢 В сети';
                                                        return st?.last_seen ? formatLastSeen(st.last_seen) : (other?.position_title || '');
                                                    })()
                                            }
                                        </p>
                                        </div>
                                    </button>
                                    <div className="ml-auto flex items-center gap-1">
                                        <button
                                            onClick={() => setSearchOpen(true)}
                                            className="p-2 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
                                            title="Поиск в чате"
                                        >
                                            <Search className="h-4 w-4" />
                                        </button>
                                        <button
                                            onClick={() => {
                                                // Owner of a group = the participant whose room role
                                                // is 'admin'. Only they get the destructive wording,
                                                // because only for them does the backend delete the
                                                // room for everyone.
                                                const myRole = activeRoom.participants.find(
                                                    (p) => uidOf(p) === myUid,
                                                )?.role;
                                                const isOwner =
                                                    activeRoom.room_type === 'group' && myRole === 'admin';
                                                const prompt = isOwner
                                                    ? `Удалить группу${activeRoom.name ? ` «${activeRoom.name}»` : ''} для всех участников? Отменить это будет нельзя.`
                                                    : activeRoom.room_type === 'group'
                                                        ? 'Выйти из группы? Она пропадёт из вашего списка.'
                                                        : 'Убрать чат из вашего списка? Он вернётся, если собеседник напишет.';
                                                if (confirm(prompt)) {
                                                    deleteRoomMutation.mutate(activeRoom.id);
                                                }
                                            }}
                                            className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                                            title="Удалить чат / выйти из группы"
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </button>
                                    </div>
                                </div>

                                <ChatSearchSheet
                                    open={searchOpen}
                                    onOpenChange={setSearchOpen}
                                    roomId={activeRoom.id}
                                    onJump={(id) => {
                                        setSearchOpen(false);
                                        // Defer the scroll to next tick so the sheet's exit
                                        // animation doesn't fight the scroll-into-view.
                                        setTimeout(() => {
                                            const el = document.querySelector(`[data-msg-id="${id}"]`);
                                            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        }, 200);
                                    }}
                                />

                                <ChatInfoDialog
                                    open={infoOpen}
                                    onOpenChange={setInfoOpen}
                                    room={activeRoom}
                                    myUid={myUid}
                                    displayName={getRoomDisplayName(activeRoom)}
                                    presence={presence}
                                    isUploadingGroupAvatar={updateRoomMutation.isPending}
                                    onGroupAvatarChange={async (file) => {
                                        try {
                                            const att = await messengerApi.uploadGroupAvatar(activeRoom.id, file);
                                            if (att?.url) {
                                                await updateRoomMutation.mutateAsync({
                                                    roomId: activeRoom.id,
                                                    payload: { avatar_url: att.url },
                                                });
                                                toast.success('Фото группы обновлено');
                                            }
                                        } catch (err) {
                                            console.warn('group avatar update failed', err);
                                            toast.error('Не удалось обновить фото группы');
                                        }
                                    }}
                                />

                                {/* Messages */}
                                <div
                                    ref={messagesScrollRef}
                                    onScroll={onMessagesScroll}
                                    className="flex-1 overflow-y-auto p-4 space-y-3 bg-accent/10"
                                >
                                    {msgsLoading ? (
                                        <div className="flex items-center justify-center h-full">
                                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                        </div>
                                    ) : orderedMessages.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                                            <MessageCircle className="h-10 w-10 mb-2 opacity-20" />
                                            <p className="text-sm">Начните разговор</p>
                                        </div>
                                    ) : (() => {
                                        // Pre-compute the highest message-index that ALL other
                                        // participants have read. Anything <= this index counts as
                                        // "read by everyone" and earns a green double-check.
                                        // Indices are derived from the (chronologically ascending)
                                        // ``orderedMessages`` so we can compare UUIDs without
                                        // hitting the DB.
                                        const indexById = new Map(orderedMessages.map((m, i) => [m.id, i]));
                                        const otherReadIdxs = activeRoom.participants
                                            .filter((p) => uidOf(p) !== myUid)
                                            .map((p) => {
                                                if (!p.last_read_message_id) return -1;
                                                return indexById.get(p.last_read_message_id) ?? -1;
                                            });
                                        const minOtherReadIdx = otherReadIdxs.length
                                            ? Math.min(...otherReadIdxs)
                                            : -1;

                                        const locale = i18n.language || 'ru-RU';
                                        const todayLabel = t('messenger.dateToday', 'Сегодня');
                                        const yesterdayLabel = t('messenger.dateYesterday', 'Вчера');

                                        return orderedMessages.map((msg, idx) => {
                                            // ``sender_id`` is the canonical column; fall back to the
                                            // nested sender object when the API echoes both shapes.
                                            const senderUid = (msg as any).sender_id ?? uidOf(msg.sender);
                                            const isMe = senderUid != null && myUid != null && senderUid === myUid;
                                            // Sender label only makes sense in groups — in a direct
                                            // chat the participant identity is already on the header.
                                            const showSenderLabel =
                                                !isMe && msg.sender && activeRoom.room_type === 'group';
                                            // Read-receipt state for outgoing messages:
                                            //  • optimistic ``id``-less / temp ids → 1 grey check (sending)
                                            //  • saved on server but not yet read    → 2 grey checks (delivered)
                                            //  • read by every other participant     → 2 green checks
                                            const isPending = !msg.id || String(msg.id).startsWith('tmp-');
                                            const isReadByOthers = !isPending && idx <= minOtherReadIdx;
                                            // Тумбстоун: сервер обнулил content/attachments, но строку
                                            // сохранил — админ-выдача по-прежнему видит оригинал.
                                            const isDeletedMsg = Boolean(msg.is_deleted);
                                            // Автор правит своё; удалять может автор ИЛИ админ группы
                                            // (тот же гейт, что в messenger_service.delete_message).
                                            const canEditMsg = isMe && !isPending && !isDeletedMsg && !msg.is_encrypted;
                                            const canDeleteMsg =
                                                !isPending && !isDeletedMsg &&
                                                (isMe || (activeRoom.room_type === 'group' && myRoleInActiveRoom === 'admin'));

                                            // Insert a date chip whenever the calendar day rolls over.
                                            const prev = idx > 0 ? orderedMessages[idx - 1] : null;
                                            const showDayDivider =
                                                !prev || !isSameLocalDay(prev.created_at, msg.created_at);
                                            const daySeparator = showDayDivider ? (
                                                <div
                                                    key={`day-${msg.id}`}
                                                    className="flex items-center justify-center my-3"
                                                >
                                                    <span className="text-[11px] uppercase tracking-wide text-muted-foreground bg-muted/60 px-3 py-1 rounded-full">
                                                        {formatDaySeparator(msg.created_at, locale, todayLabel, yesterdayLabel)}
                                                    </span>
                                                </div>
                                            ) : null;

                                            return (
                                                <React.Fragment key={msg.id}>
                                                    {daySeparator}
                                                <div
                                                    data-msg-id={msg.id}
                                                    className={`group/msg flex min-w-0 scroll-mt-20 items-center gap-1 ${isMe ? 'justify-end' : 'justify-start'}`}
                                                >
                                                    {/* Действия над сообщением — появляются при наведении,
                                                        слева от своего пузыря и справа от чужого, чтобы не
                                                        перекрывать текст. */}
                                                    {(canEditMsg || canDeleteMsg || !isDeletedMsg) && (
                                                        <div className={`flex items-center gap-0.5 opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 transition-opacity ${isMe ? 'order-0' : 'order-1'}`}>
                                                            {!isDeletedMsg && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => { setEditingMsg(null); setReplyTo(msg); }}
                                                                    className="p-1.5 rounded-full text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                    title="Ответить"
                                                                >
                                                                    <ReplyIcon className="h-3.5 w-3.5" />
                                                                </button>
                                                            )}
                                                            {canEditMsg && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        setReplyTo(null);
                                                                        setEditingMsg(msg);
                                                                        const decoded = decodeMessageText(msg);
                                                                        setMessageText(
                                                                            typeof decoded === 'string' ? decoded : decoded.text || '',
                                                                        );
                                                                    }}
                                                                    className="p-1.5 rounded-full text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                    title="Редактировать"
                                                                >
                                                                    <Pencil className="h-3.5 w-3.5" />
                                                                </button>
                                                            )}
                                                            {canDeleteMsg && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        if (confirm('Удалить сообщение?')) {
                                                                            deleteMsgMutation.mutate(String(msg.id));
                                                                        }
                                                                    }}
                                                                    className="p-1.5 rounded-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                                                                    title="Удалить"
                                                                >
                                                                    <Trash2 className="h-3.5 w-3.5" />
                                                                </button>
                                                            )}
                                                        </div>
                                                    )}
                                                    {/* ``max-w-[75%]`` caps the bubble width; ``min-w-0`` lets
                                                        the flex parent shrink instead of pushing siblings. */}
                                                    <div className={`min-w-0 max-w-[75%] ${isMe ? 'order-1' : 'order-0'}`}>
                                                        {showSenderLabel && (
                                                            <p className="text-xs text-muted-foreground mb-1 ml-1">
                                                                {(msg.sender as any)?.full_name || msg.sender?.username}
                                                            </p>
                                                        )}
                                                        <div
                                                            className={`px-3.5 py-2 rounded-2xl text-sm leading-relaxed ${isDeletedMsg
                                                                ? 'bg-muted/50 border border-dashed text-muted-foreground italic rounded-bl-md'
                                                                : isMe
                                                                ? 'bg-primary text-primary-foreground rounded-br-md'
                                                                : 'bg-card border rounded-bl-md shadow-sm'
                                                                }`}
                                                        >
                                                            {/* Цитата: снапшот, сделанный сервером при отправке —
                                                                остаётся читаемой, даже если оригинал потом
                                                                отредактировали или удалили. */}
                                                            {msg.reply_to && !isDeletedMsg && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        const el = document.querySelector(`[data-msg-id="${msg.reply_to!.id}"]`);
                                                                        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                                                    }}
                                                                    className={`mb-1.5 w-full text-left border-l-2 pl-2 py-0.5 rounded-sm transition-colors ${isMe
                                                                        ? 'border-primary-foreground/50 bg-primary-foreground/10 hover:bg-primary-foreground/20'
                                                                        : 'border-primary/50 bg-primary/5 hover:bg-primary/10'
                                                                        }`}
                                                                >
                                                                    <span className={`block text-[11px] font-semibold ${isMe ? 'text-primary-foreground/80' : 'text-primary'}`}>
                                                                        {msg.reply_to.sender_name || 'Сообщение'}
                                                                    </span>
                                                                    <span className={`block text-xs truncate ${isMe ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                                                                        {msg.reply_to.preview || 'вложение'}
                                                                    </span>
                                                                </button>
                                                            )}
                                                            {/* ``overflow-wrap: anywhere`` forces breaking even
                                                                inside a single long token (URL, ``aaaaa…``) so
                                                                the bubble can't push the layout off-screen. */}
                                                            <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                                                                {isDeletedMsg ? 'Сообщение удалено' : (() => {
                                                                    const decoded = decodeMessageText(msg);
                                                                    if (typeof decoded === 'object') {
                                                                        const isAudio = decoded.mime_type?.startsWith('audio/');
                                                                        const isImage = decoded.mime_type?.startsWith('image/');
                                                                        return (
                                                                            <div className="flex flex-col gap-2">
                                                                                {decoded.text && <p className="text-sm mb-1">{decoded.text}</p>}
                                                                                {isAudio ? (
                                                                                    <VoiceMessagePlayer
                                                                                        src={decoded.file_url || ''}
                                                                                        filename={decoded.file_name}
                                                                                        isMine={isMe}
                                                                                    />
                                                                                ) : isImage ? (
                                                                                    <ChatImageAttachment
                                                                                        src={decoded.file_url || ''}
                                                                                        thumbSrc={decoded.thumb_url ?? null}
                                                                                        filename={decoded.file_name}
                                                                                        width={decoded.width ?? null}
                                                                                        height={decoded.height ?? null}
                                                                                    />
                                                                                ) : (
                                                                                    <div className="flex items-center gap-2 bg-background/20 p-2 rounded-lg">
                                                                                        <FileText className="h-5 w-5 opacity-70" />
                                                                                        <span className="text-sm font-medium truncate max-w-[150px]" title={decoded.file_name}>{decoded.file_name || 'Файл'}</span>
                                                                                        <a
                                                                                            href={decoded.file_url}
                                                                                            target="_blank"
                                                                                            rel="noreferrer"
                                                                                            download={decoded.file_name}
                                                                                            className="ml-2 p-1.5 bg-background/30 rounded-full hover:bg-background/50 transition-colors"
                                                                                            title="Скачать"
                                                                                        >
                                                                                            <Download className="h-4 w-4" />
                                                                                        </a>
                                                                                    </div>
                                                                                )}
                                                                            </div>
                                                                        )
                                                                    }
                                                                    return decoded;
                                                                })()}
                                                            </div>
                                                            <p className={`text-[10px] mt-1 flex items-center justify-end gap-1 ${isDeletedMsg ? 'text-muted-foreground' : isMe ? 'text-primary-foreground/60' : 'text-muted-foreground'
                                                                }`}>
                                                                {msg.is_edited && !isDeletedMsg && (
                                                                    <span title="Отредактировано">изменено</span>
                                                                )}
                                                                {formatTime(msg.created_at)}
                                                                {isMe && !isDeletedMsg && (
                                                                    isPending ? (
                                                                        <Check className="h-3 w-3 opacity-60" aria-label="Отправляется" />
                                                                    ) : isReadByOthers ? (
                                                                        <CheckCheck className="h-3 w-3 text-emerald-300" aria-label="Прочитано" />
                                                                    ) : (
                                                                        <CheckCheck className="h-3 w-3 opacity-60" aria-label="Доставлено" />
                                                                    )
                                                                )}
                                                            </p>
                                                        </div>
                                                    </div>
                                                </div>
                                                </React.Fragment>
                                            );
                                        });
                                    })()}
                                    <div ref={messagesEndRef} />
                                </div>

                                {/* Message Input */}
                                <div className="p-3 border-t bg-card">
                                    {/* Режим ответа или редактирования — взаимоисключающие,
                                        оба сбрасываются крестиком или после отправки. */}
                                    {(replyTo || editingMsg) && (
                                        <div className="mb-2 flex items-center gap-2 border-l-2 border-primary bg-primary/5 pl-2 pr-1 py-1.5 rounded-r-lg">
                                            {editingMsg ? (
                                                <Pencil className="h-4 w-4 text-primary flex-shrink-0" />
                                            ) : (
                                                <ReplyIcon className="h-4 w-4 text-primary flex-shrink-0" />
                                            )}
                                            <div className="min-w-0 flex-1">
                                                <p className="text-xs font-semibold text-primary">
                                                    {editingMsg
                                                        ? 'Редактирование'
                                                        : `Ответ · ${(replyTo!.sender as any)?.full_name || replyTo!.sender?.username || 'сообщение'}`}
                                                </p>
                                                <p className="text-xs text-muted-foreground truncate">
                                                    {(() => {
                                                        const src = editingMsg || replyTo!;
                                                        const decoded = decodeMessageText(src);
                                                        const text = typeof decoded === 'string' ? decoded : decoded.text;
                                                        return text || src.attachments?.[0]?.filename || 'вложение';
                                                    })()}
                                                </p>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    if (editingMsg) setMessageText('');
                                                    setReplyTo(null);
                                                    setEditingMsg(null);
                                                }}
                                                className="p-1.5 rounded-full hover:bg-accent transition-colors flex-shrink-0"
                                                title="Отменить"
                                            >
                                                <X className="h-4 w-4 text-muted-foreground" />
                                            </button>
                                        </div>
                                    )}
                                    {isRecording && (
                                        <div className="mb-2 flex items-center justify-between gap-2 bg-destructive/10 border border-destructive/30 p-2 rounded-lg max-w-sm">
                                            <div className="flex items-center gap-2 min-w-0">
                                                <span className="relative flex h-3 w-3">
                                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-destructive opacity-75"></span>
                                                    <span className="relative inline-flex rounded-full h-3 w-3 bg-destructive"></span>
                                                </span>
                                                <span className="text-sm font-medium tabular-nums">
                                                    {t('messenger.audio.recording', 'Запись')}
                                                    {' · '}
                                                    {formatRecordingDuration(recordingDuration)}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-1">
                                                <button
                                                    type="button"
                                                    onClick={cancelRecording}
                                                    className="p-1.5 hover:bg-destructive/20 rounded-full transition-colors"
                                                    title={t('messenger.audio.cancel', 'Отменить')}
                                                >
                                                    <Trash2 className="h-4 w-4 text-destructive" />
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={finishRecording}
                                                    className="p-1.5 hover:bg-primary/20 rounded-full transition-colors"
                                                    title={t('messenger.audio.finish', 'Готово')}
                                                >
                                                    <Check className="h-4 w-4 text-primary" />
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                    {selectedFile && (
                                        <div className="mb-2 flex items-center justify-between gap-2 bg-accent/30 p-2 rounded-lg border border-accent max-w-sm">
                                            <div className="flex items-center gap-2 min-w-0">
                                                {selectedFile.type.startsWith('audio/') ? <Music className="h-4 w-4 text-primary flex-shrink-0" /> : <FileText className="h-4 w-4 text-primary flex-shrink-0" />}
                                                <span className="text-sm font-medium truncate">{selectedFile.name}</span>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => { setSelectedFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
                                                className="p-1 hover:bg-background rounded-full transition-colors flex-shrink-0"
                                                title="Удалить файл"
                                            >
                                                <X className="h-4 w-4 text-muted-foreground hover:text-destructive transition-colors" />
                                            </button>
                                        </div>
                                    )}
                                    <div className="flex items-end gap-2">
                                        <input
                                            type="file"
                                            ref={fileInputRef}
                                            onChange={handleFileSelect}
                                            className="hidden"
                                            accept=".zip,.rar,.doc,.docx,.xls,.xlsx,.pdf,audio/*,image/*,.1c"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => fileInputRef.current?.click()}
                                            disabled={uploadingFile || isRecording}
                                            className="p-2.5 rounded-xl bg-accent text-accent-foreground hover:bg-accent/80 transition-colors disabled:opacity-40"
                                            title={t('messenger.attachFile', 'Прикрепить файл')}
                                        >
                                            {uploadingFile ? <Loader2 className="h-5 w-5 animate-spin" /> : <Paperclip className="h-5 w-5" />}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={isRecording ? finishRecording : startRecording}
                                            disabled={uploadingFile || sendMutation.isPending || (!!selectedFile && !isRecording)}
                                            className={`p-2.5 rounded-xl transition-colors disabled:opacity-40 ${
                                                isRecording
                                                    ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                                                    : 'bg-accent text-accent-foreground hover:bg-accent/80'
                                            }`}
                                            title={
                                                isRecording
                                                    ? t('messenger.audio.stop', 'Остановить запись')
                                                    : t('messenger.audio.record', 'Записать аудио')
                                            }
                                        >
                                            {isRecording ? <Square className="h-5 w-5 fill-current" /> : <Mic className="h-5 w-5" />}
                                        </button>
                                        <textarea
                                            value={messageText}
                                            onChange={(e) => setMessageText(e.target.value)}
                                            onKeyDown={handleKeyDown}
                                            placeholder="Написать сообщение..."
                                            className="flex-1 resize-none rounded-xl border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 max-h-32"
                                            rows={1}
                                        />
                                        <button
                                            onClick={handleSend}
                                            disabled={(!messageText.trim() && !selectedFile) || sendMutation.isPending || uploadingFile}
                                            className="p-2.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                        >
                                            {sendMutation.isPending || uploadingFile ? (
                                                <Loader2 className="h-5 w-5 animate-spin" />
                                            ) : (
                                                <Send className="h-5 w-5" />
                                            )}
                                        </button>
                                    </div>
                                </div>
                            </>
                        ) : (
                            /* Empty state */
                            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
                                <div className="w-24 h-24 rounded-full bg-primary/5 flex items-center justify-center mb-4">
                                    <MessageCircle className="h-12 w-12 text-primary/30" />
                                </div>
                                <p className="font-medium text-lg">Мессенджер</p>
                                <p className="text-sm mt-1 max-w-xs text-center">
                                    Выберите чат слева или создайте новый, чтобы начать общение с коллегами
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
};

export default MessengerPage;
