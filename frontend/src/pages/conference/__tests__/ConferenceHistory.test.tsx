/**
 * Вкладки экрана «Мои видеоконференции».
 *
 * Проверяем ровно то, что нельзя увидеть по типам: что «Сегодня» и «Идут
 * сейчас» берут данные из /overview, а не из истории, и что пустая вкладка
 * говорит человеку, что она пуста, а не показывает вечный скелет.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ConferenceHistory from '../ConferenceHistory';

vi.mock('@/api/conference', () => ({
  listSessions: vi.fn(async () => ({
    items: [], total: 0, page: 1, pages: 1, limit: 25,
    recorded_total: 0, active_total: 0,
  })),
  fetchOverview: vi.fn(async () => ({
    server_time: '2026-08-25T09:00:00Z',
    today: [{
      event_id: 1, room_id: 'room-1', title: 'Планёрка',
      start_at: '2026-08-25T10:00:00Z', end_at: '2026-08-25T11:00:00Z',
      status: 'live', session_id: 5, is_organizer: true, participant_count: 3,
    }],
    active: [],
  })),
}));

const renderPage = () => render(
  <QueryClientProvider client={new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })}>
    <MemoryRouter>
      <ConferenceHistory />
    </MemoryRouter>
  </QueryClientProvider>,
);

describe('ConferenceHistory', () => {
  beforeEach(() => vi.clearAllMocks());

  it('показывает сегодняшнюю встречу на первой вкладке', async () => {
    renderPage();

    expect(await screen.findByText('Планёрка')).toBeInTheDocument();
  });

  it('на вкладке «Идут сейчас» пусто, когда активных нет', async () => {
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: /Идут сейчас/i }));

    await waitFor(() => {
      expect(screen.getByText(/Сейчас никто не разговаривает/i)).toBeInTheDocument();
    });
  });
});
