/**
 * Реестр компаний. Проверяем то, что отличает экран: дерево из ответа
 * /companies/tree, подпись «создание — командой», архив как платформенная
 * операция и читаемый отказ 409 last_active.
 */
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import CompanyRegistry from './CompanyRegistry';

const tree = vi.fn();
const list = vi.fn();
const archive = vi.fn();
const restore = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: {
    tree: () => tree(),
    list: () => list(),
    archive: (slug: string) => archive(slug),
    restore: (slug: string) => restore(slug),
    modules: vi.fn(), setModule: vi.fn(), memberships: vi.fn(),
    grantMembership: vi.fn(), revokeMembership: vi.fn(), patch: vi.fn(), get: vi.fn(),
    myCompanies: vi.fn(),
  },
}));

const roles = vi.fn<[], string[]>();
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { roles: roles() }, isLoggedIn: true }),
}));
const companyArchived = vi.fn(() => false);
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ companyArchived: companyArchived() }),
}));
vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));

const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

const TREE = [{
  slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '',
  children: [{ slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction',
               status: 'active', country: 'KZ', children: [] }],
}];
const LIST = [
  { id: 1, slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '', parent_slug: null, archived_at: null },
  { id: 2, slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', status: 'active', country: 'KZ', parent_slug: 'hi-tech-group', archived_at: null },
];

describe('CompanyRegistry', () => {
  beforeEach(() => {
    tree.mockResolvedValue({ data: TREE });
    list.mockResolvedValue({ data: LIST });
    archive.mockReset();
    toastError.mockReset();
    companyArchived.mockReturnValue(false);
  });

  it('рисует дерево владения и говорит, что создание — командой', async () => {
    roles.mockReturnValue(['admin']);
    renderWithProviders(<CompanyRegistry />);
    const treeEl = await screen.findByTestId('company-tree');
    // findByText (not getByText): the tree query resolves via react-query's
    // notifyManager, which schedules the re-render on a real setTimeout(0)
    // macrotask — the testid container is already in the DOM (empty) before
    // that fires, so only an actively-polling query can see the loaded data.
    expect(await within(treeEl).findByText('Hi-Tech Group')).toBeInTheDocument();
    expect(within(treeEl).getByText('Hi-Tech Qazaqstan')).toBeInTheDocument();
    expect(screen.getByText(/company_create/)).toBeInTheDocument();
  });

  it('не показывает архив не платформенному администратору', async () => {
    roles.mockReturnValue(['staff']);
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.queryByRole('button', { name: /В архив/ })).toBeNull();
  });

  it('409 last_active показывается читаемо', async () => {
    roles.mockReturnValue(['admin']);
    archive.mockRejectedValue({ response: { status: 409, data: { detail: 'единственная действующая', code: 'last_active' } } });
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    await userEvent.click(screen.getByRole('button', { name: /В архив/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Подтвердить/ }));
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/единственная действующая/));
  });

  it('на поддомене архива не даёт ничего менять и подсказывает, где восстановить', async () => {
    roles.mockReturnValue(['admin']);
    companyArchived.mockReturnValue(true);
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.queryByRole('button', { name: /В архив/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Изменить/ })).toBeNull();
    expect(screen.getByText(/Восстановить компанию можно из реестра/)).toBeInTheDocument();
  });
});
