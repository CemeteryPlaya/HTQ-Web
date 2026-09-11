import React, { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckSquare, MessageSquare, AlertCircle, History, Calendar, Briefcase, UserSquare, Mail } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
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
import { MessengerToast } from '@/components/MessengerToast';
import { playNotificationSound } from '@/lib/sound/soundService';
import { SoundSettingsModal } from '@/components/sound/SoundSettingsModal';
import { Volume2 } from 'lucide-react';

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

    // Auto-refresh notifications every 30 seconds — toasts depend on this
    // poll to surface freshly-arrived rows shortly after they're created.
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

    // Surface unread notifications as transient toasts in the bottom-right.
    // The "seen" set is persisted to localStorage so:
    //   - toasts survive route changes (NotificationsViewer remounts).
    //   - already-toasted rows don't pop again after a page refresh.
    //   - any notification we haven't toasted yet — INCLUDING ones that
    //     existed when the page was first opened — gets a toast on the
    //     first poll where it's still unread. This is what fixes the case
    //     of "page already open, but no toast appeared".
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
            // Cap stored ids so localStorage doesn't grow unbounded.
            const arr = Array.from(set).slice(-500);
            localStorage.setItem(SEEN_KEY, JSON.stringify(arr));
        } catch {
            /* private mode / quota — ignore */
        }
    };
    useEffect(() => {
        if (notifications.length === 0) return;
        const seen = readSeen();
        for (const n of notifications) {
            const key = String(n.id);
            if (seen.has(key)) continue;
            // Persist BEFORE rendering the toast. React StrictMode mounts
            // this effect twice in development; a second pass would otherwise
            // re-read the localStorage snapshot from before our in-memory
            // ``seen.add`` and toast the same notification twice. Writing
            // first means the second pass already finds the id and skips.
            seen.add(key);
            writeSeen(seen);

            // Don't toast already-read entries — they were probably read
            // on another device, no need to interrupt here. We still record
            // the id above so they don't re-toast on later refresh.
            if (n.is_read) continue;

            const source = notificationSourceLabel(n);
            const body = formatNotificationText(n);
            const title = n.actor_name ? `${n.actor_name} ${body}` : body;
            const url = notificationTargetUrl(n);
            // Play corresponding pleasant sound (debounced internally)
            playNotificationSound(n);

            // Messenger gets a rich layout (avatar + 2-line clamp + time).
            // Other types stay on the default sonner text toast — they read
            // better as a simple title + description.
            if (n.target_type === 'messenger_room') {
                toast.custom(
                    (t) => (
                        <MessengerToast
                            toastId={t}
                            notification={n}
                            onClick={() => {
                                markReadMutation.mutate(n.id);
                                toast.dismiss(t);
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
    }, [notifications, markReadMutation, navigate, t]);

    return (
        <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
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
