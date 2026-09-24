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
vi.mock('@/lib/auth/companySwitch', async (importOriginal) => ({
  // hostLabelOf — настоящий: переключатель строит по нему значения пунктов.
  hostLabelOf: (await importOriginal<typeof import('@/lib/auth/companySwitch')>()).hostLabelOf,
  switchCompany: (company: MyCompany) => switchCompany(company),
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
    expect(switchCompany).toHaveBeenCalledWith(group);
  });

  it('на поддомене-псевдониме узнаёт текущую компанию и переходит по объекту компании', async () => {
    // Блок I.2: хост несёт псевдоним (htq), а не слаг — сравнение с текущей
    // компанией обязано идти по метке хоста, иначе переключатель не узнал бы
    // свою же компанию.
    const htqAlias: MyCompany = { ...htq, subdomain: 'htq' };
    const hts: MyCompany = { slug: 'hi-tech-systems', subdomain: 'hts', name: 'Hi-Tech Systems', kind: 'it', is_default: false, is_current: false };
    companyFromHost.mockReturnValue('htq');
    myCompanies.mockResolvedValue({ data: [htqAlias, hts] });
    renderWithProviders(<CompanySwitcher />);
    expect(await screen.findByRole('combobox')).toHaveTextContent('Hi-Tech Qazaqstan');
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: /Hi-Tech Systems/ }));
    expect(switchCompany).toHaveBeenCalledWith(hts);
  });

  it('помечает архивную компанию', async () => {
    const dead: MyCompany = { slug: 'keg', name: 'KEG', kind: 'service', is_default: false, is_current: false, is_archived: true };
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq, dead] });
    renderWithProviders(<CompanySwitcher />);
    await userEvent.click(await screen.findByRole('combobox'));
    expect(await screen.findByRole('option', { name: /KEG · архив/ })).toBeInTheDocument();
  });
});
