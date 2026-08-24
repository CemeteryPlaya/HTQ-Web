/**
 * Звуковые уведомления — синтез через Web Audio, без единого внешнего файла.
 *
 * Единственная точка воспроизведения: раньше звук был собран прямо в
 * ConferenceNotifier осциллятором на месте, без громкости, выключателя и
 * защиты от очереди сообщений.
 *
 * Три вещи, которые здесь сделаны намеренно и легко ломаются при правке:
 *
 * 1. **Ничего не планируется на приостановленном контексте.** Пока
 *    пользователь не взаимодействовал со страницей, браузер держит
 *    AudioContext в состоянии `suspended`, и его `currentTime` НЕ ИДЁТ.
 *    Запланированные в это время сигналы копятся на одной и той же метке и
 *    при первом клике бьют залпом, накладываясь друг на друга. Поэтому
 *    воспроизведение просто пропускается, пока контекст не `running`:
 *    пропущенный сигнал лучше, чем дюжина одновременных.
 *
 * 2. **Троттлинг — на каждый вид звука отдельно.** Общее окно приводило к
 *    тому, что болтовня в чате глушила напоминание о созвоне, то есть ровно
 *    то, ради чего звук нужен.
 *
 * 3. **Вид сигнала выбирается по машинным полям уведомления**, а не по
 *    русским подстрокам: бэкенд шлёт слаги (`chat_message`,
 *    `calendar_event_starts_in_5m`, `task_due_3d`), и разбор текста молча
 *    выродился бы в дефолтный сигнал при любой правке формулировок.
 *
 * Громкость двухуровневая: общий регулятор — одна ручка «сделай потише всё»,
 * персональный у каждого сигнала — множитель к ней, задающий баланс. В графе
 * это два узла подряд: `огибающая → kindGain → masterGain → выход`.
 */

/** Вид сигнала. Он же ключ троттлинга и ключ персональных настроек. */
export type SoundKind =
  | 'messenger'
  | 'messenger-active'
  | 'meeting'
  | 'event'
  | 'deadline'
  | 'deadline-urgent'
  | 'system';

export const SOUND_KINDS: readonly SoundKind[] = [
  'messenger',
  'messenger-active',
  'meeting',
  'event',
  'deadline',
  'deadline-urgent',
  'system',
] as const;

/** Настройки одного сигнала. */
export interface KindSettings {
  enabled: boolean;
  /**
   * Множитель к общей громкости, 0…1. Именно множитель, а не независимое
   * значение: общий регулятор остаётся одной ручкой «сделай потише всё», а
   * персональный задаёт баланс между сигналами. Иначе, приглушив общий звук,
   * пользователь всё равно получал бы громкий срочный дедлайн.
   */
  volume: number;
}

export interface SoundSettings {
  enabled: boolean;
  volume: number; // 0.0 … 1.0
  kinds: Record<SoundKind, KindSettings>;
}

const STORAGE_KEY = 'htq:sound:settings';

const clampVolume = (value: number) => Math.max(0, Math.min(1, value));

const defaultKindSettings = (): Record<SoundKind, KindSettings> =>
  SOUND_KINDS.reduce((acc, kind) => {
    acc[kind] = { enabled: true, volume: 1 };
    return acc;
  }, {} as Record<SoundKind, KindSettings>);

const defaultSettings = (): SoundSettings => ({
  enabled: true,
  volume: 0.75,
  kinds: defaultKindSettings(),
});

/** Разобрать сохранённую карту сигналов, добив недостающие умолчаниями.
 *
 *  Добить обязательно: в хранилище лежат настройки, записанные ДО появления
 *  персональных громкостей, и половина кода дальше обращается к
 *  ``settings.kinds[kind]`` без проверок. */
function readStoredKinds(raw: unknown): Record<SoundKind, KindSettings> {
  const result = defaultKindSettings();
  if (!raw || typeof raw !== 'object') return result;
  const source = raw as Partial<Record<SoundKind, Partial<KindSettings>>>;
  SOUND_KINDS.forEach((kind) => {
    const stored = source[kind];
    if (!stored || typeof stored !== 'object') return;
    if (typeof stored.enabled === 'boolean') result[kind].enabled = stored.enabled;
    if (typeof stored.volume === 'number') result[kind].volume = clampVolume(stored.volume);
  });
  return result;
}

function readStoredSettings(): SoundSettings {
  const fallback = defaultSettings();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<SoundSettings>;
    return {
      enabled: typeof parsed.enabled === 'boolean' ? parsed.enabled : fallback.enabled,
      volume: typeof parsed.volume === 'number' ? clampVolume(parsed.volume) : fallback.volume,
      kinds: readStoredKinds(parsed.kinds),
    };
  } catch {
    // приватный режим / битый JSON — работаем на умолчаниях
    return fallback;
  }
}

