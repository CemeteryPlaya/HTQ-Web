/**
 * Сквозная проверка того, ради чего всё затевалось: карточка уведомления
 * действительно появляется, и появляется В ПРАВОМ НИЖНЕМ УГЛУ.
 *
 * Здесь sonner НЕ подменён — работают настоящий `<Toaster/>` и настоящий
 * `toast()`. Тест ловит целый класс поломок, которые проверка с моком пропустит:
 * приёмник не сообщил о себе, тост ушёл раньше приёмника, угол переехал.
 *
 * Приёмник монтируется ПОСЛЕ источника — как в жизни: в `App.tsx` он приходит
 * отдельным чанком по таймеру, а список уведомлений успевает приехать раньше.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NotificationToasts } from '@/components/NotificationToasts';
import { Toaster } from '@/components/ui/sonner';
import type { Notification } from '@/types/tasks';

const fetchNotifications = vi.hoisted(() => vi.fn());

vi.mock('@/api/tasks', () => ({
    fetchNotifications,
    markNotificationRead: vi.fn(),
    notificationSourceLabel: () => 'Задача',
    formatNotificationText: (n: Notification) => n.verb,
    notificationTargetUrl: () => '/tasks/7',
}));

// Web Audio в jsdom нет, а звук здесь не проверяется.
vi.mock('@/lib/sound/soundService', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/lib/sound/soundService')>()),
    playNotificationSound: vi.fn(),
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

beforeEach(() => {
    localStorage.clear();
    fetchNotifications.mockResolvedValue([NOTIFICATION]);
});

describe('карточка уведомления', () => {
    it('появляется в правом нижнем углу, даже если приёмник смонтирован позже источника', async () => {
        const queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        });
        const wrap = (children: React.ReactNode) => (
            <QueryClientProvider client={queryClient}>
                <MemoryRouter>{children}</MemoryRouter>
            </QueryClientProvider>
        );

        // Сначала только источник — показывать уведомление пока негде.
        const { rerender } = render(wrap(<NotificationToasts />));
        await waitFor(() =>
            expect(queryClient.getQueryData(['notifications'])).toHaveLength(1),
        );
        expect(document.querySelector('[data-sonner-toast]')).toBeNull();

        // Приёмник появился — карточка обязана всплыть сама.
        rerender(
            wrap(
                <>
                    <Toaster />
                    <NotificationToasts />
                </>,
            ),
        );

        expect(await screen.findByText(/Иванов Иван/)).toBeInTheDocument();

        const toaster = document.querySelector('[data-sonner-toaster]');
        expect(toaster).not.toBeNull();
        expect(toaster).toHaveAttribute('data-y-position', 'bottom');
        expect(toaster).toHaveAttribute('data-x-position', 'right');
    });
});
