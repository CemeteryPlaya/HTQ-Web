/**
 * Уведомление должно быть ВИДНО, а не только слышно.
 *
 * Оба теста ниже про один и тот же разрыв: звук платформа играла, а карточки
 * человек не видел.
 *
 * 1. Пока `<Toaster/>` не смонтирован, sonner выбрасывает тост молча (он не
 *    копит отправленное, а рассылает подписчикам «сейчас»). Список уведомлений
 *    же приезжал раньше приёмника — звук отрабатывал, id уходил в «уже
 *    показанные», карточка не появлялась никогда.
 * 2. Когда человек ушёл в другое окно, карточка в углу СТРАНИЦЫ до него не
 *    доходит: там нужно уведомление операционной системы.
 */
import { act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NotificationToasts } from '@/components/NotificationToasts';
import { setToastHostMounted } from '@/lib/notifications/toastHost';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { Notification } from '@/types/tasks';

const fetchNotifications = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() =>
    Object.assign(vi.fn(), { custom: vi.fn(), dismiss: vi.fn() }),
);
const playNotificationSound = vi.hoisted(() => vi.fn());

vi.mock('@/api/tasks', () => ({
    fetchNotifications,
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
    notificationSourceLabel: () => 'Задача',
    formatNotificationText: (n: Notification) => n.verb,
    notificationTargetUrl: () => '/tasks/7',
}));

vi.mock('sonner', () => ({ toast: toastMock, Toaster: () => null }));

// Настоящий модуль звука, подменён только сам проигрыватель.
vi.mock('@/lib/sound/soundService', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/lib/sound/soundService')>()),
    playNotificationSound,
}));

const NOTIFICATION = {
    id: 7,
    recipient: 1,
    actor: 2,
    actor_name: 'Иванов Иван',
    verb: 'назначил(а) вас исполнителем',
    task: 7,
    task_key: 'HTQ-7',
    target_type: 'task',
    target_id: 7,
    is_read: false,
    read_at: null,
    created_at: '2026-08-28T09:00:00Z',
} as unknown as Notification;

/** Смонтировать показ уведомлений и дождаться, пока список приехал. */
const mountAndLoad = async () => {
    const { queryClient } = renderWithProviders(<NotificationToasts />);
    await waitFor(() =>
        expect(queryClient.getQueryData(['notifications'])).toHaveLength(1),
    );
    return queryClient;
};

/** Смотрит ли человек на страницу. Оба признака задаются явно: в jsdom
 *  `hasFocus()` возвращает false (окна-то нет), и «передний план» пришлось бы
 *  считать фоном. */
const setPageHidden = (hidden: boolean) => {
    Object.defineProperty(document, 'hidden', {
        configurable: true,
        get: () => hidden,
    });
    Object.defineProperty(document, 'hasFocus', {
        configurable: true,
        value: () => !hidden,
    });
};

const stubDesktopNotifications = (permission: NotificationPermission) => {
    const ctor = vi.fn();
    Object.assign(ctor, { permission, requestPermission: vi.fn() });
    vi.stubGlobal('Notification', ctor);
    return ctor;
};

beforeEach(() => {
    localStorage.clear();
    setToastHostMounted(false);
    setPageHidden(false);
    fetchNotifications.mockResolvedValue([NOTIFICATION]);
});

afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    setToastHostMounted(false);
});

describe('NotificationToasts', () => {
    it('не сжигает уведомление, пока приёмник тостов не смонтирован', async () => {
        await mountAndLoad();

        // Список уже пришёл, но показывать карточку негде — значит и звука
        // быть не должно: иначе выйдет ровно то, на что жаловались.
        expect(toastMock).not.toHaveBeenCalled();
        expect(playNotificationSound).not.toHaveBeenCalled();

        act(() => setToastHostMounted(true));

        await waitFor(() => expect(toastMock).toHaveBeenCalledTimes(1));
        expect(playNotificationSound).toHaveBeenCalledTimes(1);
        expect(toastMock.mock.calls[0][0]).toContain('Иванов Иван');
    });

    it('в фоне дублирует карточку уведомлением операционной системы', async () => {
        const ctor = stubDesktopNotifications('granted');
        setPageHidden(true);

        await mountAndLoad();
        act(() => setToastHostMounted(true));

        await waitFor(() => expect(ctor).toHaveBeenCalledTimes(1));
        const [title, options] = ctor.mock.calls[0] as [string, NotificationOptions];
        expect(title).toBe('Иванов Иван');
        expect(options.body).toBe(NOTIFICATION.verb);
        // Тег привязан к уведомлению — повтор того же не размножится в трее.
        expect(options.tag).toBe('htq-notification-7');
    });

    it('на переднем плане обходится карточкой, не трогая трей', async () => {
        const ctor = stubDesktopNotifications('granted');

        await mountAndLoad();
        act(() => setToastHostMounted(true));

        await waitFor(() => expect(toastMock).toHaveBeenCalledTimes(1));
        expect(ctor).not.toHaveBeenCalled();
    });
});
