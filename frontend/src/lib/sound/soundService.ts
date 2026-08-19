/**
 * Sound Service — high-fidelity Web Audio API sound synthesis.
 *
 * Provides pleasant, non-fatiguing audio notifications for:
 * - Messenger: Warm Kalimba chime / Bubble pop
 * - Calendar & Conferences: Executive bell / Event created chord
 * - Deadlines & Tasks: Gentle focus pulse / Urgent deadline chime
 *
 * Key features:
 * - Zero external asset downloads (100% mathematical Web Audio synthesis)
 * - Automatic Autoplay Policy unlock on first user gesture
 * - Master volume and Mute settings persisted to localStorage
 * - Anti-spam throttling to prevent audio clutter on bulk notifications
 */

export interface SoundSettings {
  enabled: boolean;
  volume: number; // 0.0 to 1.0
}

const STORAGE_KEY = 'htq:sound:settings';

// Default sound settings
const defaultSettings: SoundSettings = {
  enabled: true,
  volume: 0.75,
};

// Cached settings in memory
let currentSettings: SoundSettings = (() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultSettings;
    const parsed = JSON.parse(raw);
    return {
      enabled: typeof parsed.enabled === 'boolean' ? parsed.enabled : defaultSettings.enabled,
      volume: typeof parsed.volume === 'number' ? Math.max(0, Math.min(1, parsed.volume)) : defaultSettings.volume,
    };
  } catch {
    return defaultSettings;
  }
})();

// Listeners for setting updates
type SettingsListener = (settings: SoundSettings) => void;
const listeners = new Set<SettingsListener>();

export function getSoundSettings(): SoundSettings {
  return { ...currentSettings };
}

export function updateSoundSettings(newSettings: Partial<SoundSettings>): SoundSettings {
  currentSettings = {
    ...currentSettings,
    ...newSettings,
    volume: newSettings.volume !== undefined
      ? Math.max(0, Math.min(1, newSettings.volume))
      : currentSettings.volume,
  };

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(currentSettings));
  } catch {
    // quota / private mode
  }

  listeners.forEach((fn) => fn(currentSettings));
  return currentSettings;
}

export function toggleSound(): boolean {
  const updated = updateSoundSettings({ enabled: !currentSettings.enabled });
  return updated.enabled;
}

export function setSoundVolume(volume: number): void {
  updateSoundSettings({ volume });
}

export function subscribeSoundSettings(listener: SettingsListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ---------------------------------------------------------------------------
// Audio Context Management
// ---------------------------------------------------------------------------
let audioCtx: AudioContext | null = null;
let masterGain: GainNode | null = null;

function getAudioContext(): { ctx: AudioContext; master: GainNode } | null {
  if (typeof window === 'undefined') return null;

  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return null;
    audioCtx = new AudioContextClass();

    masterGain = audioCtx.createGain();
    masterGain.gain.setValueAtTime(currentSettings.volume, audioCtx.currentTime);
    masterGain.connect(audioCtx.destination);

    // Auto-resume suspended AudioContext on user interaction
    const unlock = () => {
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
  }

  if (audioCtx.state === 'suspended') {
    audioCtx.resume().catch(() => {});
  }

  if (masterGain) {
    // Keep master gain synced with current volume
    masterGain.gain.setValueAtTime(
      currentSettings.enabled ? currentSettings.volume : 0,
      audioCtx.currentTime,
    );
  }

  return { ctx: audioCtx, master: masterGain! };
}

// ---------------------------------------------------------------------------
// Throttling / Anti-spam
// ---------------------------------------------------------------------------
let lastPlayTimestamp = 0;
const THROTTLE_MS = 1200; // Minimum time between consecutive notification sounds

function shouldThrottle(bypassThrottle = false): boolean {
  if (!currentSettings.enabled || currentSettings.volume <= 0) return true;
  if (bypassThrottle) return false;

  const now = Date.now();
  if (now - lastPlayTimestamp < THROTTLE_MS) {
    return true;
  }
  lastPlayTimestamp = now;
  return false;
}

// ---------------------------------------------------------------------------
// Synthesizer Presets
// ---------------------------------------------------------------------------

/**
 * 1. Warm Kalimba Chime (Мессенджер — входящее сообщение)
 * Двухнотный восходящий перезвон (E5: 659.25Hz -> A5: 880Hz) с мягким затуханием.
 */
export function playMessengerChime(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const playTone = (freq: number, start: number, duration: number, peakGain: number) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);

    // Мягкая атака (15 мс) и экспоненциальный спад
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(peakGain, start + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(master);

    osc.start(start);
    osc.stop(start + duration);
  };

  playTone(659.25, now, 0.28, 0.22);
  playTone(880.00, now + 0.075, 0.38, 0.25);
}

/**
 * 2. Bubble Pop / Dewdrop (Органичный мягкий "бульк" для активного окна диалога)
 */
