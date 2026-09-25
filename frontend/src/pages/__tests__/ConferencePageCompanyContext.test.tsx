/**
 * Комната на голом домене (финальное ревью блока L, I-1).
 *
 * Ссылка-приглашение строится от голого домена, и сотрудник попадает в
 * `/room/<id>` без поддомена компании. Там гейт модуля отвечает 403 на всё
 * под ним, поэтому комната не зовёт ни сводку и историю встреч
 * (`conference/v1/overview`, `sessions`), ни ручки приглашений (кнопка
 * «Пригласить по ссылке» не показывается). Конфиг звонка зовётся всегда: он
 * гейта не несёт (`open` в реестре самообслуживания).
 */
import React from 'react';
import { screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

const fetchOverview = vi.fn();
const listSessions = vi.fn();
vi.mock('@/api/conference', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/conference')>()),
  fetchOverview: () => fetchOverview(),
  listSessions: (params: unknown) => listSessions(params),
}));

const apiGet = vi.fn();
vi.mock('@/api/client', () => ({
  default: { get: (url: string) => apiGet(url), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock('@/lib/auth/profileStorage', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/profileStorage')>()),
  getAccessToken: () => 'employee-token',
}));

const companyFromHost = vi.fn<(host: string) => string | null>();
vi.mock('@/lib/auth/companySwitch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/companySwitch')>()),
  companyFromHost: (host: string) => companyFromHost(host),
}));

// Шапка и кнопка «назад» тянут свои запросы и контексты — к предмету теста
// отношения не имеют.
vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/BackToProfile', () => ({ BackToProfile: () => null }));

import ConferencePage from '../ConferencePage';

const renderRoom = () =>
  renderWithProviders(
    <Routes>
      <Route path="/room/:roomId" element={<ConferencePage />} />
    </Routes>,
    { route: '/room/r-1' },
  );

describe('ConferencePage — контекст компании', () => {
  beforeEach(() => {
    fetchOverview.mockReset().mockResolvedValue({ today: [], active: [] });
    listSessions.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, limit: 5 });
    apiGet.mockReset().mockResolvedValue({ data: {} });
    companyFromHost.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('на голом домене не зовёт ручки под гейтом, но берёт конфиг звонка', async () => {
    companyFromHost.mockReturnValue(null);
    renderRoom();

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('cms/v1/conference/config'));
    expect(fetchOverview).not.toHaveBeenCalled();
    expect(listSessions).not.toHaveBeenCalled();
    expect(screen.queryByText(/Пригласить по ссылке/)).toBeNull();
  });

  it('на хосте компании зовёт сводку и историю встреч', async () => {
    companyFromHost.mockReturnValue('htq');
    renderRoom();

    await waitFor(() => expect(fetchOverview).toHaveBeenCalled());
    expect(listSessions).toHaveBeenCalled();
    expect(apiGet).toHaveBeenCalledWith('cms/v1/conference/config');
    // Та же кнопка, которой нет на голом домене, — иначе проверка выше
    // проходила бы и там, где кнопки нет вовсе.
    expect(await screen.findByText(/Пригласить по ссылке/)).toBeInTheDocument();
  });
});
