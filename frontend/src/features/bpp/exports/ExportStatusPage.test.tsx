/**
 * Экран фоновой выгрузки (задача 6/8): три состояния — «готовится»,
 * «готово» (кнопка «Скачать», срок ссылки) и «ошибка» (текст причины);
 * несуществующая/чужая выгрузка — «не найдена».
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { ExportStatusPage } from './ExportStatusPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

// Подделываем только часы: таймеры react-query и waitFor остаются настоящими.
const NOW = new Date('2026-09-27T20:30:00Z');
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  get.mockReset();
});
afterEach(() => { vi.useRealTimers(); });

const doneJob = (over: Record<string, unknown> = {}) => ({
  id: 'job-1', name: 'Реестр заявок', status: 'done', row_count: 12_345,
  error: null, created_at: '2026-09-27T20:00:00Z', finished_at: '2026-09-27T20:05:00Z',
  url: 'https://storage.example/export.xlsx?sig=abc', expires_at: '2026-09-27T21:00:00Z',
  ...over,
});

function renderPage(id = 'job-1') {
  const queryClient = createTestQueryClient();
  // Как в приложении: по умолчанию данные устаревают сразу и перечитываются
  // при фокусе — проверяем, что готовую выгрузку это не задевает.
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: 0, refetchOnWindowFocus: true },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/bpp/exports/${id}`]}>
        <Routes>
          <Route path="/bpp/exports/:id" element={<ExportStatusPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExportStatusPage — готовая выгрузка не перечитывается сама', () => {
  it('возврат фокуса на вкладку не выдаёт новую ссылку (не пишет скачивание в журнал)', async () => {
    get.mockResolvedValue({ data: doneJob() });
    renderPage();
    await screen.findByRole('link', { name: /Скачать/ });
    expect(get).toHaveBeenCalledTimes(1);

    act(() => {
      window.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('focus'));
    });
    await new Promise((resolve) => { setTimeout(resolve, 50); });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('истёкшая ссылка — «Ссылка истекла» и кнопка «Получить новую ссылку»', async () => {
    get.mockResolvedValueOnce({ data: doneJob({ expires_at: '2026-09-27T20:00:00Z' }) });
    get.mockResolvedValueOnce({
      data: doneJob({
        url: 'https://storage.example/export.xlsx?sig=new', expires_at: '2026-09-27T21:30:00Z',
      }),
    });
    renderPage();

    expect(await screen.findByText('Ссылка истекла.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Скачать/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Получить новую ссылку/ }));
    const link = await screen.findByRole('link', { name: /Скачать/ });
    expect(link).toHaveAttribute('href', 'https://storage.example/export.xlsx?sig=new');
    expect(get).toHaveBeenCalledTimes(2);
  });
});

describe('ExportStatusPage', () => {
  it('готовится — сообщение об опросе, без кнопки «Скачать»', async () => {
    get.mockResolvedValue({
      data: {
        id: 'job-1', name: 'Реестр заявок', status: 'queued', row_count: 12_345,
        error: null, created_at: '2026-09-27T20:00:00Z', finished_at: null,
      },
    });
    renderPage();

    expect(await screen.findByText('Реестр заявок')).toBeInTheDocument();
    expect(screen.getByText('Готовится')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('собирается в фоне');
    expect(screen.queryByRole('link', { name: /Скачать/ })).not.toBeInTheDocument();
  });

  it('готово — кнопка «Скачать» ведёт на ссылку, показан срок действия', async () => {
    get.mockResolvedValue({
      data: {
        id: 'job-1', name: 'Реестр заявок', status: 'done', row_count: 12_345,
        error: null, created_at: '2026-09-27T20:00:00Z', finished_at: '2026-09-27T20:05:00Z',
        url: 'https://storage.example/export.xlsx?sig=abc', expires_at: '2026-09-27T21:00:00Z',
      },
    });
    renderPage();

    const link = await screen.findByRole('link', { name: /Скачать/ });
    expect(link).toHaveAttribute('href', 'https://storage.example/export.xlsx?sig=abc');
    expect(screen.getByText(/Ссылка действует до/)).toBeInTheDocument();
  });

  it('ошибка — текст причины сервера', async () => {
    get.mockResolvedValue({
      data: {
        id: 'job-1', name: 'Реестр заявок', status: 'error', row_count: 12_345,
        error: 'Очередь фоновых задач недоступна. Повторите экспорт через несколько минут.',
        created_at: '2026-09-27T20:00:00Z', finished_at: '2026-09-27T20:05:00Z',
      },
    });
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Очередь фоновых задач недоступна');
  });

  it('выгрузка не найдена — 404 объясняется отдельно от прочих ошибок', async () => {
    get.mockRejectedValue({ response: { status: 404 } });
    renderPage('unknown');

    await waitFor(() =>
      expect(screen.getByText(/Выгрузка не найдена/)).toBeInTheDocument());
  });

  it('прочая ошибка загрузки — общее сообщение', async () => {
    get.mockRejectedValue({ response: { status: 500 } });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Не удалось загрузить состояние выгрузки/)).toBeInTheDocument());
  });
});