export function playMessengerPop(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = 'sine';
  osc.frequency.setValueAtTime(420, now);
  osc.frequency.exponentialRampToValueAtTime(880, now + 0.07);

  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.24, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.16);

  osc.connect(gain);
  gain.connect(master);

  osc.start(now);
  osc.stop(now + 0.16);
}

/**
 * 3. Executive Bell / Ding-Dong (Конференции и созвоны — напоминание за 5 мин / 1 мин)
 * Элегантный перезвон высокой четкости (A5: 880Hz -> D5: 587.33Hz) с гармоникой.
 */
export function playMeetingReminder(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const playBell = (freq: number, start: number, duration: number, peakGain: number) => {
    const osc = ctx.createOscillator();
    const overtone = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);

    overtone.type = 'triangle';
    overtone.frequency.setValueAtTime(freq * 2.01, start);

    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(peakGain, start + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    overtone.connect(gain);
    gain.connect(master);

    osc.start(start);
    overtone.start(start);
    osc.stop(start + duration);
    overtone.stop(start + duration);
  };

  playBell(880.00, now, 0.55, 0.22);
  playBell(587.33, now + 0.18, 0.75, 0.25);
}

/**
 * 4. Schedule Snap (Событие или встреча назначена / добавлена в календарь)
 * Восходящий мажорный аккорд (C5 -> E5 -> G5 -> C6).
 */
export function playEventCreated(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
  notes.forEach((freq, idx) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const start = now + idx * 0.045;
    const duration = 0.32;

    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(0.16, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(master);

    osc.start(start);
    osc.stop(start + duration);
  });
}

/**
 * 5. Deadline Warning / Focus Pulse (Приближение дедлайна задачи)
 * Двойной спокойный, бархатный пульс ("Тук... тук"), создающий фокус без стресса.
 */
export function playDeadlineWarning(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const playPulse = (start: number, freq: number) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);
    osc.frequency.exponentialRampToValueAtTime(freq * 0.72, start + 0.2);

    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(0.26, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, start + 0.24);

    osc.connect(gain);
    gain.connect(master);

    osc.start(start);
    osc.stop(start + 0.24);
  };

  playPulse(now, 320);
  playPulse(now + 0.16, 380);
}

/**
 * 6. Critical Urgent Alert (Критический дедлайн: < 15 мин / высокая срочность)
 * Трёхкратный акцентированный сигнал.
 */
export function playDeadlineUrgent(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const steps = [
    { freq: 440.00, start: now, duration: 0.14 },
    { freq: 440.00, start: now + 0.10, duration: 0.14 },
    { freq: 587.33, start: now + 0.22, duration: 0.28 },
  ];

  steps.forEach(({ freq, start, duration }) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(0.20, start + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.001, start + duration);

    osc.connect(gain);
    gain.connect(master);

    osc.start(start);
    osc.stop(start + duration);
  });
}

/**
 * 7. Ambient Glass Sparkle (Хрустальный аккорд для общих приятных системных уведомлений)
 */
export function playGlassChime(options?: { bypassThrottle?: boolean }): void {
  if (shouldThrottle(options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const { ctx, master } = audio;
  const now = ctx.currentTime;

  const notes = [739.99, 932.33, 1108.73]; // F#5, A#5, C#6
  notes.forEach((freq, idx) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const start = now + idx * 0.04;
    const duration = 0.36;

    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(0.12, start + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(master);

    osc.start(start);
    osc.stop(start + duration);
  });
}

/**
 * Smart notification dispatcher — выбирает и воспроизводит подходящий
 * звук на основе типа и содержания уведомления.
 */
export function playNotificationSound(notification: {
  target_type?: string | null;
  verb?: string | null;
  [key: string]: any;
}): void {
  const target = notification.target_type || '';
  const verb = (notification.verb || '').toLowerCase();

  // 1. Messenger / Comments
  if (target === 'messenger_room' || verb.includes('сообщение') || verb.includes('комментарий')) {
    playMessengerChime();
    return;
  }

  // 2. Calendar / Conferences
  if (
    target === 'calendar_event' ||
    verb.includes('calendar') ||
    verb.includes('конференц') ||
    verb.includes('созвон') ||
    verb.includes('встреч')
  ) {
    if (verb.includes('напоминан') || verb.includes('начинается') || verb.includes('скоро')) {
      playMeetingReminder();
    } else {
      playEventCreated();
    }
    return;
  }

  // 3. Tasks & Deadlines
  if (
    target === 'task' ||
    verb.includes('task') ||
    verb.includes('задач') ||
    verb.includes('дедлайн') ||
    verb.includes('срок')
  ) {
    if (verb.includes('срочн') || verb.includes('просроч') || verb.includes('критич')) {
      playDeadlineUrgent();
    } else if (verb.includes('дедлайн') || verb.includes('истекает') || verb.includes('скоро')) {
      playDeadlineWarning();
    } else {
      playGlassChime();
    }
    return;
  }

  // 4. Default system chime
  playGlassChime();
}
