/**
 * «К списку» с формы документа — на то место реестра, откуда её открыли:
 * реестр кладёт свой `?page=&q=` в состояние перехода (ссылкой и кликом по
 * строке), форма строит ссылку назад `useRegistryBackHref`. Открыли не из
 * реестра — голый адрес, как из меню.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { BppRegistry } from './BppRegistry';
import { registrySearchOf, useRegistryBackHref } from './registryBack';
import type { RegistryColumn } from './registryTypes';

interface Row { id: string; number: string; status: string }

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));
vi.mock('./registryExport', () => ({ exportRegistry: vi.fn() }));

const BASE = '/bpp/counterparties';
const COLUMNS: RegistryColumn<Row>[] = [
  { key: 'number', title: 'Номер', required: true },
  { key: 'status', title: 'Статус' },
];

function CardStub() {
  const href = useRegistryBackHref(BASE);
  return <a href={href}>К списку</a>;
}

function renderAt(entry: string) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route
            path={BASE}
            element={(
              <BppRegistry<Row>
                registryKey="back-test"
                endpoint="/bpp/v1/counterparties"
                columns={COLUMNS}
                rowHref={(r) => `${BASE}/${r.id}`}
              />
            )}
          />
          <Route path={`${BASE}/:id`} element={<CardStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const backParams = () => {
  const href = screen.getByRole('link', { name: 'К списку' }).getAttribute('href') ?? '';
  const [path, search = ''] = href.split('?');
  return { path, params: new URLSearchParams(search) };
};

describe('registryBack', () => {
  beforeEach(() => {
    window.localStorage.clear();
    get.mockReset();
    get.mockResolvedValue({
      data: { items: [{ id: 'cp-1', number: 'К-01', status: 'active' }], total: 120, page: 2, page_size: 50 },
    });
  });

  it('ссылка на строке несёт место реестра — «К списку» возвращает ?page= и ?q=', async () => {
    const user = userEvent.setup();
    renderAt(`${BASE}?page=2&q=${encodeURIComponent('бетон')}`);

    await user.click(await screen.findByRole('link', { name: 'К-01' }));

    const { path, params } = backParams();
    expect(path).toBe(BASE);
    expect(params.get('page')).toBe('2');
    expect(params.get('q')).toBe('бетон');
  });

  it('клик по строке (не по ссылке) несёт то же место', async () => {
    const user = userEvent.setup();
    renderAt(`${BASE}?page=2&q=${encodeURIComponent('бетон')}`);

    await user.click(await screen.findByRole('cell', { name: 'active' }));

    const { params } = backParams();
    expect(params.get('page')).toBe('2');
    expect(params.get('q')).toBe('бетон');
  });

  it('документ открыт не из реестра — голый адрес реестра', () => {
    renderAt(`${BASE}/cp-1`);
    expect(screen.getByRole('link', { name: 'К списку' })).toHaveAttribute('href', BASE);
  });

  it('чужое состояние перехода не превращается в адрес', () => {
    expect(registrySearchOf(null)).toBe('');
    expect(registrySearchOf({ from: '/x' })).toBe('');
    expect(registrySearchOf({ registrySearch: 42 })).toBe('');
    expect(registrySearchOf({ registrySearch: '//evil.example/?a=1' })).toBe('');
    expect(registrySearchOf({ registrySearch: '?page=3' })).toBe('?page=3');
  });
});
