/**
 * Показ уведомлений: карточка в правом нижнем углу, звук и — когда человек
 * ушёл из вкладки — уведомление операционной системы.
 *
 * Живёт в `App.tsx`, а не в колокольчике шапки, где этот код был раньше. Так
 * получилось не из любви к слоям: колокольчик монтируется ВНУТРИ `Header`, и
 * уведомления не приходили ни на страницах без шапки (например, файлы отдела),
 * ни в первые 1200 мс, пока шапка откладывает второстепенные кнопки. Показ
 * уведомлений не должен зависеть от того, какая на странице обвязка.
 *
 * Компонент ничего не рисует сам: карточки рисует `<Toaster/>` рядом в
 * `App.tsx`, и до его монтирования здесь не делается ВООБЩЕ ничего — см.
 * `lib/notifications/toastHost.ts`, там же вся история про «звук есть,
 * уведомления нет».
 *
 * Запрос тот же (`['notifications']`), что и у колокольчика: react-query
 * держит один кэш на ключ, поэтому сеть от этого не удваивается.
 */
import React, { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
    fetchNotifications,
    formatNotificationText,
    markNotificationRead,
    notificationSourceLabel,
    notificationTargetUrl,
} from '@/api/tasks';
import { MessengerToast } from '@/components/MessengerToast';
import { playNotificationSound } from '@/lib/sound/soundService';
import { useToastHostMounted } from '@/lib/notifications/toastHost';
import {
    pageIsInBackground,
    showDesktopNotification,
} from '@/lib/notifications/desktop';

/** Уже показанные уведомления. Список в localStorage, а не в памяти, чтобы:
 *   - карточки не всплывали заново при каждом переходе по страницам;
 *   - и не всплывали повторно после перезагрузки вкладки;
 *   - но при этом уведомление, которое ещё НЕ показывали — включая пришедшие
 *     до открытия платформы, — карточку всё-таки получило. */
const SEEN_KEY = 'htq:notif:toasted';

const readSeen = (): Set<string> => {
    try {
        const raw = localStorage.getItem(SEEN_KEY);
        if (!raw) return new Set();
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return new Set();
        return new Set(parsed.map(String));
    } catch {
        return new Set();
    }
};

const writeSeen = (set: Set<string>) => {
    try {
        // Ограничиваем список, иначе localStorage растёт без предела.
        const arr = Array.from(set).slice(-500);
        localStorage.setItem(SEEN_KEY, JSON.stringify(arr));
    } catch {
        /* приватный режим / переполнение — не беда */
    }
};

export const NotificationToasts: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const toastHostMounted = useToastHostMounted();

    // Опрос раз в 30 секунд: именно он приносит уведомления, созданные, пока
    // страница открыта.
    const { data: notifications = [] } = useQuery({
        queryKey: ['notifications'],
        queryFn: fetchNotifications,
        refetchInterval: 30 * 1000,
    });

    const markReadMutation = useMutation({
        mutationFn: markNotificationRead,
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
    });

    useEffect(() => {
        if (notifications.length === 0) return;
        // Приёмника тостов ещё нет — не трогаем НИЧЕГО: ни звука, ни отметки
        // «показано». sonner не копит отправленное, поэтому выпущенная сейчас
        // карточка исчезла бы бесследно, а id уже считался бы показанным — и
        // уведомление не всплыло бы никогда. Эффект перезапустится сам, как
        // только приёмник появится: он в зависимостях.
        if (!toastHostMounted) return;

        const seen = readSeen();
        for (const n of notifications) {
            const key = String(n.id);
            if (seen.has(key)) continue;
            // Записываем ДО показа. В режиме StrictMode эффект в разработке
            // выполняется дважды, и второй проход прочитал бы снимок
            // localStorage, сделанный до `seen.add`, — то есть показал бы то же
            // уведомление второй раз. Запись первой закрывает этот проход.
            seen.add(key);
            writeSeen(seen);

            // Прочитанное не показываем: скорее всего, человек прочитал его на
            // другом устройстве. Id выше всё равно записан, чтобы карточка не
            // всплыла при следующей загрузке.
            if (n.is_read) continue;

            const source = notificationSourceLabel(n);
            const body = formatNotificationText(n);
            const title = n.actor_name ? `${n.actor_name} ${body}` : body;
            const url = notificationTargetUrl(n);
            playNotificationSound(n);

            // Человек сейчас не на странице (свернул окно, ушёл в другую
            // программу или вкладку) — карточку в углу СТРАНИЦЫ он не увидит,
            // а звук услышит. Дублируем уведомлением операционной системы: оно
            // показывается в правом нижнем углу ЭКРАНА поверх всего.
            //
            // `tag` для чатов — тот же, что у MessengerBadge: одно сообщение
            // приходит и сокетом, и опросом уведомлений, и без общего ключа
            // система показала бы два уведомления об одном и том же.
            if (pageIsInBackground()) {
                showDesktopNotification({
                    title: n.actor_name || source || t('notifications.title'),
                    body,
                    tag:
                        n.target_type === 'messenger_room' && n.target_id
                            ? `messenger-room-${n.target_id}`
                            : `htq-notification-${n.id}`,
                    onClick: url
                        ? () => {
                              markReadMutation.mutate(n.id);
                              navigate(url);
                          }
                        : undefined,
                });
            }

            // У сообщений из чата своя вёрстка (аватар, две строки текста,
            // время). Остальные типы читаются лучше обычным тостом sonner:
            // заголовок и подпись.
            if (n.target_type === 'messenger_room') {
                toast.custom(
                    (toastId) => (
                        <MessengerToast
                            toastId={toastId}
                            notification={n}
                            onClick={() => {
                                markReadMutation.mutate(n.id);
                                toast.dismiss(toastId);
                                if (url) navigate(url);
                            }}
                        />
                    ),
                    { id: `notif-${n.id}`, duration: 8000 },
                );
                continue;
            }

            toast(title, {
                id: `notif-${n.id}`,
                description: source ? t('notifications.toastSource', { source }) : undefined,
                duration: 8000,
                action: url
                    ? {
                          label: t('common.open'),
                          onClick: () => {
                              markReadMutation.mutate(n.id);
                              navigate(url);
                          },
                      }
                    : undefined,
            });
        }
    }, [notifications, toastHostMounted, markReadMutation, navigate, t]);

    return null;
};

export default NotificationToasts;
