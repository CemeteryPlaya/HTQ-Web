/**
 * Живое уведомление о начале встречи.
 *
 * Отдельная проверка на системные уведомления: конструктор `Notification`
 * подставлен так, что бросает исключение уже ВНУТРИ асинхронной ветки
 * (после `requestPermission()`) — именно там, где общий `try/catch`
 * снаружи эффекта его не поймает. Компонент должен это пережить.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ConferenceNotifier } from '../ConferenceNotifier';

const handlers: Record<string, (payload: unknown) => void> = {};

vi.mock('@/features/messenger/api/socket', () => ({
  getMessengerSocket: () => ({
    on: (event: string, handler: (payload: unknown) => void) => {
      handlers[event] = handler;
    },
    off: vi.fn(),
  }),
}));

const toastSpy = vi.fn();
vi.mock('sonner', () => ({ toast: (...args: unknown[]) => toastSpy(...args) }));

vi.mock('@/api/calendar', () => ({ fetchCalendarTimeline: vi.fn(async () => ({ events: [] })) }));
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { id: 1 } }),
}));

const renderNotifier = () => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter><ConferenceNotifier /></MemoryRouter>
  </QueryClientProvider>,
);

describe('ConferenceNotifier', () => {
  beforeEach(() => { toastSpy.mockClear(); });

  it('показывает тост на conference_started', async () => {
    renderNotifier();

    handlers.notification?.({
      type: 'conference_started', session_id: 5, room_id: 'room-1',
      title: 'Планёрка', join_url: '/room/room-1',
      started_at: '2026-08-25T10:00:00Z',
    });

    await waitFor(() => expect(toastSpy).toHaveBeenCalled());
  });

  it('чужие уведомления игнорирует', async () => {
    renderNotifier();

    handlers.notification?.({ type: 'task_assigned', task_id: 3 });

    expect(toastSpy).not.toHaveBeenCalled();
  });

  it('переживает падение Notification в асинхронной ветке (первый запрос разрешения)', async () => {
    const originalNotification = globalThis.Notification;
    const notificationCtor = vi.fn(() => {
      throw new Error('браузер отказал в создании системного уведомления');
    });
    const requestPermission = vi.fn(async () => 'granted' as NotificationPermission);

    class ThrowingNotification {
      static permission: NotificationPermission = 'default';
      static requestPermission = requestPermission;
      constructor(...args: unknown[]) { notificationCtor(...args); }
    }
    // @ts-expect-error — подменяем глобальный конструктор упрощённым стабом только для теста.
    globalThis.Notification = ThrowingNotification;

    try {
      renderNotifier();

      handlers.notification?.({
        type: 'conference_started', session_id: 6, room_id: 'room-2',
        title: 'Летучка', join_url: '/room/room-2',
        started_at: '2026-08-25T11:00:00Z',
      });

      // Тост — до системного уведомления, значит появится сразу.
      await waitFor(() => expect(toastSpy).toHaveBeenCalled());
      // requestPermission() резолвится 'granted', после чего show() вызывает
      // конструктор Notification уже в .then() — вне синхронного try/catch
      // обработчика. Если бы бросок не был пойман отдельным try/catch внутри
      // show(), это ушло бы необработанным отклонением промиса, и тест
      // упал бы сам (vitest репортит unhandled rejection как ошибку).
      await waitFor(() => expect(requestPermission).toHaveBeenCalled());
      await waitFor(() => expect(notificationCtor).toHaveBeenCalled());
    } finally {
      globalThis.Notification = originalNotification;
    }
  });
});
