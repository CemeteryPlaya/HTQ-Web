/**
 * Звуковые уведомления.
 *
 * Проверяется то, что ломается молча: выбор сигнала по уведомлению (ошибка
 * здесь не падает, а просто играет не тот звук — или дефолтный на всё подряд),
 * и три защиты, ради которых сервис вообще существует.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'htq:sound:settings';

/** Осцилляторы, созданные за прогон, — по ним видно, играл ли звук. */
let started: number[] = [];
let ctxState: AudioContextState = 'running';
let resumeCalls = 0;

class FakeAudioContext {
    get state() { return ctxState; }
    currentTime = 0;
    destination = {} as AudioDestinationNode;

    resume() {
        resumeCalls += 1;
        return Promise.resolve();
    }

    createGain() {
        return {
            gain: {
                setValueAtTime: vi.fn(),
                linearRampToValueAtTime: vi.fn(),
                exponentialRampToValueAtTime: vi.fn(),
                setTargetAtTime: vi.fn(),
            },
            connect: vi.fn(),
        };
    }

    createOscillator() {
        return {
            type: 'sine',
            frequency: {
                setValueAtTime: (freq: number) => { started.push(freq); },
                exponentialRampToValueAtTime: vi.fn(),
            },
            connect: vi.fn(),
            start: vi.fn(),
            stop: vi.fn(),
        };
    }
}

/** Модуль держит настройки и окна троттлинга в модульном состоянии —
 *  каждому тесту нужен свежий импорт. */
const loadService = async () => {
    vi.resetModules();
    return import('../soundService');
};

