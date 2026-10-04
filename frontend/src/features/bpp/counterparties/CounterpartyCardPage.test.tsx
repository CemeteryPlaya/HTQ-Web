/**
 * Карточка контрагента (ТЗ §18; BR-060; задача 9 плана этапа 2 A):
 * - блокировка требует причину не короче 10 символов, уходит с `version`
 *   и `Idempotency-Key`;
 * - у роли без права блокировки (СН, ПМ) кнопок блокировки, архива и метки
 *   нет — даже если сервер ошибочно назвал их в `allowed_actions`;
 * - заблокированный — плашка с причиной;
 * - «К списку» — на то место реестра, откуда открыли карточку;
 * - «История изменений» получает подписи полей карточки.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { CounterpartyCardPage } from './CounterpartyCardPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch: vi.fn() } }));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('../core/HistoryTab', () => ({
  HistoryTab: ({ fieldLabels }: { fieldLabels?: Record<string, string> }) => (
    <div>
      История: {fieldLabels?.reg_number} / {fieldLabels?.short_name} / {fieldLabels?.iban}
    </div>
  ),
}));

function permissionsWith(depth: Record<string, DepthFlag[]>): Permissions {
  return {
    company: 'hi-tech-qazaqstan',
    level: () => 'write',
    atLeast: () => true,
    scope: () => null,
    depth: (node) => depth[node] ?? [],
    can: (node, flag) => (depth[node] ?? []).includes(flag),
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    companyArchived: false,
    isLoading: false,
    isError: false,
    refetch: () => {},
  };
}
const FD = { 'bpp.counterparties': ['view', 'create', 'edit'], 'bpp.counterparties.block': ['edit'] } as Record<string, DepthFlag[]>;
const SN = { 'bpp.counterparties': ['view', 'create'], 'bpp.counterparties.block': [] } as Record<string, DepthFlag[]>;
const permissions = vi.fn(() => permissionsWith(FD));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const card = (over: Record<string, unknown> = {}) => ({
  id: ID, name: 'Товарищество «Альфа»', short_name: 'ТОО «Альфа»', kind: 'legal',
  country_code: 'KZ', reg_number: '100000000001', is_vat_payer: false,
  vat_cert_series: '', vat_cert_number: '', legal_address: '', contact_person: '',
  phone: '', email: '', status: 'active', block_reason: '', blocked_at: null,
  blocked_by: null, successful_documents: 1, verified_override: null,
  verified_threshold: 3, is_verified: false, ext_1c_ref: '', version: 4,
  created_at: '2026-09-20T05:00:00Z', created_by: 1, updated_at: '2026-09-20T05:00:00Z',
  updated_by: 1, bank_accounts: [],
  allowed_actions: ['edit', 'add_account', 'block', 'archive', 'verified'],
  ...over,
});

function renderCard(state?: unknown) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[{ pathname: `/bpp/counterparties/${ID}`, state }]}>
        <Routes>
          <Route path="/bpp/counterparties/:id" element={<CounterpartyCardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CounterpartyCardPage', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    permissions.mockReturnValue(permissionsWith(FD));
  });

  it('блокировка: причина короче 10 символов не отправляется, с 10 — уходит с version', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: card() });
    post.mockResolvedValue({
      data: card({ status: 'blocked', block_reason: 'Срыв сроков', blocked_at: '2026-09-27T05:00:00Z', version: 5, allowed_actions: ['unblock', 'archive', 'verified'] }),
    });
    renderCard();

    await user.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    const dialog = await screen.findByRole('dialog');
    const confirm = () => screen.getAllByRole('button', { name: 'Заблокировать' }).at(-1)!;

    await user.type(screen.getByLabelText('Комментарий'), '123456789');
    expect(confirm()).toBeDisabled();
    expect(dialog).toHaveTextContent('Минимум 10 символов, сейчас 9');

    await user.clear(screen.getByLabelText('Комментарий'));
    await user.type(screen.getByLabelText('Комментарий'), 'Срыв сроков');
    expect(confirm()).toBeEnabled();
    await user.click(confirm());

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe(`bpp/v1/counterparties/${ID}/block`);
    expect(body).toEqual({ version: 4, reason: 'Срыв сроков' });
    expect(config.headers['Idempotency-Key']).toEqual(expect.any(String));

    // Карточка обновилась ответом сервера: плашка причины и «Разблокировать».
    expect(await screen.findByText(/Заблокирован 27\.09\.2026 10:00: Срыв сроков/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Разблокировать' })).toBeInTheDocument();
  });

  it('у роли без права блокировки (СН) — ни блокировки, ни архива, ни метки', async () => {
    permissions.mockReturnValue(permissionsWith(SN));
    // Сервер для СН этих действий не отдаёт; даже если бы отдал — фронт их прячет.
    get.mockResolvedValue({ data: card() });
    renderCard();

    expect(await screen.findByRole('heading', { name: 'ТОО «Альфа»' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Заблокировать' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'В архив' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Метка «Проверенный»' })).not.toBeInTheDocument();
    // Правки у СН тоже нет (`edit` — ФД и БУХ).
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument();
  });

  it('ФД видит блокировку, архив, метку и правку', async () => {
    get.mockResolvedValue({ data: card() });
    renderCard();
    expect(await screen.findByRole('button', { name: 'Заблокировать' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'В архив' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Метка «Проверенный»' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Изменить' })).toBeInTheDocument();
  });

  it('чужой или несуществующий — «Контрагент не найден»', async () => {
    get.mockRejectedValue({ response: { status: 404, data: { detail: 'Контрагент не найден.' } } });
    renderCard();
    expect(await screen.findByText('Контрагент не найден')).toBeInTheDocument();
  });

  it('«К списку» возвращает на страницу и поиск реестра, откуда открыли', async () => {
    get.mockResolvedValue({ data: card() });
    renderCard({ registrySearch: '?page=3&q=%D0%B0%D0%BB%D1%8C%D1%84%D0%B0' });
    expect(await screen.findByRole('link', { name: 'К списку контрагентов' }))
      .toHaveAttribute('href', '/bpp/counterparties?page=3&q=%D0%B0%D0%BB%D1%8C%D1%84%D0%B0');
  });

  it('открыт не из реестра — «К списку» на голый адрес', async () => {
    get.mockResolvedValue({ data: card() });
    renderCard();
    expect(await screen.findByRole('link', { name: 'К списку контрагентов' }))
      .toHaveAttribute('href', '/bpp/counterparties');
  });

  it('история изменений получает подписи полей карточки и счетов', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: card() });
    renderCard();

    await user.click(await screen.findByRole('tab', { name: 'История изменений' }));
    expect(await screen.findByText('История: БИН/ИИН / Краткое наименование / IBAN'))
      .toBeInTheDocument();
  });
});
