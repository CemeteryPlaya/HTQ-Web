import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const getToken = vi.fn();

vi.mock('../api/users', () => ({ usersApi: { getToken: (...a: unknown[]) => getToken(...a) } }));
vi.mock('../api/client', () => ({ default: {} }));
vi.mock('@/lib/auth/profileStorage', () => ({ setAuthTokens: vi.fn() }));
const logUserAction = vi.fn();
vi.mock('@/lib/telemetry', () => ({ logUserAction: (...a: unknown[]) => logUserAction(...a) }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: string | { defaultValue?: string; minutes?: number }) => {
      if (typeof opts === 'string') return opts;
      return (opts?.defaultValue ?? _key).replace('{{minutes}}', String(opts?.minutes));
    },
  }),
}));

import LoginForm from './LoginForm';

function submit() {
  const inputs = document.querySelectorAll('input');
  fireEvent.change(inputs[0], { target: { value: 'alice' } });
  fireEvent.change(inputs[1], { target: { value: 'pw' } });
  fireEvent.submit(document.querySelector('form')!);
}

describe('LoginForm — блокировка входа (429)', () => {
  beforeEach(() => {
    getToken.mockReset();
    logUserAction.mockReset();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('показывает минуты из Retry-After', async () => {
    getToken.mockRejectedValue({
      response: { status: 429, headers: { 'retry-after': '840' },
        data: { detail: 'x', code: 'E-AUTH-LOCKED' } },
    });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    expect(await screen.findByText(/через 14 мин/)).toBeTruthy();
  });

  it('округляет секунды вверх до минут', async () => {
    getToken.mockRejectedValue({ response: { status: 429, headers: { 'retry-after': '61' }, data: { code: 'E-AUTH-LOCKED' } } });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    expect(await screen.findByText(/через 2 мин/)).toBeTruthy();
  });

  it('без Retry-After — «повторите позже», а не «неверный пароль»', async () => {
    getToken.mockRejectedValue({ response: { status: 429, headers: {}, data: { code: 'E-AUTH-LOCKED' } } });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    await waitFor(() => expect(screen.getByText(/Повторите позже/)).toBeTruthy());
    expect(screen.queryByText(/Неверный логин/)).toBeNull();
  });

  it('429 без кода (лимит nginx по IP) — «слишком много запросов», а не блокировка логина', async () => {
    getToken.mockRejectedValue({ response: { status: 429, headers: { 'retry-after': '30' }, data: '' } });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    expect(await screen.findByText(/Слишком много запросов/)).toBeTruthy();
    expect(screen.queryByText(/неудачных попыток/)).toBeNull();
  });

  it('логин не уходит в телеметрию (она пишется в лог бэкенда)', async () => {
    getToken.mockRejectedValue({ response: { status: 401, headers: {} } });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    await screen.findByText(/Неверный логин или пароль/);
    getToken.mockResolvedValue({ data: { access: 'a', refresh: 'r' } });
    submit();
    await waitFor(() => expect(logUserAction).toHaveBeenCalledWith({ action: 'login_success' }));
    expect(JSON.stringify(logUserAction.mock.calls)).not.toContain('alice');
  });

  it('401 по-прежнему — неверный логин или пароль', async () => {
    getToken.mockRejectedValue({ response: { status: 401, headers: {} } });
    render(<LoginForm onLogin={vi.fn()} />);
    submit();
    expect(await screen.findByText(/Неверный логин или пароль/)).toBeTruthy();
  });
});
