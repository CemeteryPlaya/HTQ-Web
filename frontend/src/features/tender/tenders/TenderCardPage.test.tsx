/**
 * Карточка тендера (T2.3; план §4.2–4.4): правка черновика (срок, валюта,
 * условия, проверяющий) и схемы оплаты, участники (контрагент + контакт,
 * потенциальный поставщик), публикация с диалогом ссылок «показываются
 * один раз», действия по приглашению (отзыв, перевыпуск, сброс
 * устройства), продление, отмена с причиной, счётчики и 409 E-CON-01.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { TenderCard } from './api';
import { TenderCardPage } from './TenderCardPage';
import {
  CONTACTS, COUNTERPARTIES, PROSPECTS, REQUEST_ID, TENDER_ID, awardView, comparisonData, invitation, tenderCard,
} from './testData';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, put, delete: vi.fn() } }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));
const copyText = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('../core/clipboard', () => ({ copyText }));
vi.mock('@/api/users', () => ({
  searchUserOptions: vi.fn(() => Promise.resolve([{ id: 77, full_name: 'Серикова Д.', email: '' }])),
}));

const LINK_1 = 'https://htq.group/supplier/AbCdEf123';
const LINK_2 = 'https://htq.group/supplier/ZyXwVu987';

function serve(card: TenderCard) {
  get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url.endsWith(`tender/v1/tenders/${TENDER_ID}`)) return Promise.resolve({ data: card });
    if (url.endsWith('tender/v1/counterparties')) {
      const q = (config?.params?.q ?? '').toLowerCase();
      return Promise.resolve({ data: COUNTERPARTIES.filter((row) => row.name.toLowerCase().includes(q)) });
    }
    if (url.endsWith('tender/v1/contacts')) return Promise.resolve({ data: CONTACTS });
    if (url.endsWith('tender/v1/prospects')) return Promise.resolve({ data: PROSPECTS });
    if (url.includes('refdata/v1/currencies')) {
      return Promise.resolve({ data: [{ id: 'c1', code: 'KZT', name: 'Тенге', symbol: '₸', is_active: true }] });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/tender/tenders/${TENDER_ID}`]}>
        <Routes>
          <Route path="/tender/tenders/:id" element={<TenderCardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const conflict = () => Object.assign(new Error('409'), {
  response: { status: 409, data: { detail: 'Документ изменён', code: 'E-CON-01', fields: [] } },
});

describe('TenderCardPage — черновик', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('шапка: номер, статус, заявка ссылкой, счётчики', async () => {
    serve(tenderCard({ counters: { sent: 3, opened: 2, submitted: 1 } }));
    renderCard();

    expect(await screen.findByRole('heading', { name: /ТН-2026-000003/ })).toBeInTheDocument();
    expect(screen.getByText('Черновик')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ЗТ-2026-000007' }))
      .toHaveAttribute('href', `/tender/requests/${REQUEST_ID}`);
    const counters = screen.getByTestId('tender-counters');
    expect(within(counters).getByText('Отправлено').nextSibling).toHaveTextContent('3');
    expect(within(counters).getByText('Открыто').nextSibling).toHaveTextContent('2');
    expect(within(counters).getByText('Подано').nextSibling).toHaveTextContent('1');
  });

  it('«Сохранить»: PATCH с version, сроком в ISO и условиями; схема — PUT по шаблону', async () => {
    serve(tenderCard());
    patch.mockResolvedValue({ data: tenderCard({ version: 3 }) });
    put.mockResolvedValue({ data: tenderCard({ version: 4 }) });
    renderCard();

    const deadline = await screen.findByLabelText('Срок приёма предложений');
    fireEvent.change(deadline, { target: { value: '2099-12-01T18:00' } });
    const terms = screen.getByLabelText('Условия поставки');
    await userEvent.clear(terms);
    await userEvent.type(terms, 'DDP объект');
    await userEvent.click(screen.getByRole('radio', { name: /Аванс/ }));
    await userEvent.type(screen.getByLabelText('Аванс, %'), '30');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body] = patch.mock.calls[0];
    expect(url).toContain(`tender/v1/tenders/${TENDER_ID}`);
    // Только изменённые поля: сервер проверяет каждое переданное (срок — «в
    // будущем»), и неизменённое поле не должно ронять правку соседнего.
    expect(body).toEqual({
      version: 2, delivery_terms: 'DDP объект',
      deadline_at: new Date('2099-12-01T18:00').toISOString(),
    });
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/payment-scheme`);
    expect(put.mock.calls[0][1]).toEqual({ kind: 'advance', advance_pct: '30' });
  });

  it('аванс без процента — схема не уходит, ошибка у поля', async () => {
    serve(tenderCard());
    renderCard();

    await userEvent.click(await screen.findByRole('radio', { name: /Аванс/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Аванс — от 1 до 99 %')).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it('проверяющий качества: пусто — ТД по должности, выбор — id пользователя', async () => {
    serve(tenderCard());
    patch.mockResolvedValue({ data: tenderCard({ version: 3 }) });
    renderCard();

    expect(await screen.findByText('Технический директор (по должности)')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Найти пользователя'), 'Сер');
    await userEvent.click(await screen.findByRole('button', { name: 'Серикова Д.' }));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][1]).toEqual({ quality_reviewer_user_id: 77, version: 2 });
  });

  it('проверяющий без роли — текст сервера у поля', async () => {
    serve(tenderCard());
    patch.mockRejectedValue(Object.assign(new Error('422'), {
      response: {
        status: 422,
        data: {
          detail: 'Не удалось сохранить тендер.', code: 'E-VAL-01',
          fields: [{ field: 'quality_reviewer_user_id', message: 'проверяющий — пользователь с ролью «Тендеры: Проверка качества»' }],
        },
      },
    }));
    renderCard();

    await userEvent.type(await screen.findByLabelText('Найти пользователя'), 'Сер');
    await userEvent.click(await screen.findByRole('button', { name: 'Серикова Д.' }));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('проверяющий — пользователь с ролью «Тендеры: Проверка качества»'))
      .toBeInTheDocument();
  });

  it('без права edit — полей правки и «Опубликовать» нет', async () => {
    serve(tenderCard({ status: 'intake', allowed_actions: ['extend', 'cancel', 'invite'] }));
    renderCard();

    expect(await screen.findByText('Приём предложений')).toBeInTheDocument();
    expect(screen.queryByLabelText('Условия поставки')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Опубликовать' })).not.toBeInTheDocument();
    expect(screen.getByText('Предоплата 100 %')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Продлить срок' })).toBeInTheDocument();
  });

  it('409 E-CON-01 при сохранении — «тендер уже изменили»', async () => {
    serve(tenderCard());
    patch.mockRejectedValue(conflict());
    renderCard();

    const terms = await screen.findByLabelText('Условия поставки');
    await userEvent.type(terms, ', разгрузка поставщиком');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Тендер уже изменили');
  });
});

describe('TenderCardPage — публикация и ссылки', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('«Опубликовать» — диалог ссылок с «Скопировать» и предупреждением', async () => {
    const card = tenderCard({
      invitations: [invitation(), invitation({ id: 'inv-2', counterparty_id: null, prospect_id: 'pr-1', name: 'ИП Новый поставщик', email: 'new@supplier.kz' })],
    });
    serve(card);
    post.mockResolvedValue({ data: { links: [{ invitation_id: 'inv-1', link: LINK_1 }, { invitation_id: 'inv-2', link: LINK_2 }] } });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Опубликовать' }));
    const confirm = await screen.findByRole('dialog');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Опубликовать' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/publish`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2 });

    const dialog = await screen.findByRole('dialog', { name: 'Ссылки для участников' });
    expect(within(dialog).getByText(/показываются один раз/)).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue(LINK_1)).toBeInTheDocument();
    expect(within(dialog).getByText('ИП Новый поставщик')).toBeInTheDocument();
    const copies = within(dialog).getAllByRole('button', { name: 'Скопировать' });
    expect(copies).toHaveLength(2);
    await userEvent.click(copies[1]);
    expect(copyText).toHaveBeenCalledWith(LINK_2);
  });

  it('без участников «Опубликовать» закрыта с подсказкой', async () => {
    serve(tenderCard({ invitations: [] }));
    renderCard();
    expect(await screen.findByRole('button', { name: 'Опубликовать' })).toBeDisabled();
    expect(screen.getByText('Добавьте хотя бы одного участника')).toBeInTheDocument();
  });

  it('перевыпуск — новая ссылка в диалоге; отзыв и сброс устройства — свои ручки', async () => {
    serve(tenderCard({
      status: 'intake', allowed_actions: ['extend', 'cancel', 'invite'],
      invitations: [invitation({
        status: 'opened', sent_at: '2099-11-01T10:00:00Z', first_opened_at: '2099-11-02T09:00:00Z',
        allowed_actions: ['revoke', 'reissue', 'reset_device'],
      })],
    }));
    post.mockImplementation((url: string) => Promise.resolve({
      data: url.endsWith('/reissue') ? { link: LINK_2 } : invitation({ status: 'revoked' }),
    }));
    renderCard();

    const row = (await screen.findByText('sales@metall.kz')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Открыто')).toBeInTheDocument();

    await userEvent.click(within(row).getByRole('button', { name: 'Перевыпустить ссылку' }));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Перевыпустить ссылку' }));
    const links = await screen.findByRole('dialog', { name: 'Ссылки для участников' });
    expect(within(links).getByDisplayValue(LINK_2)).toBeInTheDocument();
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/invitations/inv-1/reissue`);
    await userEvent.click(within(links).getByRole('button', { name: 'Готово' }));

    await userEvent.click(within(row).getByRole('button', { name: 'Сбросить устройство' }));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Сбросить устройство' }));
    await waitFor(() => expect(post.mock.calls.map((call) => call[0]))
      .toContainEqual(expect.stringContaining('invitations/inv-1/reset-device')));

    await userEvent.click(within(row).getByRole('button', { name: 'Отозвать' }));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отозвать' }));
    await waitFor(() => expect(post.mock.calls.map((call) => call[0]))
      .toContainEqual(expect.stringContaining('invitations/inv-1/revoke')));
  });

  it('кнопки приглашения — по allowed_actions приглашения (после срока — только «Отозвать»)', async () => {
    serve(tenderCard({
      status: 'intake', allowed_actions: ['extend', 'cancel'],
      invitations: [invitation({ status: 'opened', sent_at: '2099-11-01T10:00:00Z', allowed_actions: ['revoke'] })],
    }));
    renderCard();
    const row = (await screen.findByText('sales@metall.kz')).closest('tr') as HTMLElement;
    expect(within(row).getByRole('button', { name: 'Отозвать' })).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Перевыпустить ссылку' })).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Сбросить устройство' })).not.toBeInTheDocument();
  });

  it('отозванное приглашение — без действий', async () => {
    serve(tenderCard({
      status: 'intake', allowed_actions: ['invite'],
      invitations: [invitation({ status: 'revoked', revoked_at: '2099-11-03T09:00:00Z' })],
    }));
    renderCard();
    const row = (await screen.findByText('sales@metall.kz')).closest('tr') as HTMLElement;
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('«Продлить срок» — новый срок в ISO и version', async () => {
    serve(tenderCard({ status: 'intake', allowed_actions: ['extend'] }));
    post.mockResolvedValue({ data: tenderCard({ status: 'intake', version: 3 }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Продлить срок' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Новый срок'), { target: { value: '2099-12-10T12:00' } });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Продлить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/extend`);
    expect(post.mock.calls[0][1]).toEqual({ deadline_at: new Date('2099-12-10T12:00').toISOString(), version: 2 });
  });

  it('новый срок не позже прежнего — не уходит', async () => {
    serve(tenderCard({ status: 'intake', allowed_actions: ['extend'] }));
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Продлить срок' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Новый срок'), { target: { value: '2099-11-01T12:00' } });
    expect(within(dialog).getByRole('button', { name: 'Продлить' })).toBeDisabled();
    expect(within(dialog).getByText('Новый срок — позже текущего')).toBeInTheDocument();
  });

  it('«Отменить тендер» — причина от 10 символов', async () => {
    serve(tenderCard());
    post.mockResolvedValue({ data: tenderCard({ status: 'cancelled', allowed_actions: [] }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Отменить тендер' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByRole('textbox'), 'Поставщики не нашлись');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отменить тендер' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/cancel`);
    expect(post.mock.calls[0][1]).toEqual({ reason: 'Поставщики не нашлись', version: 2 });
  });
});

describe('TenderCardPage — участники', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('контрагент: поиск, только действующие, выбор контакта — POST с contact_id', async () => {
    serve(tenderCard());
    post.mockResolvedValue({ data: invitation({ id: 'inv-9', counterparty_id: 'cp-2', email: 'tender@stal.kz' }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить участника' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Поиск контрагента'), 'ТОО');
    const active = await within(dialog).findByRole('button', { name: /Сталь Трейд/ });
    expect(within(dialog).getByRole('button', { name: /Закрытая лавка/ })).toBeDisabled();
    await userEvent.click(active);

    // Неактивный контакт не предлагается; e-mail карточки — запасной вариант.
    expect(await within(dialog).findByRole('radio', { name: /tender@stal\.kz/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole('radio', { name: /old@stal\.kz/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('radio', { name: /info@stal\.kz/ })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('radio', { name: /tender@stal\.kz/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Пригласить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/invitations`);
    expect(post.mock.calls[0][1]).toEqual({ counterparty_id: 'cp-2', contact_id: 'ct-1' });
  });

  it('контакты недоступны (нет tender.prospects, 403) — остаётся e-mail карточки', async () => {
    serve(tenderCard());
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => (
      url.endsWith('tender/v1/contacts')
        ? Promise.reject(Object.assign(new Error('403'), { response: { status: 403, data: { detail: 'Недостаточно прав на контакты поставщиков.', code: 'E-ACC-01', fields: [] } } }))
        : base(url, config)));
    post.mockResolvedValue({ data: invitation({ id: 'inv-9' }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить участника' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Поиск контрагента'), 'Сталь');
    await userEvent.click(await within(dialog).findByRole('button', { name: /Сталь Трейд/ }));
    await userEvent.click(await within(dialog).findByRole('radio', { name: /info@stal\.kz/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Пригласить' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({ counterparty_id: 'cp-2' });
  });

  it('e-mail карточки контрагента — без contact_id', async () => {
    serve(tenderCard());
    post.mockResolvedValue({ data: invitation({ id: 'inv-9' }) });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить участника' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Поиск контрагента'), 'Сталь');
    await userEvent.click(await within(dialog).findByRole('button', { name: /Сталь Трейд/ }));
    await userEvent.click(await within(dialog).findByRole('radio', { name: /info@stal\.kz/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Пригласить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({ counterparty_id: 'cp-2' });
  });

  it('потенциальный поставщик после публикации — ссылка сразу в диалоге', async () => {
    serve(tenderCard({ status: 'intake', allowed_actions: ['invite'] }));
    post.mockResolvedValue({
      data: { ...invitation({ id: 'inv-9', counterparty_id: null, prospect_id: 'pr-1', name: 'ИП Новый поставщик', email: 'new@supplier.kz', status: 'sent' }), link: LINK_1 },
    });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить участника' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Потенциальный поставщик' }));
    await userEvent.click(await within(dialog).findByRole('radio', { name: /ИП Новый поставщик/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Пригласить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({ prospect_id: 'pr-1' });
    const links = await screen.findByRole('dialog', { name: 'Ссылки для участников' });
    expect(within(links).getByDisplayValue(LINK_1)).toBeInTheDocument();
  });

  it('без права invite — кнопки «Добавить участника» нет', async () => {
    serve(tenderCard({ allowed_actions: ['edit'] }));
    renderCard();
    await screen.findByText('sales@metall.kz');
    expect(screen.queryByRole('button', { name: 'Добавить участника' })).not.toBeInTheDocument();
  });
});

describe('TenderCardPage — вскрытие и выбор (этап 5)', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
  });

  it('до вскрытия вкладок нет; «Вскрыть» уходит с версией', async () => {
    const intake = tenderCard({ status: 'intake', allowed_actions: ['extend', 'cancel', 'open'] });
    serve(intake);
    post.mockResolvedValue({ data: { ...intake, status: 'opened', opened_at: '2026-10-20T10:00:00+05:00' } });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Вскрыть' }));
    expect(screen.queryByRole('tab', { name: 'Сравнение' })).toBeNull();
    const confirm = await screen.findByRole('dialog');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Вскрыть' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/open`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2 });
  });

  it('после вскрытия — вкладки «Сравнение» и «Выбор»', async () => {
    serve(tenderCard({ status: 'opened', opened_at: '2026-10-20T10:00:00+05:00', allowed_actions: ['cancel', 'award'] }));
    renderCard();
    expect(await screen.findByRole('tab', { name: 'Сравнение' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Выбор' })).toBeInTheDocument();
    expect(screen.getByText('sales@metall.kz')).toBeInTheDocument();
  });

  it('смена проверяющего после публикации — PATCH с версией', async () => {
    serve(tenderCard({ status: 'intake', allowed_actions: ['extend', 'cancel', 'reviewer'] }));
    patch.mockResolvedValue({ data: tenderCard({ status: 'intake', quality_reviewer_user_id: 77 }) });
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'Сменить' }));
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Найти пользователя'), 'Сер');
    await userEvent.click(await screen.findByRole('button', { name: 'Серикова Д.' }));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][1]).toEqual({ quality_reviewer_user_id: 77, version: 2 });
  });
});

describe('TenderCardPage — утверждение, передача, поставка (этап 5)', () => {
  const OPENED = '2026-10-20T10:00:00+05:00';
  /** Карточка + ручки вкладок этапа 5 (сравнение, выбор, поставка). */
  const serveCard = (card: TenderCard) => {
    serve(card);
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string, config?: object) => {
      if (url.endsWith('/comparison')) return Promise.resolve({ data: comparisonData() });
      if (url.endsWith('/award')) return Promise.resolve({ data: awardView({ allowed_actions: [] }) });
      if (url.endsWith('/delivery')) return Promise.resolve({ data: { tender_id: TENDER_ID, status: card.status, suppliers: [] } });
      if (url.endsWith('/receipts')) return Promise.resolve({ data: [] });
      return base(url, config);
    });
  };

  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('выбор утверждён — «Передать в БЗО» с версией, затем вкладка «Поставка»', async () => {
    const awarded = tenderCard({ status: 'awarded', opened_at: OPENED, allowed_actions: ['handover'] });
    serveCard(awarded);
    post.mockImplementation((url: string) => {
      if (url.endsWith('/handover')) {
        serveCard({ ...awarded, status: 'handed_over', allowed_actions: ['receipt'] });
        return Promise.resolve({ data: { tender_id: TENDER_ID, status: 'handed_over', documents: [
          { invitation_id: 'inv-1', supplier: 'ТОО «Металл-Снаб»', part_id: 'p1', doc_type: 'invoice', doc_id: 'd1', number: 'СЧ-2026-000010' },
        ] } });
      }
      return Promise.reject(new Error(url));
    });
    renderCard();
    expect(screen.queryByRole('tab', { name: 'Поставка' })).toBeNull();
    await userEvent.click(await screen.findByRole('button', { name: 'Передать в БЗО' }));
    const confirm = await screen.findByRole('dialog');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Передать в БЗО' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/handover`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2 });
    expect(toast.success).toHaveBeenCalledWith('Передано в БЗО: СЧ-2026-000010');
    expect(await screen.findByRole('tab', { name: 'Поставка' })).toBeInTheDocument();
  });

  it('на утверждении — ход согласования tender.award под вкладкой «Выбор»', async () => {
    serveCard(tenderCard({ status: 'on_approval', opened_at: OPENED, allowed_actions: [] }));
    renderCard();
    await userEvent.click(await screen.findByRole('tab', { name: 'Выбор' }));
    await waitFor(() => expect(get.mock.calls.some(([url, config]) => String(url).includes('signoff')
      && JSON.stringify(config ?? {}).includes('tender.award'))).toBe(true));
  });

  it('«Закрыть остаток» — с причиной и версией', async () => {
    const card = tenderCard({ status: 'delivery', opened_at: OPENED, allowed_actions: ['receipt', 'close_remainder'] });
    serveCard(card);
    post.mockResolvedValue({ data: card });
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'Закрыть остаток' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByRole('textbox'), 'Остаток закупим в следующем квартале');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Закрыть остаток' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/close-remainder`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2, comment: 'Остаток закупим в следующем квартале' });
  });
});
