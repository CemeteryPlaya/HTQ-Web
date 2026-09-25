/**
 * Экран выбора компании на голом домене (блок I.2, S4).
 *
 * Компания определяется поддоменом, а вход живёт на голом домене, поэтому
 * после входа человека надо увести в его компанию: с одной — сразу (и туда,
 * куда он шёл по глубокой ссылке), с несколькими — по выбору, без компаний —
 * сказать это прямо, а не показывать пустой список.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';
import type { MyCompany } from '@/types/companies';

import CompanyPicker from '../CompanyPicker';

const myCompanies = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: { myCompanies: () => myCompanies() },
}));

const clearAuthStorage = vi.fn();
vi.mock('@/lib/auth/profileStorage', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth/profileStorage')>()),
  clearAuthStorage: () => clearAuthStorage(),
}));

const mockMyCompanies = (companies: MyCompany[]) => {
  myCompanies.mockResolvedValue({ data: companies });
};

const HTQ: MyCompany = { slug: 'hi-tech-qazaqstan', subdomain: 'htq', name: 'HTQ', kind: 'construction', is_default: true, is_current: false };
const HTS: MyCompany = { slug: 'hi-tech-systems', subdomain: 'hts', name: 'HTS', kind: 'it', is_default: false, is_current: false };
const KEG_ARCHIVED: MyCompany = { slug: 'keg', subdomain: 'keg', name: 'KEG', kind: 'service', is_default: false, is_current: false, is_archived: true };

const wrapperAt = (entry: string | { pathname: string; state?: unknown }) => {
  const queryClient = createTestQueryClient();
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/companies/choose" element={children} />
          <Route path="/login" element={<div>страница входа</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

// Каждый тест — свой QueryClient: общий кеш `['companies', 'me']` протащил бы
// ответ одного теста в следующий.
let wrapper: ReturnType<typeof wrapperAt>;

const stubBareHost = () => {
  const assign = vi.fn();
  vi.stubGlobal('location', { host: 'htq.group', pathname: '/companies/choose', search: '', hash: '', protocol: 'https:', assign });
  return assign;
};

describe('CompanyPicker', () => {
  beforeEach(() => {
    wrapper = wrapperAt('/companies/choose');
    myCompanies.mockReset();
    clearAuthStorage.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // Без `state.from` (прямой заход на экран выбора) цель — стартовая страница
  // вошедшего, та же, что у Login после входа, а не публичный лендинг `/`.
  it('с одной компанией сразу уводит на её поддомен, на стартовую страницу', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ]);

    render(<CompanyPicker />, { wrapper });

    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://htq.htq.group/myprofile'));
  });

  it('с одной компанией возвращает туда, куда человек шёл по глубокой ссылке', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ]);

    render(<CompanyPicker />, {
      wrapper: wrapperAt({
        pathname: '/companies/choose',
        state: { from: { pathname: '/hr/employees', search: '?tab=cards', hash: '#top' } },
      }),
    });

    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://htq.htq.group/hr/employees?tab=cards#top'));
  });

  it('с несколькими компаниями показывает список и не уводит сам', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ, HTS]);

    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('HTQ')).toBeInTheDocument();
    expect(screen.getByText('HTS')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('по выбору уводит на псевдоним выбранной компании', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ, HTS]);

    render(<CompanyPicker />, { wrapper });

    await userEvent.click(await screen.findByRole('button', { name: /HTS/ }));

    expect(assign).toHaveBeenCalledWith('https://hts.htq.group/myprofile');
  });

  it('единственную архивную компанию не открывает сам, а показывает с меткой', async () => {
    const assign = stubBareHost();
    mockMyCompanies([KEG_ARCHIVED]);

    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('KEG')).toBeInTheDocument();
    expect(screen.getByText('архив')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('с действующей и архивной — список, без автоперехода', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ, KEG_ARCHIVED]);

    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('HTQ')).toBeInTheDocument();
    expect(screen.getByText('KEG')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('без компаний говорит об этом прямо', async () => {
    mockMyCompanies([]);
    render(<CompanyPicker />, { wrapper });
    expect(await screen.findByText(/нет доступа ни к одной компании/i)).toBeInTheDocument();
  });

  it('без компаний даёт выйти тем же путём, что и остальное приложение', async () => {
    mockMyCompanies([]);
    render(<CompanyPicker />, { wrapper });

    await userEvent.click(await screen.findByRole('button', { name: 'Выйти' }));

    expect(clearAuthStorage).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('страница входа')).toBeInTheDocument();
  });

  it('не выдаёт неудачный запрос за «компаний нет»', async () => {
    myCompanies.mockRejectedValue(new Error('network'));
    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('Не удалось получить список компаний.')).toBeInTheDocument();
    expect(screen.queryByText(/нет доступа ни к одной компании/i)).not.toBeInTheDocument();
  });
});
