/**
 * Вкладка «Параметры модуля»: значение из реестра сервера, правка по месту
 * `PATCH settings/<ключ>` `{value}` с `Idempotency-Key`, проверка границ до
 * запроса, отказ сервера E-VAL-01 — у поля; без права правки — только
 * значение. Экран «Настройки» показывает вкладку лишь при `bpp.settings`
 * `view`.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { renderWithProviders } from '@/test/renderWithProviders';

import type { ModuleParam } from './api';
import { ModuleParamsTab } from './ModuleParamsTab';
import { SettingsPage } from './SettingsPage';

const get = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, patch, post: vi.fn() } }));

const toastError = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: toastSuccess, info: vi.fn() } }));

const canView = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, flag: string) => node === 'bpp.settings' && flag === 'view' && canView.value,
  }) as unknown as Permissions,
}));

const LABEL = 'Порог метки «Проверенный» контрагента, удачных документов';

const PARAM: ModuleParam = {
  key: 'counterparty_verified_threshold', label: LABEL, kind: 'integer',
  value: 3, default: 3, min: 1, max: 100,
  help: 'Контрагент получает метку «Проверенный» после стольких удачных документов.',
  updated_at: null,
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  patch.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
  canView.value = true;
  get.mockImplementation((url: string) => Promise.resolve({
    data: url === 'bpp/v1/settings' ? [PARAM] : [],
  }));
});

describe('ModuleParamsTab', () => {
  it('сохраняет новое значение PATCH с ключом идемпотентности', async () => {
    patch.mockResolvedValue({
      data: { ...PARAM, value: 5, updated_at: '2026-09-29T10:00:00+00:00' },
    });
    renderWithProviders(<ModuleParamsTab canEdit />);

    const form = await screen.findByRole('form', { name: LABEL });
    expect(within(form).getByText(PARAM.help)).toBeInTheDocument();
    expect(screen.getByText('Действует значение по умолчанию.')).toBeInTheDocument();
    const input = within(form).getByLabelText(LABEL);
    expect(input).toHaveValue(3);
    const save = within(form).getByRole('button', { name: 'Сохранить' });
    expect(save).toBeDisabled();  // ничего не изменено

    await user.clear(input);
    await user.type(input, '5');
    await user.click(save);

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const [url, body, config] = patch.mock.calls[0];
    expect(url).toBe('bpp/v1/settings/counterparty_verified_threshold');
    expect(body).toEqual({ value: 5 });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(await screen.findByText('По умолчанию — 3.')).toBeInTheDocument();
  });

  it('значение вне границ — правило у поля, без запроса', async () => {
    renderWithProviders(<ModuleParamsTab canEdit />);
    const form = await screen.findByRole('form', { name: LABEL });
    const input = within(form).getByLabelText(LABEL);
    await user.clear(input);
    await user.type(input, '101');
    await user.click(within(form).getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText('Целое число от 1 до 100')).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(patch).not.toHaveBeenCalled();
  });

  it('отказ сервера E-VAL-01 — текст поля value у поля, без тоста', async () => {
    const message = `${LABEL}: целое число от 1 до 100.`;
    patch.mockRejectedValue({
      response: {
        status: 422,
        data: { detail: message, code: 'E-VAL-01', fields: [{ field: 'value', message }] },
      },
    });
    renderWithProviders(<ModuleParamsTab canEdit />);
    const form = await screen.findByRole('form', { name: LABEL });
    const input = within(form).getByLabelText(LABEL);
    await user.clear(input);
    await user.type(input, '7');
    await user.click(within(form).getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('без права правки — только значение, без поля и кнопки', async () => {
    renderWithProviders(<ModuleParamsTab canEdit={false} />);
    const form = await screen.findByRole('form', { name: LABEL });
    expect(within(form).queryByRole('spinbutton')).toBeNull();
    expect(within(form).queryByRole('button')).toBeNull();
    expect(within(form).getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Параметры меняет администратор модуля.')).toBeInTheDocument();
  });
});

describe('SettingsPage — вкладка «Параметры модуля»', () => {
  it('открывается по ?tab=params', async () => {
    renderWithProviders(<SettingsPage />, { route: '/bpp/settings?tab=params' });
    expect(screen.getByRole('tab', { name: 'Параметры модуля' }))
      .toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('form', { name: LABEL })).toBeInTheDocument();
  });

  it('без bpp.settings view вкладки нет, и ?tab=params открывает счета', async () => {
    canView.value = false;
    renderWithProviders(<SettingsPage />, { route: '/bpp/settings?tab=params' });
    expect(screen.queryByRole('tab', { name: 'Параметры модуля' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Счета организации' }))
      .toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls.map(([url]) => url)).not.toContain('bpp/v1/settings');
  });
});