beforeEach(() => {
    started = [];
    ctxState = 'running';
    resumeCalls = 0;
    localStorage.clear();
    vi.stubGlobal('AudioContext', FakeAudioContext);
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('pickNotificationSound', () => {
    it('сообщение в чате — сигнал мессенджера', async () => {
        const { pickNotificationSound } = await loadService();
        expect(pickNotificationSound({ target_type: 'chat', verb: 'chat_message' }))
            .toBe('messenger');
    });

    it('напоминание о созвоне — колокольчик, а не аккорд «событие создано»', async () => {
        const { pickNotificationSound } = await loadService();
        expect(pickNotificationSound({
            target_type: 'calendar_event', verb: 'calendar_event_starts_in_5m',
        })).toBe('meeting');
        expect(pickNotificationSound({
            target_type: 'calendar_event', verb: 'calendar_event_starts_in_0m',
        })).toBe('meeting');
    });

    it('приглашение и правка события — аккорд «событие»', async () => {
        const { pickNotificationSound } = await loadService();
        // Календарь пишет verb человекочитаемым текстом (calendar_service:284),
        // поэтому опознаётся он по target_type, а не по формулировке.
        expect(pickNotificationSound({
            target_type: 'calendar_event', verb: 'пригласил(а) на событие «Планёрка»',
        })).toBe('event');
        expect(pickNotificationSound({
            target_type: 'calendar_event', verb: 'обновил(а) событие «Планёрка»',
        })).toBe('event');
    });

    it('срок сегодня или просрочен — срочный сигнал', async () => {
        const { pickNotificationSound } = await loadService();
        // verb = f"task_due_{(due_date - today).days}d": 0 — сегодня,
        // отрицательное — уже просрочено.
        expect(pickNotificationSound({ target_type: 'task', verb: 'task_due_0d' }))
            .toBe('deadline-urgent');
        expect(pickNotificationSound({ target_type: 'task', verb: 'task_due_-3d' }))
            .toBe('deadline-urgent');
    });

    it('срок завтра — спокойный пульс', async () => {
        const { pickNotificationSound } = await loadService();
        expect(pickNotificationSound({ target_type: 'task', verb: 'task_due_1d' }))
            .toBe('deadline');
    });

    it('назначение и делегирование задачи — системный сигнал', async () => {
        const { pickNotificationSound } = await loadService();
        expect(pickNotificationSound({ target_type: 'task', verb: 'task_assigned:TASK-1' }))
            .toBe('system');
        expect(pickNotificationSound({ target_type: 'task', verb: 'task_delegated:TASK-1' }))
            .toBe('system');
    });

    it('незнакомое и пустое уведомление — системный сигнал, без падения', async () => {
        const { pickNotificationSound } = await loadService();
        expect(pickNotificationSound({ target_type: 'employee', verb: 'whatever' }))
            .toBe('system');
        expect(pickNotificationSound({})).toBe('system');
        expect(pickNotificationSound({ target_type: null, verb: null })).toBe('system');
    });
});

describe('приостановленный контекст', () => {
    it('ничего не планирует, пока пользователь не взаимодействовал со страницей', async () => {
        // Ключевая защита: у suspended-контекста currentTime заморожен, и всё
        // запланированное копится на одной метке, чтобы разом ударить при
        // первом клике.
        ctxState = 'suspended';
        const { playMessengerChime } = await loadService();

        playMessengerChime({ bypassThrottle: true });
        playMessengerChime({ bypassThrottle: true });
        playMessengerChime({ bypassThrottle: true });

        expect(started).toEqual([]);
        expect(resumeCalls).toBeGreaterThan(0); // попытка разбудить всё же делается
    });

    it('играет, как только контекст ожил', async () => {
        const { playMessengerChime } = await loadService();
        playMessengerChime({ bypassThrottle: true });
        expect(started.length).toBeGreaterThan(0);
    });
});

describe('троттлинг', () => {
    it('гасит очередь однотипных сигналов', async () => {
        const { playMessengerChime } = await loadService();

        playMessengerChime();
        const afterFirst = started.length;
        playMessengerChime();
        playMessengerChime();

        expect(started.length).toBe(afterFirst);
    });

    it('чужой вид сигнала не глушится болтовнёй в чате', async () => {
        // Ровно тот случай, ради которого окна разведены: напоминание о
        // созвоне не должно теряться из-за сообщения, пришедшего секундой раньше.
        const { playMessengerChime, playMeetingReminder } = await loadService();

        playMessengerChime();
        const afterMessage = started.length;
        playMeetingReminder();

        expect(started.length).toBeGreaterThan(afterMessage);
    });

    it('предпрослушивание играет всегда и не съедает окно', async () => {
        const { playMessengerChime } = await loadService();

        playMessengerChime({ bypassThrottle: true });
        playMessengerChime({ bypassThrottle: true });
        const afterPreviews = started.length;
        expect(afterPreviews).toBeGreaterThan(0);

        // Настоящее уведомление после предпрослушивания не должно оказаться
        // «уже сыгранным».
        playMessengerChime();
        expect(started.length).toBeGreaterThan(afterPreviews);
    });
});

describe('настройки', () => {
    it('выключенный звук не играет', async () => {
        const { updateSoundSettings, playMessengerChime } = await loadService();
        updateSoundSettings({ enabled: false });

        playMessengerChime({ bypassThrottle: true });

        expect(started).toEqual([]);
    });

    it('нулевая громкость равносильна выключению', async () => {
        const { updateSoundSettings, playMessengerChime } = await loadService();
        updateSoundSettings({ volume: 0 });

        playMessengerChime({ bypassThrottle: true });

        expect(started).toEqual([]);
    });

    it('громкость зажимается в 0…1 и переживает перезагрузку', async () => {
        const { updateSoundSettings } = await loadService();

        expect(updateSoundSettings({ volume: 5 }).volume).toBe(1);
        expect(updateSoundSettings({ volume: -2 }).volume).toBe(0);

        updateSoundSettings({ volume: 0.4 });
        const reloaded = await loadService();
        expect(reloaded.getSoundSettings().volume).toBe(0.4);
    });

    it('битые настройки в хранилище не ломают звук', async () => {
        localStorage.setItem(STORAGE_KEY, '{не json');
        const { getSoundSettings } = await loadService();

        const settings = getSoundSettings();
        expect(settings.enabled).toBe(true);
        expect(settings.volume).toBe(0.75);
        expect(settings.kinds.messenger).toEqual({ enabled: true, volume: 1 });
    });

    it('подписчики узнают об изменении и умеют отписаться', async () => {
        const { subscribeSoundSettings, updateSoundSettings } = await loadService();
        const seen: boolean[] = [];

        const unsubscribe = subscribeSoundSettings((s) => seen.push(s.enabled));
        updateSoundSettings({ enabled: false });
        unsubscribe();
        updateSoundSettings({ enabled: true });

        expect(seen).toEqual([false]);
    });

    it('соседняя вкладка выключила звук — эта тоже замолкает', async () => {
        const { playMessengerChime } = await loadService();

        localStorage.setItem(STORAGE_KEY, JSON.stringify({ enabled: false, volume: 0.75 }));
        window.dispatchEvent(new StorageEvent('storage', {
            key: STORAGE_KEY,
            newValue: JSON.stringify({ enabled: false, volume: 0.75 }),
        }));

        playMessengerChime({ bypassThrottle: true });
        expect(started).toEqual([]);
    });
});


describe('настройки каждого сигнала по отдельности', () => {
    it('выключенный сигнал молчит, остальные звучат', async () => {
        const { updateKindSettings, playMessengerChime, playMeetingReminder } =
            await loadService();

        updateKindSettings('messenger', { enabled: false });

        playMessengerChime({ bypassThrottle: true });
        expect(started).toEqual([]);

        playMeetingReminder({ bypassThrottle: true });
        expect(started.length).toBeGreaterThan(0);
    });

    it('нулевая персональная громкость равносильна выключению', async () => {
        const { updateKindSettings, playMessengerChime } = await loadService();

        updateKindSettings('messenger', { volume: 0 });
        playMessengerChime({ bypassThrottle: true });

        expect(started).toEqual([]);
    });

    it('персональная громкость — множитель к общей', async () => {
        const { updateSoundSettings, updateKindSettings, effectiveVolume } =
            await loadService();

        updateSoundSettings({ volume: 0.8 });
        updateKindSettings('meeting', { volume: 0.5 });

        expect(effectiveVolume('meeting')).toBeCloseTo(0.4);
        // Другие сигналы остаются на общей громкости.
        expect(effectiveVolume('messenger')).toBeCloseTo(0.8);
    });

    it('общий выключатель глушит всё, не стирая персональных настроек', async () => {
        const { updateSoundSettings, updateKindSettings, effectiveVolume, getSoundSettings } =
            await loadService();

        updateKindSettings('deadline', { volume: 0.3 });
        updateSoundSettings({ enabled: false });

        expect(effectiveVolume('deadline')).toBe(0);
        // Значение сохранено: вернув общий звук, пользователь получит свой баланс.
        expect(getSoundSettings().kinds.deadline.volume).toBe(0.3);
    });

    it('громкость сигнала зажимается в 0…1', async () => {
        const { updateKindSettings } = await loadService();

        expect(updateKindSettings('system', { volume: 9 }).kinds.system.volume).toBe(1);
        expect(updateKindSettings('system', { volume: -4 }).kinds.system.volume).toBe(0);
    });

    it('правка одного сигнала не трогает соседние', async () => {
        const { updateKindSettings, getSoundSettings } = await loadService();

        updateKindSettings('event', { volume: 0.2, enabled: false });
        const settings = getSoundSettings();

        expect(settings.kinds.event).toEqual({ enabled: false, volume: 0.2 });
        expect(settings.kinds.messenger).toEqual({ enabled: true, volume: 1 });
    });

    it('настройки сигналов переживают перезагрузку', async () => {
        const { updateKindSettings } = await loadService();
        updateKindSettings('deadline-urgent', { volume: 0.45, enabled: false });

        const reloaded = await loadService();
        expect(reloaded.getSoundSettings().kinds['deadline-urgent'])
            .toEqual({ enabled: false, volume: 0.45 });
    });

    it('настройки, записанные до появления персональных громкостей, читаются', async () => {
        // В хранилище у действующих пользователей лежит ровно такая форма.
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ enabled: true, volume: 0.5 }));
        const { getSoundSettings, effectiveVolume } = await loadService();

        expect(getSoundSettings().volume).toBe(0.5);
        expect(getSoundSettings().kinds.messenger).toEqual({ enabled: true, volume: 1 });
        expect(effectiveVolume('messenger')).toBeCloseTo(0.5);
    });

    it('частичная карта в хранилище добивается умолчаниями', async () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            enabled: true, volume: 0.75, kinds: { meeting: { volume: 0.1 } },
        }));
        const { getSoundSettings } = await loadService();

        const settings = getSoundSettings();
        expect(settings.kinds.meeting).toEqual({ enabled: true, volume: 0.1 });
        expect(settings.kinds.system).toEqual({ enabled: true, volume: 1 });
    });

    it('getSoundSettings отдаёт копию, а не живую ссылку', async () => {
        const { getSoundSettings, effectiveVolume } = await loadService();

        const snapshot = getSoundSettings();
        snapshot.kinds.messenger.volume = 0;

        expect(effectiveVolume('messenger')).toBeGreaterThan(0);
    });
});