let currentSettings: SoundSettings = readStoredSettings();

type SettingsListener = (settings: SoundSettings) => void;
const listeners = new Set<SettingsListener>();

export function getSoundSettings(): SoundSettings {
  // Глубокая копия карты: иначе вызывающий правил бы настройки в обход
  // updateSoundSettings, и ни подписчики, ни localStorage об этом не узнали бы.
  return {
    ...currentSettings,
    kinds: SOUND_KINDS.reduce((acc, kind) => {
      acc[kind] = { ...currentSettings.kinds[kind] };
      return acc;
    }, {} as Record<SoundKind, KindSettings>),
  };
}

/** Громкость конкретного сигнала с учётом общего регулятора. */
export function effectiveVolume(kind: SoundKind): number {
  if (!currentSettings.enabled) return 0;
  const own = currentSettings.kinds[kind];
  if (!own || !own.enabled) return 0;
  return clampVolume(currentSettings.volume) * clampVolume(own.volume);
}

export function updateSoundSettings(newSettings: Partial<SoundSettings>): SoundSettings {
  currentSettings = {
    ...currentSettings,
    ...newSettings,
    volume: newSettings.volume !== undefined
      ? clampVolume(newSettings.volume)
      : currentSettings.volume,
  };

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(currentSettings));
  } catch {
    // quota / private mode — настройка доживёт до конца сессии в памяти
  }

  applyVolume();
  applyKindVolumes();
  listeners.forEach((fn) => fn(currentSettings));
  return currentSettings;
}

/** Изменить настройки ОДНОГО сигнала, не трогая остальные. */
export function updateKindSettings(
  kind: SoundKind, patch: Partial<KindSettings>,
): SoundSettings {
  const own = currentSettings.kinds[kind] ?? { enabled: true, volume: 1 };
  return updateSoundSettings({
    kinds: {
      ...currentSettings.kinds,
      [kind]: {
        enabled: patch.enabled ?? own.enabled,
        volume: patch.volume !== undefined ? clampVolume(patch.volume) : own.volume,
      },
    },
  });
}

export function toggleSound(): boolean {
  return updateSoundSettings({ enabled: !currentSettings.enabled }).enabled;
}

export function setSoundVolume(volume: number): void {
  updateSoundSettings({ volume });
}

export function subscribeSoundSettings(listener: SettingsListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Соседняя вкладка того же браузера пишет в тот же localStorage. Без этой
// подписки выключенный в одной вкладке звук продолжал бы звонить в другой.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY) return;
    currentSettings = readStoredSettings();
    applyVolume();
    applyKindVolumes();
    listeners.forEach((fn) => fn(currentSettings));
  });
}

// ---------------------------------------------------------------------------
// AudioContext
// ---------------------------------------------------------------------------

type AudioContextCtor = new () => AudioContext;

let audioCtx: AudioContext | null = null;
let masterGain: GainNode | null = null;
let unlockBound = false;

