/**
 * Форма загрузки выписки (ТЗ §11.2): без счёта и файла не отправляется;
 * счетов нет — плашка со ссылкой в настройки; загрузка идёт multipart с
 * `Idempotency-Key` и открывает экран загрузки; отказ сервера по полю —
 * у поля; файл больше 20 МБ и «по» позже сегодня отсекаются до отправки;
 * без права загрузки формы нет; счета не загрузились — это сказано.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { renderWithProviders } from '@/test/renderWithProviders';

import type { OrgAccount } from '../settings/api';
import { BankImportForm } from './BankImportForm';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const canEditSettings = vi.hoisted(() => ({ value: true }));
const canUpload = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string) => (node === 'bpp.bank' && canUpload.value)
      || (node === 'bpp.settings' && canEditSettings.value),
  }) as unknown as Permissions,
}));

const ACCOUNT: OrgAccount = {
  id: 'acc-1', iban: 'KZ86125KZT5004100100', bank_name: 'Халык Банк', bic: 'HSBKKZKX',
  currency: 'KZT', template: { id: 'tpl-1', name: 'Халык CSV', format: 'csv' },
  is_active: true, version: 1,
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  post.mockReset();
  toastError.mockReset();
  canEditSettings.value = true;
  canUpload.value = true;
});

function renderForm(accounts: OrgAccount[] = [ACCOUNT]) {
  get.mockResolvedValue({ data: accounts });
  return renderWithProviders(
    <Routes>
      <Route path="/bpp/bank/new" element={<BankImportForm />} />
      <Route path="/bpp/bank/:id" element={<p>Экран загрузки</p>} />
    </Routes>,
    { route: '/bpp/bank/new' },
  );
}

const csv = () => new File(['Дата;Номер\n'], 'vypiska.csv', { type: 'text/csv' });

async function chooseAccount() {
  await user.click(screen.getByRole('combobox', { name: 'Банк / счёт организации' }));
  await user.click(await screen.findByRole('option', { name: /Халык Банк/ }));
}

describe('BankImportForm', () => {
  it('без счёта и файла не отправляется и говорит, чего не хватает', async () => {
    renderForm();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText('Выберите банковский счёт организации')).toBeInTheDocument();
    expect(screen.getByText('Выберите файл выписки')).toBeInTheDocument();
  });

  it('счетов нет — плашка со ссылкой в настройки счетов', async () => {
    renderForm([]);
    const link = await screen.findByRole('link', { name: 'заведите счёт в настройках' });
    expect(link).toHaveAttribute('href', '/bpp/settings?tab=accounts');
    expect(screen.getByRole('combobox', { name: 'Банк / счёт организации' })).toBeDisabled();
  });

  it('без права на настройки — плашка без ссылки', async () => {
    canEditSettings.value = false;
    renderForm([]);
    expect(await screen.findByText(/их заводит администратор модуля/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /настройках/ })).toBeNull();
  });

  it('формат — из шаблона счёта; загрузка multipart с ключом и переход на экран загрузки', async () => {
    post.mockResolvedValue({ data: { id: 'imp-1', status: 'processing', warnings: [] } });
    renderForm();
    await chooseAccount();
    expect(screen.getByTestId('import-format')).toHaveTextContent('CSV');

    await user.type(screen.getByLabelText('Период с'), '01.09.2025');
    await user.type(screen.getByLabelText('Период по'), '15.09.2025');
    await user.upload(screen.getByLabelText('Файл выписки'), csv());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(await screen.findByText('Экран загрузки')).toBeInTheDocument();
    const [url, form, config] = post.mock.calls[0];
    expect(url).toBe('bpp/v1/bank/imports');
    expect(form).toBeInstanceOf(FormData);
    expect((form as FormData).get('account_id')).toBe('acc-1');
    expect((form as FormData).get('period_from')).toBe('2025-09-01');
    expect((form as FormData).get('period_to')).toBe('2025-09-15');
    expect(((form as FormData).get('file') as File).name).toBe('vypiska.csv');
    expect(config.headers['Idempotency-Key']).toBeTruthy();
  });

  it('у CSV без периода не отправляется', async () => {
    renderForm();
    await chooseAccount();
    await user.upload(screen.getByLabelText('Файл выписки'), csv());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(post).not.toHaveBeenCalled();
    expect(screen.getAllByText('Укажите период выписки')).toHaveLength(2);
  });

  it('отказ сервера по полю показывается у поля', async () => {
    post.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Файл не соответствует формату CSV',
          code: 'E-IMP-01',
          fields: [{ field: 'file', message: 'Файл не соответствует формату CSV: нужен файл .csv или .txt' }],
        },
      },
    });
    renderForm();
    await chooseAccount();
    await user.type(screen.getByLabelText('Период с'), '01.09.2025');
    await user.type(screen.getByLabelText('Период по'), '15.09.2025');
    await user.upload(screen.getByLabelText('Файл выписки'), csv());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(await screen.findByText(/нужен файл \.csv или \.txt/)).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  async function submitFilled() {
    await chooseAccount();
    await user.type(screen.getByLabelText('Период с'), '01.09.2025');
    await user.type(screen.getByLabelText('Период по'), '15.09.2025');
    await user.upload(screen.getByLabelText('Файл выписки'), csv());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));
  }

  it('E-IMP-02: поля отказа — колонки шаблона, у файла — полный текст отказа', async () => {
    const detail = 'Не найдена обязательная колонка «Назначение» шаблона «Халык CSV» в первых 30 строках файла.';
    post.mockRejectedValue({
      response: {
        status: 422,
        data: { detail, code: 'E-IMP-02', fields: [{ field: 'purpose', message: 'Назначение' }] },
      },
    });
    renderForm();
    await submitFilled();

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('413 E-FIL-02 — текст у поля файла', async () => {
    const message = 'Файл vypiska.csv не загружен: допустимы TXT, XLSX, CSV до 20 МБ';
    post.mockRejectedValue({
      response: {
        status: 413,
        data: { detail: message, code: 'E-FIL-02', fields: [{ field: 'file', message }] },
      },
    });
    renderForm();
    await submitFilled();

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });
  it('без права загрузки (БУХ) — формы нет, только объяснение; счета не запрашиваются', async () => {
    canUpload.value = false;
    renderForm();

    expect(await screen.findByText('У вашей роли нет права загружать выписки.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Загрузить' })).toBeNull();
    expect(screen.queryByLabelText('Файл выписки')).toBeNull();
    expect(screen.getByRole('link', { name: 'К списку загрузок' })).toHaveAttribute('href', '/bpp/bank');
    expect(get).not.toHaveBeenCalled();
  });

  it('счета не загрузились — сообщение об ошибке, а не молча пустой список', async () => {
    get.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    renderWithProviders(<BankImportForm />, { route: '/bpp/bank/new' });

    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить счета организации');
    expect(screen.queryByText(/Действующих счетов организации нет/)).toBeNull();
  });

  it('файл больше 20 МБ отсекается до отправки', async () => {
    renderForm();
    await chooseAccount();
    await user.type(screen.getByLabelText('Период с'), '01.09.2025');
    await user.type(screen.getByLabelText('Период по'), '15.09.2025');
    const big = csv();
    Object.defineProperty(big, 'size', { value: 20 * 1024 * 1024 + 1 });
    await user.upload(screen.getByLabelText('Файл выписки'), big);
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText('Файл vypiska.csv не загружен: допустимы TXT, XLSX, CSV до 20 МБ')).toBeInTheDocument();
  });

  it('«по» позже сегодняшнего дня — не отправляется', async () => {
    renderForm();
    await chooseAccount();
    await user.type(screen.getByLabelText('Период с'), '01.09.2025');
    await user.type(screen.getByLabelText('Период по'), '01.01.2099');
    await user.upload(screen.getByLabelText('Файл выписки'), csv());
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));

    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText('Период выписки не может заканчиваться позже сегодняшнего дня')).toBeInTheDocument();
  });
});
