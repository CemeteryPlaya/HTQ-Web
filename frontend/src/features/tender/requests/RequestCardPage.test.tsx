/**
 * Карточка заявки на тендер (T1.4, план §3.3–3.5): части «ЗЗ-… — статус» со
 * ссылкой на заявку БЗО, кнопки по `allowed_actions`, отправка с `version`,
 * отказ 409 E-CON-01 — понятное сообщение, «Исключить часть» — только у
 * отклонённой части, отмена — с комментарием от 10 символов.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { TenderRequestCard } from './api';
import { RequestCardPage } from './RequestCardPage';
import { BPP_REQUEST_ID, REQUEST_ID, requestCard, serveReference } from './testData';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch: vi.fn(), delete: del } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const nodes = vi.hoisted(() => ({ value: {} as Record<string, string[]> }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, flag: string) => (nodes.value[node] ?? []).includes(flag),
    isLoading: false,
  }),
}));

function serve(request: TenderRequestCard) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`tender/v1/requests/${REQUEST_ID}`)) return Promise.resolve({ data: request });
    const reference = serveReference(url);
    return Promise.resolve(reference ?? { data: [] });
  });
}

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/tender/requests/${REQUEST_ID}`]}>
        <Routes>
          <Route path="/tender/requests/:id" element={<RequestCardPage />} />
          <Route path="/tender/requests" element={<div>Реестр заявок</div>} />
          <Route path="/tender/tenders/:id" element={<div>Карточка тендера</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const conflict = () => Object.assign(new Error('409'), {
  response: {
    status: 409,
    data: { detail: 'Документ изменён другим пользователем', code: 'E-CON-01', fields: [] },
  },
});

describe('RequestCardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nodes.value = {};
  });

  it('утверждённая заявка и право tender.tenders create — «Объявить тендер» → карточка тендера', async () => {
    nodes.value = { 'tender.tenders': ['view', 'create'] };
    serve(requestCard({ status: 'approved', allowed_actions: ['cancel'] }));
    post.mockResolvedValue({ data: { id: 'tn-1', number: 'ТН-2026-000003', status: 'draft' } });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Объявить тендер' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain('tender/v1/tenders');
    expect(post.mock.calls[0][1]).toEqual({ request_id: REQUEST_ID });
    expect(await screen.findByText('Карточка тендера')).toBeInTheDocument();
  });

  it('«Объявить тендер» — только у утверждённой заявки и с правом create', async () => {
    nodes.value = { 'tender.tenders': ['view', 'create'] };
    serve(requestCard({ status: 'in_approval', allowed_actions: [] }));
    const { unmount } = renderCard();
    await screen.findByRole('heading', { name: /ЗТ-2026-000007/ });
    expect(screen.queryByRole('button', { name: 'Объявить тендер' })).not.toBeInTheDocument();
    unmount();

    nodes.value = { 'tender.tenders': ['view'] };
    serve(requestCard({ status: 'approved', allowed_actions: [] }));
    renderCard();
    await screen.findByRole('heading', { name: /ЗТ-2026-000007/ });
    expect(screen.queryByRole('button', { name: 'Объявить тендер' })).not.toBeInTheDocument();
  });

  it('шапка, позиции и названия из справочников', async () => {
    serve(requestCard());
    renderCard();

    expect(await screen.findByRole('heading', { name: /ЗТ-2026-000007/ })).toBeInTheDocument();
    expect(screen.getByText('Черновик')).toBeInTheDocument();
    expect(await screen.findByText('П-015 — ЖК Нурлы Жол')).toBeInTheDocument();
    expect(await screen.findAllByText('T-METAL — Металлопрокат')).not.toHaveLength(0);
    expect(screen.getByText('Швеллер 12П')).toBeInTheDocument();
    expect(await screen.findByText('т')).toBeInTheDocument();
  });

  it('проект и автор — из самой карточки (project, author_name)', async () => {
    serve(requestCard({ project_id: 'p9', project: { id: 'p9', code: 'П-099', name: 'Склад' } }));
    renderCard();

    expect(await screen.findByText('П-099 — Склад')).toBeInTheDocument();
    expect(screen.getByText('Иванов А.')).toBeInTheDocument();
  });

  it('части — номер ЗЗ ссылкой на карточку БЗО и её статус', async () => {
    serve(requestCard({
      status: 'in_approval',
      allowed_actions: ['withdraw', 'cancel'],
      parts: [{
        id: 'part-1', kind: 'goods', article_id: 'a-metal', purchase_type: 'goods',
        bpp_request_id: BPP_REQUEST_ID, bpp_number: 'ЗЗ-2026-000045', bpp_status: 'in_approval',
        excluded_at: null,
      }],
    }));
    renderCard();

    const link = await screen.findByRole('link', { name: 'ЗЗ-2026-000045' });
    expect(link).toHaveAttribute('href', `/bpp/requests/${BPP_REQUEST_ID}`);
    const row = link.closest('tr') as HTMLElement;
    expect(within(row).getByText('На согласовании')).toBeInTheDocument();
    expect(within(row).getByText('ТМЦ')).toBeInTheDocument();
  });

  it('кнопки — ровно по allowed_actions', async () => {
    serve(requestCard({ allowed_actions: ['save', 'submit'] }));
    renderCard();

    expect(await screen.findByRole('button', { name: 'Отправить на согласование' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Редактировать' }))
      .toHaveAttribute('href', `/tender/requests/${REQUEST_ID}/edit`);
    expect(screen.queryByRole('button', { name: 'Отозвать' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отменить заявку' })).not.toBeInTheDocument();
  });

  it('«Отправить на согласование» уходит с version', async () => {
    serve(requestCard());
    post.mockResolvedValue({ data: requestCard({ status: 'in_approval', allowed_actions: [] }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить на согласование' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`tender/v1/requests/${REQUEST_ID}/submit`);
    expect(body).toEqual({ version: 4 });
    expect(await screen.findByText('На согласовании')).toBeInTheDocument();
  });

  it('409 E-CON-01 — сообщение, что заявку уже изменили, и «Обновить»', async () => {
    serve(requestCard());
    post.mockRejectedValue(conflict());
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить на согласование' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Заявку уже изменили');
    get.mockClear();
    await userEvent.click(within(alert).getByRole('button', { name: 'Обновить' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining(`requests/${REQUEST_ID}`)));
  });

  it('«Отменить заявку» — комментарий не короче 10 символов уходит в теле', async () => {
    serve(requestCard());
    post.mockResolvedValue({ data: requestCard({ status: 'cancelled', allowed_actions: [] }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Отменить заявку' }));
    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Отменить заявку' });
    await userEvent.type(within(dialog).getByRole('textbox'), 'коротко');
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole('textbox'), ' — проект заморожен');
    await userEvent.click(confirm);

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`requests/${REQUEST_ID}/cancel`);
    expect(body).toEqual({ version: 4, comment: 'коротко — проект заморожен' });
  });

  it('«Исключить часть» — только у отклонённой части и при праве exclude', async () => {
    serve(requestCard({
      status: 'rejected',
      allowed_actions: ['exclude', 'cancel'],
      parts: [
        {
          id: 'part-1', kind: 'goods', article_id: 'a-metal', purchase_type: 'goods',
          bpp_request_id: BPP_REQUEST_ID, bpp_number: 'ЗЗ-2026-000045', bpp_status: 'approved',
          excluded_at: null,
        },
        {
          id: 'part-2', kind: 'delivery', article_id: 'a-logistics', purchase_type: 'works',
          bpp_request_id: 'bpp-2', bpp_number: 'ЗЗ-2026-000046', bpp_status: 'rejected',
          excluded_at: null,
        },
      ],
    }));
    post.mockResolvedValue({ data: requestCard({ status: 'approved', allowed_actions: [] }) });
    renderCard();

    const buttons = await screen.findAllByRole('button', { name: 'Исключить часть' });
    expect(buttons).toHaveLength(1);
    expect(buttons[0].closest('tr')).toHaveTextContent('ЗЗ-2026-000046');
    await userEvent.click(buttons[0]);
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Исключить часть' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`requests/${REQUEST_ID}/parts/part-2/exclude`);
    expect(body).toEqual({ version: 4 });
  });

  it('исключённая часть помечена, «На доработке» — комментарий возврата', async () => {
    serve(requestCard({
      status: 'rework',
      rework_comment: 'Уточните марку стали',
      allowed_actions: ['save', 'submit'],
      parts: [{
        id: 'part-2', kind: 'works', article_id: 'a-logistics', purchase_type: 'works',
        bpp_request_id: 'bpp-2', bpp_number: 'ЗЗ-2026-000046', bpp_status: 'rejected',
        excluded_at: '2026-10-05T10:00:00Z',
      }],
    }));
    renderCard();

    expect(await screen.findByText('Уточните марку стали')).toBeInTheDocument();
    expect(screen.getByText('Заявка возвращена на доработку')).toBeInTheDocument();
    expect(screen.getByText(/Исключена/)).toBeInTheDocument();
  });

  it('«Удалить» черновик — DELETE с version и возврат в реестр', async () => {
    serve(requestCard());
    del.mockResolvedValue({ data: null });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Удалить' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(del).toHaveBeenCalled());
    const [url, config] = del.mock.calls[0];
    expect(url).toContain(`tender/v1/requests/${REQUEST_ID}`);
    expect(config.params).toEqual({ version: 4 });
    expect(await screen.findByText('Реестр заявок')).toBeInTheDocument();
  });

  it('404 — «не найдена»', async () => {
    get.mockImplementation((url: string) => {
      if (url.endsWith(`requests/${REQUEST_ID}`)) {
        return Promise.reject(Object.assign(new Error('404'), { response: { status: 404, data: {} } }));
      }
      return Promise.resolve(serveReference(url) ?? { data: [] });
    });
    renderCard();
    expect(await screen.findByText('Заявка не найдена или недоступна.')).toBeInTheDocument();
  });
});
