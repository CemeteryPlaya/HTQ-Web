import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Company } from '@/types/companies';

import { CompanyFormDialog } from './CompanyFormDialog';

const patch = vi.fn();
vi.mock('@/api/companies', () => ({ companiesApi: { patch: (s: string, b: unknown) => patch(s, b) } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const group: Company = { id: 1, slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '', parent_slug: null, archived_at: null };
const htq: Company = { id: 2, slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'regional', status: 'active', country: '', parent_slug: null, archived_at: null };

describe('CompanyFormDialog', () => {
  it('отправляет PATCH только с изменёнными полями, parent_slug — явно', async () => {
    patch.mockResolvedValue({ data: { ...htq, kind: 'construction', parent_slug: 'hi-tech-group', country: 'KZ' } });
    const onSaved = vi.fn();
    renderWithProviders(
      <CompanyFormDialog company={htq} candidates={[group, htq]} open onOpenChange={() => {}} onSaved={onSaved} />,
    );
    await userEvent.selectOptions(screen.getByLabelText(/Вид/), 'construction');
    await userEvent.selectOptions(screen.getByLabelText(/Вышестоящая/), 'hi-tech-group');
    await userEvent.type(screen.getByLabelText(/Страна/), 'KZ');
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/ }));

    expect(patch).toHaveBeenCalledWith('hi-tech-qazaqstan',
      { kind: 'construction', parent_slug: 'hi-tech-group', country: 'KZ' });
    expect(onSaved).toHaveBeenCalled();
  });

  it('не предлагает саму компанию в качестве родителя', () => {
    renderWithProviders(
      <CompanyFormDialog company={htq} candidates={[group, htq]} open onOpenChange={() => {}} onSaved={() => {}} />,
    );
    const options = Array.from((screen.getByLabelText(/Вышестоящая/) as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(['', 'hi-tech-group']);
  });
});
