/**
 * Страница поставщика `/supplier/:token` (T3.5; план этапа 3 §1, §2 T3.5):
 * промежуточная карточка → «Открыть предложение» (привязка устройства) →
 * форма; экраны ошибок 404 / 403 E-TND-06 / 409 E-TND-05 / 429; после
 * срока — только чтение и «Ожидается решение»; согласие на ПДн перед
 * первой отправкой; отзыв, отказ с причиной, файлы КП.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';
import {
  TOKEN, fakeResponse, portalCard, portalOffer, portalTender,
} from '@/features/tender/portal/testData';
import type { PortalCard, PortalOffer, PortalTender } from '@/features/tender/portal/types';

import SupplierTender from './SupplierTender';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

type Reply = ReturnType<typeof fakeResponse>;
type Handler = (init: RequestInit) => Reply;

const fetchMock = vi.fn();
const BASE = `/api/tender/v1/supplier/${TOKEN}`;

function routes(table: Record<string, Reply | Handler>) {
  fetchMock.mockImplementation((url: string, init: RequestInit) => {
    const key = `${init.method ?? 'GET'} ${url.replace(BASE, '') || '/'}`;
    const reply = table[key];
    if (!reply) return Promise.resolve(fakeResponse(404, { detail: `no mock: ${key}`, code: 'E-NOT-FOUND' }));
    return Promise.resolve(typeof reply === 'function' ? reply(init) : reply);
  });
}

function bound(over: { card?: Partial<PortalCard>; tender?: Partial<PortalTender>; offer?: Partial<PortalOffer> } = {}) {
  return {
    'GET /': fakeResponse(200, portalCard({ bound: true, ...over.card })),
    'GET /tender': fakeResponse(200, portalTender(over.tender)),
    'GET /offer': fakeResponse(200, portalOffer(over.offer)),
    'GET /offer/files': fakeResponse(200, []),
  };
}

const bodyOf = (method: string, path: string) => {
  const call = fetchMock.mock.calls.find(([url, init]) => url === `${BASE}${path}` && init.method === method);
  return call ? JSON.parse(call[1].body as string) : undefined;
};

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/supplier/${TOKEN}`]}>
        <Routes>
          <Route path="/supplier/:token" element={<SupplierTender />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Форма — десятки полей; под нагрузкой всего набора 5 с по умолчанию мало.
const SLOW = { timeout: 15000 };

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('вход по ссылке', SLOW, () => {
  it('не привязано: промежуточная карточка ничего не пишет; «Открыть предложение» — bind, затем форма', async () => {
    let boundNow = false;
    routes({
      'GET /': () => fakeResponse(200, portalCard({ bound: boundNow })),
      'POST /bind': () => { boundNow = true; return fakeResponse(200, { bound: true }); },
      'GET /tender': fakeResponse(200, portalTender()),
      'GET /offer': fakeResponse(200, portalOffer()),
      'GET /offer/files': fakeResponse(200, []),
    });
    renderPage();

    expect(await screen.findByText('ТОО «Hi-Tech Qazaqstan»')).toBeInTheDocument();
    expect(screen.getByText(/ТН-2026-000003/)).toBeInTheDocument();
    expect(screen.getByText(/закрепится за этим устройством/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([, init]) => init.method)).toEqual(['GET']);

    await userEvent.click(screen.getByRole('button', { name: 'Открыть предложение' }));
    expect(await screen.findByText('Швеллер 12П')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => url === `${BASE}/bind` && init.method === 'POST')).toBe(true);
  });

  it('404 — «Ссылка недействительна»', async () => {
    routes({ 'GET /': fakeResponse(404, { detail: 'Ссылка недействительна', code: 'E-NOT-FOUND' }) });
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Ссылка недействительна' })).toBeInTheDocument();
  });

  it('bind 409 E-TND-06 — экран «открыта на другом устройстве»', async () => {
    routes({
      'GET /': fakeResponse(200, portalCard()),
      'POST /bind': fakeResponse(409, { detail: 'Ссылка уже открыта на другом устройстве', code: 'E-TND-06' }),
    });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Открыть предложение' }));
    expect(await screen.findByRole('heading', { name: 'Ссылка открыта на другом устройстве' })).toBeInTheDocument();
    expect(screen.getByText(/обратитесь к закупщику/)).toBeInTheDocument();
  });

  it('привязано, но cookie не та (403 E-TND-06) — тот же экран', async () => {
    routes({
      'GET /': fakeResponse(200, portalCard({ bound: true })),
      'GET /tender': fakeResponse(403, { detail: 'Ссылка открыта на другом устройстве', code: 'E-TND-06', details: { rebind: 'otp' } }),
      'GET /offer': fakeResponse(403, { detail: 'Ссылка открыта на другом устройстве', code: 'E-TND-06' }),
      'GET /offer/files': fakeResponse(403, { detail: 'x', code: 'E-TND-06' }),
    });
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Ссылка открыта на другом устройстве' })).toBeInTheDocument();
  });

  it('429 — «Слишком много запросов, повторите через N с»', async () => {
    routes({ 'GET /': fakeResponse(429, { detail: 'Лимит', code: 'E-RATE-01' }, { 'Retry-After': '42' }) });
    renderPage();
    expect(await screen.findByText('Слишком много запросов, повторите через 42 с')).toBeInTheDocument();
  });
});

describe('форма предложения', SLOW, () => {
  it('позиции без плановых цен, ТЗ ссылкой; «Сохранить черновик» — PUT с version и ценами', async () => {
    routes({ ...bound(), 'PUT /offer': (init) => fakeResponse(200, portalOffer({ version: 4, ...JSON.parse(init.body as string) })) });
    renderPage();

    const price = await screen.findByLabelText('Цена за единицу: Швеллер 12П');
    await userEvent.type(price, '365000');
    expect(screen.getByRole('link', { name: /ТЗ\.pdf/ })).toHaveAttribute('href', `${BASE}/files/doc-1`);
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    await waitFor(() => expect(bodyOf('PUT', '/offer')).toBeDefined());
    const body = bodyOf('PUT', '/offer');
    expect(body.version).toBe(3);
    expect(body.lines[0]).toMatchObject({ item_id: 'it-1', price: '365000.00', participates: true });
    expect(body).not.toHaveProperty('requisites');
  });

  it('первая отправка — только с согласием на ПДн; уходит {version, pd_consent}', async () => {
    const offer = portalOffer();
    offer.lines = offer.lines.map((line) => ({ ...line, price: '1000.00', delivery_date: '2099-11-24' }));
    routes({
      ...bound(),
      'GET /offer': fakeResponse(200, offer),
      'POST /offer/submit': fakeResponse(200, { ...offer, status: 'submitted', number: 1, version: 4, pd_consent_at: '2026-10-07T10:00:00Z', editable: true }),
    });
    renderPage();

    const send = await screen.findByRole('button', { name: 'Отправить предложение' });
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: /Согласен на обработку персональных данных/ }));
    await userEvent.click(send);

    await waitFor(() => expect(bodyOf('POST', '/offer/submit')).toEqual({ version: 3, pd_consent: true }));
    expect(await screen.findByText(/Предложение № 1 отправлено/)).toBeInTheDocument();
  });

  it('незаполненная цена — отправка не уходит, ошибка у позиции', async () => {
    routes(bound({ offer: { pd_consent_at: '2026-10-01T10:00:00Z' } }));
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить предложение' }));
    expect((await screen.findAllByText('Укажите цену за единицу больше нуля')).length).toBeGreaterThan(0);
    expect(bodyOf('POST', '/offer/submit')).toBeUndefined();
  });

  it('аналоги запрещены — переключателя аналога нет', async () => {
    routes(bound({ tender: { allow_analogs: false } }));
    renderPage();
    await screen.findByText('Швеллер 12П');
    expect(screen.queryByRole('checkbox', { name: /Предлагаю аналог/ })).not.toBeInTheDocument();
  });

  it('известный контрагент — реквизиты только для чтения', async () => {
    routes(bound());
    renderPage();
    expect(await screen.findByText('ТОО «Сталь Трейд»')).toBeInTheDocument();
    expect(screen.queryByLabelText('Наименование организации')).not.toBeInTheDocument();
  });

  it('потенциальный поставщик — реквизиты правятся и уходят в PUT', async () => {
    routes({
      ...bound({ offer: { requisites_readonly: false } }),
      'PUT /offer': fakeResponse(200, portalOffer({ version: 4, requisites_readonly: false })),
    });
    renderPage();
    const name = await screen.findByLabelText('Наименование организации');
    await userEvent.clear(name);
    await userEvent.type(name, 'ИП Новый');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(bodyOf('PUT', '/offer')?.requisites).toMatchObject({ name: 'ИП Новый' }));
  });

  it('409 E-TND-05 при сохранении — «Приём предложений завершён», форма только для чтения', async () => {
    routes({ ...bound(), 'PUT /offer': fakeResponse(409, { detail: 'Приём предложений завершён', code: 'E-TND-05' }) });
    renderPage();

    await userEvent.type(await screen.findByLabelText('Цена за единицу: Швеллер 12П'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Приём предложений завершён');
    expect(screen.queryByRole('button', { name: 'Сохранить черновик' })).not.toBeInTheDocument();
  });

  it('отказ с причиной от 10 символов — POST decline', async () => {
    routes({ ...bound(), 'POST /decline': fakeResponse(200, { status: 'declined' }) });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Отказаться от участия' }));
    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Отказаться' });
    await userEvent.type(within(dialog).getByRole('textbox'), 'нет');
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole('textbox'), ' товара на складе');
    await userEvent.click(confirm);

    await waitFor(() => expect(bodyOf('POST', '/decline')).toEqual({ reason: 'нет товара на складе' }));
    expect(await screen.findByText('Вы отказались от участия в тендере')).toBeInTheDocument();
  });

  it('после сохранения список файлов КП перечитывается: у черновика-копии свои ключи файлов', async () => {
    routes({ ...bound(), 'PUT /offer': fakeResponse(200, portalOffer({ version: 4 })) });
    renderPage();
    const filesGets = () => fetchMock.mock.calls
      .filter(([url, init]) => url === `${BASE}/offer/files` && (init.method ?? 'GET') === 'GET').length;

    await userEvent.type(await screen.findByLabelText('Цена за единицу: Швеллер 12П'), '365000');
    await waitFor(() => expect(filesGets()).toBeGreaterThan(0));
    const before = filesGets();
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(filesGets()).toBeGreaterThan(before));
  });

  it('отозванное предложение без правок — «Отправить» сначала сохраняет черновик, затем submit с его version', async () => {
    const offer = portalOffer({ status: 'withdrawn', number: 1, pd_consent_at: '2026-10-07T10:00:00Z' });
    offer.lines = offer.lines.map((line) => ({ ...line, price: '1000.00', delivery_date: '2099-11-24' }));
    routes({
      ...bound(),
      'GET /offer': fakeResponse(200, offer),
      'PUT /offer': fakeResponse(200, { ...offer, id: 'of-2', status: 'draft', number: null, version: 1 }),
      'POST /offer/submit': fakeResponse(200, { ...offer, id: 'of-2', status: 'submitted', number: 2, version: 2 }),
    });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Отправить предложение' }));
    await waitFor(() => expect(bodyOf('POST', '/offer/submit')).toEqual({ version: 1 }));
    expect(bodyOf('PUT', '/offer')).toMatchObject({ version: 3 });
  });

  it('отправленное предложение — «Отозвать» с version', async () => {
    routes({
      ...bound({ offer: { status: 'submitted', number: 2, history: [{ number: 1, status: 'replaced', submitted_at: '2026-10-05T10:00:00Z' }, { number: 2, status: 'submitted', submitted_at: '2026-10-06T10:00:00Z' }] } }),
      'POST /offer/withdraw': fakeResponse(200, portalOffer({ status: 'withdrawn', version: 4 })),
    });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Отозвать предложение' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отозвать' }));
    await waitFor(() => expect(bodyOf('POST', '/offer/withdraw')).toEqual({ version: 3 }));
  });

  it('файл КП — multipart в offer/files', async () => {
    routes({ ...bound(), 'POST /offer/files': fakeResponse(201, { id: 'f1', name: 'kp.pdf', size: 1000 }) });
    renderPage();

    const input = await screen.findByLabelText('Добавить файл КП');
    const file = new File(['%PDF'], 'kp.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => url === `${BASE}/offer/files` && init.method === 'POST');
      expect((call?.[1].body as FormData).get('file')).toBe(file);
    });
  });

  it('файл недопустимого типа — не уходит, объяснение', async () => {
    routes(bound());
    renderPage();
    const input = await screen.findByLabelText('Добавить файл КП');
    fireEvent.change(input, { target: { files: [new File(['<x/>'], 'kp.xml', { type: 'text/xml' })] } });
    expect(await screen.findByText(/допустимы PDF, DOCX, XLSX, JPG, PNG до 20 МБ/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => url === `${BASE}/offer/files` && init.method === 'POST')).toBe(false);
  });
});

describe('после срока', SLOW, () => {
  it('приём закрыт — только чтение и «Ожидается решение»', async () => {
    routes(bound({
      card: { intake_open: false }, tender: { intake_open: false },
      offer: { status: 'submitted', number: 1, editable: false },
    }));
    renderPage();
    expect(await screen.findByText('Ожидается решение')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сохранить черновик' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить предложение' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Цена за единицу: Швеллер 12П')).not.toBeInTheDocument();
  });
});

describe('итог тендера (TND-035)', SLOW, () => {
  const closed = (tender: Partial<PortalTender>) => bound({
    card: { intake_open: false },
    tender: { intake_open: false, ...tender },
    offer: { status: 'submitted', number: 1, editable: false },
  });

  it('выбран — «Выбрано по позициям» со своими позициями', async () => {
    routes(closed({
      result: 'awarded',
      result_items: [{ line_no: 1, name: 'Швеллер 12П', qty: '10' }, { line_no: 3, name: 'Уголок 50×5', qty: '4' }],
    }));
    renderPage();
    expect(await screen.findByText('Выбрано по позициям:')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Выбранные позиции' });
    expect(within(list).getByText('1. Швеллер 12П — 10')).toBeInTheDocument();
    expect(within(list).getByText('3. Уголок 50×5 — 4')).toBeInTheDocument();
    expect(screen.queryByText('Ожидается решение')).not.toBeInTheDocument();
  });

  it('не выбран — «Не выбрано», без позиций', async () => {
    routes(closed({ result: 'not_awarded', result_items: [] }));
    renderPage();
    expect(await screen.findByText('Не выбрано')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Выбранные позиции' })).not.toBeInTheDocument();
  });

  it('отменён и не состоялся', async () => {
    routes(closed({ result: 'cancelled' }));
    const { unmount } = renderPage();
    expect(await screen.findByText('Тендер отменён')).toBeInTheDocument();
    unmount();
    routes(closed({ result: 'failed' }));
    renderPage();
    expect(await screen.findByText('Тендер не состоялся')).toBeInTheDocument();
  });
});
