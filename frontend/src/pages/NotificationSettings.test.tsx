import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import NotificationSettings from './NotificationSettings';

const savePrefs = vi.fn();
const prefs = vi.hoisted(() => ({
  value: { bell: true, email: false, telegram: false, telegram_linked: false, telegram_available: true },
}));
vi.mock('@/api/notifications', () => ({
  notificationsApi: {
    prefs: () => Promise.resolve({ data: prefs.value }),
    savePrefs: (body: unknown) => savePrefs(body),
    linkTelegram: vi.fn(),
  },
}));

describe('NotificationSettings', () => {
  it('колокольчик выключить нельзя', async () => {
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

  it('без настроенного бота кнопки подключения нет', async () => {
    prefs.value = { ...prefs.value, telegram_available: false };
    renderWithProviders(<NotificationSettings />);
    expect(await screen.findByText(/бот портала пока не настроен/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /подключить telegram/i })).toBeNull();
    prefs.value = { ...prefs.value, telegram_available: true };
  });

  it('Telegram без привязанного чата включить нельзя — сначала подключить', async () => {
    renderWithProviders(<NotificationSettings />);
    expect(await screen.findByRole('switch', { name: /telegram/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /подключить telegram/i })).toBeInTheDocument();
  });
});
