import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { CompanyMembersPanel } from './CompanyMembersPanel';
import { CompanyModulesPanel } from './CompanyModulesPanel';

const modules = vi.fn();
const setModule = vi.fn();
const memberships = vi.fn();
const grantMembership = vi.fn();
const revokeMembership = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: {
    modules: () => modules(), setModule: (s: string, a: string, b: unknown) => setModule(s, a, b),
    memberships: () => memberships(), grantMembership: (s: string, b: unknown) => grantMembership(s, b),
    revokeMembership: (s: string, u: number) => revokeMembership(s, u),
  },
}));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

describe('CompanyModulesPanel', () => {
  beforeEach(() => {
    modules.mockResolvedValue({ data: [
      { app_label: 'hr', enabled: true, message: '', is_core: true },
      { app_label: 'tasks', enabled: true, message: '', is_core: false },
    ] });
    setModule.mockResolvedValue({ data: { app_label: 'tasks', enabled: false, message: '', is_core: false } });
  });

  it('ядро не переключается, обычный модуль — PATCH с enabled=false', async () => {
    renderWithProviders(<CompanyModulesPanel slug="htq" canEdit />);
    const hr = await screen.findByRole('switch', { name: /hr/ });
    expect(hr).toBeDisabled();
    await userEvent.click(screen.getByRole('switch', { name: /tasks/ }));
    expect(setModule).toHaveBeenCalledWith('htq', 'tasks', { enabled: false });
  });
});

describe('CompanyMembersPanel', () => {
  beforeEach(() => {
    memberships.mockResolvedValue({ data: [
      { user_id: 7, username: 'ivanov', full_name: 'Иванов Иван', email: 'i@x', is_active: true, is_default: true },
    ] });
    grantMembership.mockResolvedValue({ data: { user_id: 8, username: 'petrov', full_name: '', email: '', is_active: true, is_default: false } });
    revokeMembership.mockReset();
  });

  it('выдаёт членство по id и показывает отказ self_revoke', async () => {
    revokeMembership.mockRejectedValue({ response: { status: 409, data: { detail: 'Нельзя снять членство у себя', code: 'self_revoke' } } });
    renderWithProviders(<CompanyMembersPanel slug="htq" canEdit canRevoke />);
    expect(await screen.findByText('ivanov')).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/id пользователя/i), '8');
    await userEvent.click(screen.getByRole('button', { name: /Выдать/ }));
    expect(grantMembership).toHaveBeenCalledWith('htq', { user_id: 8, is_default: false });

    await userEvent.click(screen.getByRole('button', { name: /Снять/ }));
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/у себя/));
  });
});
