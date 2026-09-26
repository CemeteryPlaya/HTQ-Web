/**
 * NotificationSettings — каналы уведомлений пользователя (/settings/notifications).
 *
 * Колокольчик, e-mail, Telegram (ТЗ §22, центр уведомлений `apps.notifications`).
 * Хотя бы один канал остаётся включённым: переключатель последнего включённого
 * заблокирован, сервер то же правило проверяет сам (422 `E-NTF-01`). Telegram
 * включается только после привязки чата — иначе доставки молча пропускались бы.
 */
import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Bell, Mail, Send } from 'lucide-react';

import {
  notificationsApi,
  type NotificationPrefs,
  type NotificationPrefsPatch,
} from '@/api/notifications';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { BackToProfile } from '@/components/BackToProfile';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { reportApiError } from '@/lib/apiError';

type Channel = 'bell' | 'email' | 'telegram';

const QUERY_KEY = ['notifications', 'prefs'];

export default function NotificationSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: prefs, isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => (await notificationsApi.prefs()).data,
  });

  const save = useMutation({
    mutationFn: async (body: NotificationPrefsPatch) => (await notificationsApi.savePrefs(body)).data,
    onSuccess: (next: NotificationPrefs) => queryClient.setQueryData(QUERY_KEY, next),
    onError: (error) => reportApiError(error, t('notifications.settings.saveError', 'Не удалось сохранить настройки')),
  });

  const link = useMutation({
    mutationFn: async () => (await notificationsApi.linkTelegram()).data,
    onSuccess: ({ url }) => {
      window.open(url, '_blank', 'noopener,noreferrer');
    },
    onError: (error) => reportApiError(error, t('notifications.settings.linkError', 'Не удалось получить ссылку на бота')),
  });

  const enabledCount = prefs ? [prefs.bell, prefs.email, prefs.telegram].filter(Boolean).length : 0;

  const rows: { key: Channel; icon: React.ElementType; label: string; hint: string }[] = [
    {
      key: 'bell',
      icon: Bell,
      label: t('notifications.settings.bell', 'Колокольчик'),
      hint: t('notifications.settings.bellHint', 'Уведомления в шапке портала'),
    },
    {
      key: 'email',
      icon: Mail,
      label: t('notifications.settings.email', 'E-mail'),
      hint: t('notifications.settings.emailHint', 'Письмо на рабочую почту'),
    },
    {
      key: 'telegram',
      icon: Send,
      label: t('notifications.settings.telegram', 'Telegram'),
      hint: t('notifications.settings.telegramHint', 'Сообщение от бота портала'),
    },
  ];

  const isLocked = (key: Channel): boolean => {
    if (!prefs) return true;
    if (key === 'telegram' && !prefs.telegram_linked && !prefs.telegram) return true;
    // Выключить последний включённый канал нельзя.
    return prefs[key] && enabledCount <= 1;
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto py-8 px-4 max-w-2xl">
        <BackToProfile className="mb-4" />
        <h1 className="text-3xl font-bold tracking-tight mb-2">
          {t('notifications.settings.title', 'Настройки уведомлений')}
        </h1>
        <p className="text-muted-foreground mb-6">
          {t('notifications.settings.subtitle', 'Как получать уведомления. Хотя бы один способ остаётся включённым.')}
        </p>

        {isLoading || !prefs ? (
          <p className="text-muted-foreground">{t('common.loading', 'Загрузка…')}</p>
        ) : (
          <div className="bg-card rounded-2xl border divide-y">
            {rows.map(({ key, icon: Icon, label, hint }) => (
              <div key={key} className="flex items-center justify-between gap-4 p-4">
                <div className="flex items-start gap-3 min-w-0">
                  <Icon className="h-5 w-5 mt-0.5 text-primary shrink-0" />
                  <div className="min-w-0">
                    <div className="font-medium">{label}</div>
                    <div className="text-sm text-muted-foreground">{hint}</div>
                    {key === 'telegram' && !prefs.telegram_linked && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-2"
                        onClick={() => link.mutate()}
                        disabled={link.isPending}
                      >
                        {t('notifications.settings.linkTelegram', 'Подключить Telegram')}
                      </Button>
                    )}
                  </div>
                </div>
                <Switch
                  aria-label={label}
                  checked={prefs[key]}
                  disabled={isLocked(key) || save.isPending}
                  onCheckedChange={(checked) => save.mutate({ [key]: checked })}
                />
              </div>
            ))}
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
}