function resolveAudioContextCtor(): AudioContextCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as Window & { webkitAudioContext?: AudioContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

/** Громкость мастера. ``setTargetAtTime``, а не ``setValueAtTime``: мгновенный
 *  скачок во время звучащего сигнала слышен как щелчок. */
function applyVolume(): void {
  if (!audioCtx || !masterGain) return;
  const target = currentSettings.enabled ? currentSettings.volume : 0;
  masterGain.gain.setTargetAtTime(target, audioCtx.currentTime, 0.015);
}

/**
 * Узел громкости конкретного сигнала: ``osc → огибающая → kindGain → master``.
 *
 * По одному постоянному узлу на вид, а не по узлу на воспроизведение: узел,
 * подключённый к мастеру, живёт, пока подключён, и создавать его на каждое
 * уведомление значило бы растить граф всю жизнь вкладки.
 *
 * Благодаря этому слою сами пресеты синтеза о персональной громкости не знают
 * — они как подключались к переданному узлу, так и подключаются.
 */
const kindGains = new Map<SoundKind, GainNode>();

function getKindGain(ctx: AudioContext, master: GainNode, kind: SoundKind): GainNode {
  let node = kindGains.get(kind);
  if (!node) {
    node = ctx.createGain();
    node.connect(master);
    kindGains.set(kind, node);
  }
  const own = currentSettings.kinds[kind];
  node.gain.setValueAtTime(own ? clampVolume(own.volume) : 1, ctx.currentTime);
  return node;
}

/** Подтянуть персональные громкости к уже созданным узлам. */
function applyKindVolumes(): void {
  if (!audioCtx) return;
  kindGains.forEach((node, kind) => {
    const own = currentSettings.kinds[kind];
    node.gain.setTargetAtTime(
      own ? clampVolume(own.volume) : 1, audioCtx!.currentTime, 0.015,
    );
  });
}

/** Разблокировка по первому жесту. Слушатели постоянные, а не ``once``:
 *  браузер вправе приостановить контекст снова (например, когда вкладку
 *  свернули на телефоне), и одноразовой подписки на второй раз не хватит. */
function bindUnlock(): void {
  if (unlockBound || typeof window === 'undefined') return;
  unlockBound = true;
  const unlock = () => {
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);
}

/**
 * Готовый к работе контекст, либо ``null``, если играть сейчас нельзя.
 *
 * ``null`` при `state !== 'running'` — не осторожность, а необходимость:
 * см. пункт 1 в докстринге модуля.
 */
function getAudioContext(): { ctx: AudioContext; master: GainNode } | null {
  const Ctor = resolveAudioContextCtor();
  if (!Ctor) return null;

  if (!audioCtx) {
    audioCtx = new Ctor();
    masterGain = audioCtx.createGain();
    masterGain.gain.setValueAtTime(
      currentSettings.enabled ? currentSettings.volume : 0,
      audioCtx.currentTime,
    );
    masterGain.connect(audioCtx.destination);
    // Узлы прошлого контекста принадлежат уже мёртвому графу.
    kindGains.clear();
    bindUnlock();
  }

  if (audioCtx.state !== 'running') {
    audioCtx.resume().catch(() => {});
    return null;
  }

  if (!masterGain) return null;
  return { ctx: audioCtx, master: masterGain };
}

// ---------------------------------------------------------------------------
// Троттлинг
// ---------------------------------------------------------------------------

const THROTTLE_MS = 1200;
const lastPlayAt = new Map<SoundKind, number>();

function shouldSkip(kind: SoundKind, bypassThrottle = false): boolean {
  // Один вопрос вместо трёх: общий выключатель, общая громкость, выключатель и
  // громкость самого сигнала — всё уже сведено в effectiveVolume.
  if (effectiveVolume(kind) <= 0) return true;
  if (bypassThrottle) return false;

  const now = Date.now();
  const last = lastPlayAt.get(kind) ?? 0;
  if (now - last < THROTTLE_MS) return true;

  lastPlayAt.set(kind, now);
  return false;
}

interface PlayOptions {
  /** Предпрослушивание в настройках: играет всегда и не съедает окно троттлинга. */
  bypassThrottle?: boolean;
}

/** Общая обвязка: проверки, контекст, время старта. */
function withAudio(
  kind: SoundKind,
  options: PlayOptions | undefined,
  render: (ctx: AudioContext, output: GainNode, now: number) => void,
): void {
  if (shouldSkip(kind, options?.bypassThrottle)) return;
  const audio = getAudioContext();
  if (!audio) return;
  const output = getKindGain(audio.ctx, audio.master, kind);
  render(audio.ctx, output, audio.ctx.currentTime);
}

// ---------------------------------------------------------------------------
// Пресеты синтеза
// ---------------------------------------------------------------------------

/** Тёплая калимба (входящее сообщение): восходящий E5 → A5 с мягким спадом. */
export function playMessengerChime(options?: PlayOptions): void {
  withAudio('messenger', options, (ctx, output, now) => {
    const playTone = (freq: number, start: number, duration: number, peakGain: number) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, start);

      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(peakGain, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

      osc.connect(gain);
      gain.connect(output);
      osc.start(start);
      osc.stop(start + duration);
    };

    playTone(659.25, now, 0.28, 0.22);
    playTone(880.0, now + 0.075, 0.38, 0.25);
  });
}

/** Капля росы: короткий «бульк» для чата, который сейчас открыт. */
export function playMessengerPop(options?: PlayOptions): void {
  withAudio('messenger-active', options, (ctx, output, now) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(420, now);
    osc.frequency.exponentialRampToValueAtTime(880, now + 0.07);

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.24, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.16);

    osc.connect(gain);
    gain.connect(output);
    osc.start(now);
    osc.stop(now + 0.16);
  });
}

/** Колокольчик «динь-дон» (A5 → D5 с обертоном): созвон вот-вот начнётся. */
export function playMeetingReminder(options?: PlayOptions): void {
  withAudio('meeting', options, (ctx, output, now) => {
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
      gain.connect(output);

      osc.start(start);
      overtone.start(start);
      osc.stop(start + duration);
      overtone.stop(start + duration);
    };

    playBell(880.0, now, 0.55, 0.22);
    playBell(587.33, now + 0.18, 0.75, 0.25);
  });
}

