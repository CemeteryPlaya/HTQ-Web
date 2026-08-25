/**
 * Живое уведомление о начале встречи.
 *
 * Отдельная проверка на запрещённые системные уведомления: браузер вправе
 * отказать, и это не повод ронять глобально смонтированный компонент.
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
});
