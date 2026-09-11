import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckSquare, MessageSquare, AlertCircle, History, Calendar, Briefcase, UserSquare, Mail } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    fetchNotifications,
    formatNotificationText,
    markNotificationRead,
    markAllNotificationsRead,
    notificationSourceLabel,
    notificationTargetUrl,
} from '@/api/tasks';
import { requestDesktopPermission } from '@/lib/notifications/desktop';
import { SoundSettingsModal } from '@/components/sound/SoundSettingsModal';
import { Volume2 } from 'lucide-react';
// Именно тип уведомления платформы. Без импорта `Notification` — это
// одноимённый тип браузерного API из lib.dom, у которого нет ни `target_type`,
// ни `verb`: подсказки в редакторе врали, а проверка типов молча ругалась.
import type { Notification } from '@/types/tasks';

/** Icon to show on the left side of each notification, picked from the
 *  source type. Calendar / Task / HR / fallback. */
const iconFor = (n: Notification) => {
    if (n.target_type === 'calendar_event') return Calendar;
    if (n.target_type === 'task' || n.task) return Briefcase;
    if (n.target_type === 'employee') return UserSquare;
    if (n.target_type === 'messenger_room') return MessageSquare;
    if (n.target_type === 'email_message') return Mail;
    if ((n.verb || '').includes('комментарий')) return MessageSquare;
    return AlertCircle;
};

const colorFor = (n: Notification): string => {
    if (n.target_type === 'calendar_event') return 'text-emerald-500';
    if (n.target_type === 'task' || n.task) return 'text-orange-500';
    if (n.target_type === 'employee') return 'text-purple-500';
    if (n.target_type === 'messenger_room') return 'text-cyan-500';
    if (n.target_type === 'email_message') return 'text-rose-500';
    return 'text-blue-500';
};

export const NotificationsViewer: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [isOpen, setIsOpen] = useState(false);

    // Тот же ключ, что у NotificationToasts: react-query держит один кэш на
    // ключ, поэтому второго опроса сети от этого не возникает.
    const { data: notifications = [] } = useQuery({
        queryKey: ['notifications'],
        queryFn: fetchNotifications,
        refetchInterval: 30 * 1000,
    });

    const unreadCount = notifications.filter(n => !n.is_read).length;
    // Show max 10 notifications in dropdown
    const topNotifications = notifications.slice(0, 10);

    const markReadMutation = useMutation({
        mutationFn: markNotificationRead,
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
    });

    const markAllReadMutation = useMutation({
        mutationFn: markAllNotificationsRead,
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
    });

    const handleNotificationClick = (notif: any) => {
        if (!notif.is_read) markReadMutation.mutate(notif.id);
        setIsOpen(false);
        const url = notificationTargetUrl(notif);
        if (url) {
            navigate(url);
        }
    };

    // Показ карточек, звук и уведомления ОС живут не здесь, а в
    // `NotificationToasts` (смонтирован в App.tsx). Колокольчик — только
    // счётчик и список: пока показ был внутри него, уведомления не приходили на
    // страницах без шапки и в первые секунды после загрузки.

    return (
        <DropdownMenu
            open={isOpen}
            onOpenChange={(open) => {
                setIsOpen(open);
                // Разрешение на уведомления ОС спрашиваем только здесь — на
                // жесте, которым человек сам открыл список уведомлений. Спросить
                // при загрузке страницы значило бы почти гарантированно получить
                // «Блокировать», а это решение из кода уже не отменить.
                if (open) requestDesktopPermission();
            }}
        >
            <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="relative h-9 w-9">
                    <Bell className="h-5 w-5" />
                    {unreadCount > 0 && (
                        <span className="absolute top-1 right-1 h-2.5 w-2.5 rounded-full bg-red-500 border-2 border-background animate-pulse" />
                    )}
                </Button>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="end" className="w-80 max-h-[85vh] overflow-y-auto">
                <div className="flex items-center justify-between px-2 py-2">
                    <DropdownMenuLabel className="p-0">{t('notifications.title')}</DropdownMenuLabel>
                    {unreadCount > 0 && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-auto p-0 text-xs text-primary hover:bg-transparent hover:underline"
                            onClick={() => markAllReadMutation.mutate()}
                        >
                            {t('notifications.markAllRead')}
                        </Button>
                    )}
                </div>
                <DropdownMenuSeparator />

                {topNotifications.length === 0 ? (
                    <div className="py-6 text-center text-sm text-muted-foreground flex flex-col items-center gap-2">
                        <CheckSquare className="h-8 w-8 text-muted-foreground/30" />
                        <p>{t('notifications.empty')}</p>
                    </div>
                ) : (
                    <div className="flex flex-col gap-1 px-1 py-1">
                        {topNotifications.map(n => {
                            const Icon = iconFor(n);
                            const source = notificationSourceLabel(n);
                            // Есть ли куда вести. Уведомление без цели не должно
                            // притворяться нажимаемым: курсор-указатель и
                            // закрывающееся меню обещают переход, которого не
                            // будет, и человек решает, что интерфейс сломан.
                            const targetUrl = notificationTargetUrl(n);
                            return (
                                <DropdownMenuItem
                                    key={n.id}
                                    className={`flex flex-col items-start gap-1 p-3 ${targetUrl ? 'cursor-pointer' : 'cursor-default'} ${!n.is_read ? 'bg-primary/5 font-medium' : 'opacity-80'}`}
                                    // Без цели меню не закрываем: отметить
                                    // прочитанным полезно, а закрытие выглядело
                                    // бы как неудавшийся переход.
                                    onSelect={(event) => { if (!targetUrl) event.preventDefault(); }}
                                    onClick={() => handleNotificationClick(n)}
                                >
                                    <div className="flex items-center gap-2 w-full">
                                        <Icon className={`h-4 w-4 shrink-0 ${colorFor(n)}`} />
                                        <span className="text-sm truncate w-full">
                                            {n.actor_name && (
                                                <strong className="text-primary">{n.actor_name} </strong>
                                            )}
                                            {formatNotificationText(n)}
                                        </span>
                                        {!n.is_read && <span className="h-2 w-2 rounded-full bg-primary shrink-0 ml-auto" />}
                                    </div>
                                    <div className="flex items-center gap-2 ml-6">
                                        {source && (
                                            <Badge variant="outline" className="h-4 px-1.5 text-[10px]">
                                                {source}
                                                {n.task_key ? ` · ${n.task_key}` : ''}
                                            </Badge>
                                        )}
                                        <span className="text-[10px] text-muted-foreground/70 uppercase">
                                            {new Date(n.created_at).toLocaleString('ru')}
                                        </span>
                                    </div>
                                </DropdownMenuItem>
                            );
                        })}

                        {notifications.length > 10 && (
                            <div className="p-2 text-center text-xs text-muted-foreground">
                                {t('notifications.latestTen')}
                            </div>
                        )}
                    </div>
                )}

                <DropdownMenuSeparator />
                <div className="px-2 py-1 flex items-center justify-between">
                    <SoundSettingsModal
                        trigger={
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5 w-full justify-start font-normal"
                            >
                                <Volume2 className="h-3.5 w-3.5" />
                                <span>{t('sound.settings', 'Настройки звуков')}</span>
                            </Button>
                        }
                    />
                </div>
                <DropdownMenuSeparator />
                <Link
                    to="/notifications"
                    onClick={() => setIsOpen(false)}
                    className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-primary hover:bg-muted/50 transition-colors"
                >
                    <History className="h-4 w-4" />
                    {t('notifications.showHistory')}
                </Link>
            </DropdownMenuContent>
        </DropdownMenu>
    );
};
