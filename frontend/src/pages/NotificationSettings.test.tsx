import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import NotificationSettings from './NotificationSettings';

const savePrefs = vi.fn();
vi.mock('@/api/notifications', () => ({
  notificationsApi: {
    prefs: () =>
      Promise.resolve({ data: { bell: true, email: false, telegram: false, telegram_linked: false } }),
    savePrefs: (body: unknown) => savePrefs(body),
    linkTelegram: vi.fn(),
  },
}));

describe('NotificationSettings', () => {
  it('не даёт выключить последний канал', async () => {
    renderWithProviders(<NotificationSettings />);
    const bell = await screen.findByRole('switch', { name: /колокольчик/i });
    expect(bell).toBeDisabled();
  });

  it('сохраняет переключение канала', async () => {
    savePrefs.mockResolvedValue({ data: { bell: true, email: true, telegram: false, telegram_linked: false } });
    renderWithProviders(<NotificationSettings />);
    await userEvent.click(await screen.findByRole('switch', { name: /e-mail/i }));
    expect(savePrefs).toHaveBeenCalledWith({ email: true });
  });

  it('Telegram без привязанного чата включить нельзя — сначала подключить', async () => {
    renderWithProviders(<NotificationSettings />);
    expect(await screen.findByRole('switch', { name: /telegram/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /подключить telegram/i })).toBeInTheDocument();
  });
});
