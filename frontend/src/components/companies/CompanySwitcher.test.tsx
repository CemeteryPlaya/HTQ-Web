/**
 * Переключатель компании. Главное — правило видимости режима перехода:
 * одна компания на голом домене = переключателя нет.
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { MyCompany } from '@/types/companies';

import { CompanySwitcher } from './CompanySwitcher';

const myCompanies = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: { myCompanies: () => myCompanies() },
}));

const switchCompany = vi.fn();
const companyFromHost = vi.fn<(host: string) => string | null>();
vi.mock('@/lib/auth/companySwitch', () => ({
  switchCompany: (slug: string) => switchCompany(slug),
  companyFromHost: (host: string) => companyFromHost(host),
}));

const htq: MyCompany = { slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', is_default: true, is_current: true };
const group: MyCompany = { slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', is_default: false, is_current: false };

describe('CompanySwitcher', () => {
  beforeEach(() => {
    switchCompany.mockReset();
    companyFromHost.mockReset();
  });

  it('скрыт при одной компании на голом домене (режим перехода)', async () => {
    companyFromHost.mockReturnValue(null);
    myCompanies.mockResolvedValue({ data: [htq] });
    renderWithProviders(<CompanySwitcher />);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('виден при одной компании, если хост уже на её поддомене', async () => {
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq] });
    renderWithProviders(<CompanySwitcher />);
    expect(await screen.findByRole('combobox')).toHaveTextContent('Hi-Tech Qazaqstan');
  });

  it('при выборе другой компании переходит на её поддомен', async () => {
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq, group] });
    renderWithProviders(<CompanySwitcher />);
    await userEvent.click(await screen.findByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: /Hi-Tech Group/ }));
    expect(switchCompany).toHaveBeenCalledWith('hi-tech-group');
  });
});
