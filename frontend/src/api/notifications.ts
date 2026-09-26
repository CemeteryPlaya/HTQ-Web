/**
 * api/notifications.ts
 * Клиент центра уведомлений (`/api/notifications/v1`): каналы доставки
 * пользователя и привязка Telegram. Лента колокольчика по-прежнему идёт через
 * фасад `/api/tasks/v1/notifications…` (см. `api/tasks.ts`).
 */

import api from './client';
import { apiPath } from './endpoints';

export interface NotificationPrefs {
  bell: boolean;
  email: boolean;
  telegram: boolean;
  /** Чат Telegram привязан — без него канал Telegram не включается. */
  telegram_linked: boolean;
}

export type NotificationPrefsPatch = Partial<Omit<NotificationPrefs, 'telegram_linked'>>;

const path = (suffix: string) => apiPath('notifications', suffix);

export const notificationsApi = {
  prefs: () => api.get<NotificationPrefs>(path('prefs')),
  /** 422 `E-NTF-01` — нельзя выключить все каналы. */
  savePrefs: (body: NotificationPrefsPatch) => api.patch<NotificationPrefs>(path('prefs'), body),
  /** Ссылка на бота с одноразовым кодом (15 минут). */
  linkTelegram: () => api.post<{ url: string }>(path('telegram/link')),
};
