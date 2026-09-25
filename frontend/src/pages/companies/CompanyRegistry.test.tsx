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
const bankrupt = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: {
    tree: () => tree(),
    list: () => list(),
    archive: (slug: string) => archive(slug),
    restore: (slug: string) => restore(slug),
    bankrupt: (slug: string, body: unknown) => bankrupt(slug, body),
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
    bankrupt.mockReset();
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

  it('банкротство: предпросмотр с dry_run, затем подтверждение', async () => {
    roles.mockReturnValue(['admin']);
    bankrupt.mockImplementation((_slug: string, body: { dry_run?: boolean }) => Promise.resolve({ data: {
      company: { ...LIST[1], status: body.dry_run ? 'active' : 'archived', successor_slug: body.dry_run ? null : 'hi-tech-group' },
      successor: LIST[0], members_total: 3, members_granted: 2, members_already: 1,
      archived: !body.dry_run, dry_run: !!body.dry_run,
    } }));
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    await userEvent.click(screen.getByRole('button', { name: /Банкротство/ }));
    await userEvent.selectOptions(screen.getByLabelText(/Преемник/), 'hi-tech-group');
    await userEvent.click(screen.getByRole('button', { name: /Проверить/ }));
    expect(bankrupt).toHaveBeenCalledWith('hi-tech-qazaqstan', { successor: 'hi-tech-group', dry_run: true });
    expect(await screen.findByText(/2 сотрудник/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Подтвердить банкротство/ }));
    expect(bankrupt).toHaveBeenLastCalledWith('hi-tech-qazaqstan', { successor: 'hi-tech-group', dry_run: false });
  });

  it('показывает преемника у закрытой компании', async () => {
    roles.mockReturnValue(['admin']);
    // Архивная компания в дерево не входит (бэкенд строит его по действующим) —
    // её находят в блоке «В архиве», который рисуется из list.
    tree.mockResolvedValue({ data: [{ ...TREE[0], children: [] }] });
    list.mockResolvedValue({ data: [LIST[0], { ...LIST[1], status: 'archived', successor_slug: 'hi-tech-group' }] });
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.getByText(/Преемник/)).toBeInTheDocument();
  });

  it('предпросмотр, пришедший после смены преемника, подтвердить не даёт', async () => {
    roles.mockReturnValue(['admin']);
    const third = { id: 3, slug: 'hi-tech-service', name: 'Hi-Tech Service', kind: 'service', status: 'active',
                    country: 'KZ', parent_slug: 'hi-tech-group', archived_at: null };
    list.mockResolvedValue({ data: [...LIST, third] });
    let resolveDryRun: (v: unknown) => void = () => {};
    bankrupt.mockImplementation(() => new Promise((r) => { resolveDryRun = r; }));
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    await userEvent.click(screen.getByRole('button', { name: /Банкротство/ }));
    await userEvent.selectOptions(screen.getByLabelText(/Преемник/), 'hi-tech-group');
    await userEvent.click(screen.getByRole('button', { name: /Проверить/ }));
    // Пока ответ dry_run в пути, выбран другой преемник.
    await userEvent.selectOptions(screen.getByLabelText(/Преемник/), 'hi-tech-service');
    resolveDryRun({ data: {
      company: { ...LIST[1] }, successor: LIST[0], members_total: 3, members_granted: 2, members_already: 1,
      archived: false, dry_run: true,
    } });
    expect(await screen.findByRole('button', { name: /Проверить/ })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /Подтвердить банкротство/ })).toBeNull();
    expect(screen.queryByText(/2 сотрудник/)).toBeNull();
  });
});
