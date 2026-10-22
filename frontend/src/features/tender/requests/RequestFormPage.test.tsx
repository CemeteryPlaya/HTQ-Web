/**
 * Форма заявки на тендер (T1.4, план §3.1, §3.5): правка черновика уходит
 * PATCH с `version`; переключатели доставки и СМР открывают свои поля;
 * подсказка остатка статьи — по `requests/budget` с плановой суммой
 * позиций этой статьи; 409 E-CON-01 — понятное сообщение.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { TenderRequestCard } from './api';
import { RequestFormPage } from './RequestFormPage';
import { REQUEST_ID, requestCard, serveReference } from './testData';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function serve(request: TenderRequestCard) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`tender/v1/requests/${REQUEST_ID}`)) return Promise.resolve({ data: request });
    return Promise.resolve(serveReference(url) ?? { data: [] });
  });
}

function renderForm(route = `/tender/requests/${REQUEST_ID}/edit`) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/tender/requests/new" element={<RequestFormPage />} />
          <Route path="/tender/requests/:id/edit" element={<RequestFormPage />} />
          <Route path="/tender/requests/:id" element={<div>Карточка заявки</div>} />
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

describe('RequestFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('«Сохранить черновик» — PATCH с version, статья позиции по умолчанию — null', { timeout: 15000 }, async () => {
    serve(requestCard());
    patch.mockResolvedValue({ data: requestCard({ version: 5 }) });
    renderForm();

    const name = await screen.findByDisplayValue('Швеллер 12П');
    await userEvent.clear(name);
    await userEvent.type(name, 'Швеллер 14П');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body] = patch.mock.calls[0];
    expect(url).toContain(`tender/v1/requests/${REQUEST_ID}`);
    expect(body.version).toBe(4);
    expect(body.items).toEqual([expect.objectContaining({
      id: 'i1', name: 'Швеллер 14П', qty: '10.000', plan_price: '365000.00', article_id: null, uom_id: 'uom-t',
    })]);
    expect(await screen.findByText('Карточка заявки')).toBeInTheDocument();
  });

  it('переключатели доставки и СМР открывают свои поля', async () => {
    serve(requestCard());
    renderForm();

    await screen.findByDisplayValue('Швеллер 12П');
    expect(screen.queryByLabelText('Плановая сумма доставки')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Нужна доставка до объекта' }));
    expect(screen.getByLabelText('Плановая сумма доставки')).toBeInTheDocument();

    expect(screen.queryByLabelText('Объём работ')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Нужны СМР' }));
    expect(screen.getByLabelText('Объём работ')).toBeInTheDocument();
    expect(screen.getByLabelText('Плановая сумма СМР')).toBeInTheDocument();
  });

  it('подсказка остатка статьи: доступно и остаток после плановой суммы позиций', async () => {
    serve(requestCard());
    renderForm();

    const hint = await screen.findByTestId('budget-hint-a-metal');
    await waitFor(() => expect(hint).toHaveTextContent('5 000 000,00 KZT'));
    expect(hint).toHaveTextContent('T-METAL — Металлопрокат');
    expect(hint).toHaveTextContent('3 650 000,00');
    expect(hint).toHaveTextContent('1 350 000,00 KZT');
    expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/requests/budget'),
      { params: { project_id: 'p1', article_id: 'a-metal', role: 'sn' } },
    );
  });

  it('проекты и статьи спрашиваются в роли заявки', async () => {
    serve(requestCard());
    renderForm();

    await screen.findByTestId('budget-hint-a-metal');
    expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/requests/projects'),
      { params: expect.objectContaining({ role: 'sn' }) },
    );
    expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/requests/articles'),
      { params: { project_id: 'p1', role: 'sn' } },
    );
  });

  it('отказ сервиса по полю позиции items[0].qty — текст у строки', async () => {
    serve(requestCard());
    patch.mockRejectedValue(Object.assign(new Error('422'), {
      response: {
        status: 422,
        data: {
          detail: 'Не удалось сохранить заявку.', code: 'E-VAL-01',
          fields: [{ field: 'items[0].qty', message: 'количество: число вне допустимого диапазона' }],
        },
      },
    }));
    renderForm();

    const name = await screen.findByDisplayValue('Швеллер 12П');
    await userEvent.type(name, ' 2');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    const row = name.closest('tr') as HTMLElement;
    expect(await within(row).findByText('количество: число вне допустимого диапазона')).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledWith('Не удалось сохранить заявку.', undefined);
  });

  it('ошибка типов pydantic {detail: [{loc, msg}]} — русский текст у поля и в сообщении', async () => {
    serve(requestCard());
    patch.mockRejectedValue(Object.assign(new Error('422'), {
      response: {
        status: 422,
        data: { detail: [{ type: 'date_from_datetime_parsing', loc: ['need_date'], msg: 'Input should be a valid date' }] },
      },
    }));
    renderForm();

    const name = await screen.findByDisplayValue('Швеллер 12П');
    await userEvent.type(name, ' 2');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    expect(await screen.findByText('Неверный формат значения')).toBeInTheDocument();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'Сервер не принял формат некоторых полей — проверьте выделенные поля.', undefined,
    ));
  });

  it('плановая сумма больше остатка — предупреждение', async () => {
    serve(requestCard({
      items: [{
        id: 'i1', line_no: 1, name: 'Швеллер 12П', specs: '', uom_id: 'uom-t',
        qty: '20.000', plan_price: '365000.00', need_date: '2099-11-01', article_id: null,
      }],
    }));
    renderForm();

    const hint = await screen.findByTestId('budget-hint-a-metal');
    await waitFor(() => expect(within(hint).getByRole('alert'))
      .toHaveTextContent('Плановая сумма больше доступного остатка статьи'));
  });

  it('«Отправить» без правок — только submit с version; с короткими полями — не уходит', { timeout: 15000 }, async () => {
    serve(requestCard());
    post.mockResolvedValue({ data: requestCard({ status: 'in_approval', allowed_actions: [] }) });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить на согласование' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`requests/${REQUEST_ID}/submit`);
    expect(post.mock.calls[0][1]).toEqual({ version: 4 });
    expect(patch).not.toHaveBeenCalled();
  });

  it('короткое обоснование — отправка не уходит, ошибка у поля', async () => {
    serve(requestCard({ justification: 'мало' }));
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить на согласование' }));
    expect(await screen.findByText('Обоснование — не короче 10 символов')).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it('409 E-CON-01 при сохранении — сообщение, что заявку уже изменили', async () => {
    serve(requestCard());
    patch.mockRejectedValue(conflict());
    renderForm();

    const name = await screen.findByDisplayValue('Швеллер 12П');
    await userEvent.type(name, ' и уголок');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Заявку уже изменили');
  });

  it('новая заявка без проекта — черновик не сохраняется', async () => {
    serve(requestCard());
    renderForm('/tender/requests/new');

    await userEvent.click(await screen.findByRole('button', { name: 'Сохранить черновик' }));
    expect(await screen.findByText('Выберите проект')).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('заявка вне черновика и доработки — правки нет, ссылка на карточку', async () => {
    serve(requestCard({ status: 'in_approval', allowed_actions: ['withdraw'] }));
    renderForm();

    expect(await screen.findByText('Заявку сейчас нельзя править.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'К карточке заявки' }))
      .toHaveAttribute('href', `/tender/requests/${REQUEST_ID}`);
  });
});