/** Восходящий мажорный аккорд C5 → C6: событие добавлено в календарь. */
export function playEventCreated(options?: PlayOptions): void {
  withAudio('event', options, (ctx, output, now) => {
    [523.25, 659.25, 783.99, 1046.5].forEach((freq, idx) => {
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
      gain.connect(output);
      osc.start(start);
      osc.stop(start + duration);
    });
  });
}

/** Двойной спокойный пульс: срок задачи приближается. */
export function playDeadlineWarning(options?: PlayOptions): void {
  withAudio('deadline', options, (ctx, output, now) => {
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
      gain.connect(output);
      osc.start(start);
      osc.stop(start + 0.24);
    };

    playPulse(now, 320);
    playPulse(now + 0.16, 380);
  });
}

/** Трёхкратный акцент: срок истёк или истекает сегодня. */
export function playDeadlineUrgent(options?: PlayOptions): void {
  withAudio('deadline-urgent', options, (ctx, output, now) => {
    const steps = [
      { freq: 440.0, start: now, duration: 0.14 },
      { freq: 440.0, start: now + 0.1, duration: 0.14 },
      { freq: 587.33, start: now + 0.22, duration: 0.28 },
    ];

    steps.forEach(({ freq, start, duration }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, start);

      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.2, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.001, start + duration);

      osc.connect(gain);
      gain.connect(output);
      osc.start(start);
      osc.stop(start + duration);
    });
  });
}

/** Хрустальный перелив: всё остальное. */
export function playGlassChime(options?: PlayOptions): void {
  withAudio('system', options, (ctx, output, now) => {
    [739.99, 932.33, 1108.73].forEach((freq, idx) => {
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
      gain.connect(output);
      osc.start(start);
      osc.stop(start + duration);
    });
  });
}

const PLAYERS: Record<SoundKind, (options?: PlayOptions) => void> = {
  messenger: playMessengerChime,
  'messenger-active': playMessengerPop,
  meeting: playMeetingReminder,
  event: playEventCreated,
  deadline: playDeadlineWarning,
  'deadline-urgent': playDeadlineUrgent,
  system: playGlassChime,
};

export function playSound(kind: SoundKind, options?: PlayOptions): void {
  PLAYERS[kind](options);
}

// ---------------------------------------------------------------------------
// Выбор сигнала по уведомлению
// ---------------------------------------------------------------------------

export interface NotificationLike {
  target_type?: string | null;
  verb?: string | null;
}

/**
 * Какой сигнал соответствует уведомлению.
 *
 * Разбираются МАШИННЫЕ поля, которые пишет бэкенд, а не человекочитаемый
 * текст:
 *
 * | `target_type`    | `verb`                          | сигнал            |
 * |------------------|---------------------------------|-------------------|
 * | `chat`           | `chat_message`                  | `messenger`       |
 * | `calendar_event` | `calendar_event_starts_in_{N}m` | `meeting`         |
 * | `calendar_event` | приглашение/изменение события   | `event`           |
 * | `task`           | `task_due_{N}d`, N ≤ 0          | `deadline-urgent` |
 * | `task`           | `task_due_{N}d`, N > 0          | `deadline`        |
 * | `task`           | назначение, делегирование, …    | `system`          |
 *
 * ``task_due`` считается от `(due_date - today).days` (apps/tasks/tasks.py),
 * поэтому ноль — «истекает сегодня», отрицательное — «уже просрочено»: и то и
 * другое срочное.
 *
 * Вынесено отдельно от воспроизведения намеренно — это чистая функция, и
 * таблицу выше можно проверить тестами, не поднимая Web Audio.
 */
export function pickNotificationSound(notification: NotificationLike): SoundKind {
  const target = (notification.target_type || '').trim().toLowerCase();
  const verb = (notification.verb || '').trim().toLowerCase();

  if (target === 'chat') return 'messenger';

  if (target === 'calendar_event') {
    return verb.startsWith('calendar_event_starts_in') ? 'meeting' : 'event';
  }

  if (target === 'task') {
    const due = /^task_due_(-?\d+)d$/.exec(verb);
    if (due) return Number(due[1]) <= 0 ? 'deadline-urgent' : 'deadline';
    return 'system';
  }

  return 'system';
}

/** Проиграть сигнал, соответствующий уведомлению. */
export function playNotificationSound(notification: NotificationLike): void {
  playSound(pickNotificationSound(notification));
}
