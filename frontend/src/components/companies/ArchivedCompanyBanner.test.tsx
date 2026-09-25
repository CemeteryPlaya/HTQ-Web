/** Баннер «компания в архиве — только чтение» (спека архива §7.2). */
import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ArchivedCompanyBanner } from './ArchivedCompanyBanner';

const permissions = vi.fn();
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

describe('ArchivedCompanyBanner', () => {
  it('виден в архивной компании', () => {
    permissions.mockReturnValue({ companyArchived: true });
    renderWithProviders(<ArchivedCompanyBanner />);
    expect(screen.getByRole('status')).toHaveTextContent('Компания в архиве — только чтение');
  });

  it('скрыт в действующей компании', () => {
    permissions.mockReturnValue({ companyArchived: false });
    renderWithProviders(<ArchivedCompanyBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
