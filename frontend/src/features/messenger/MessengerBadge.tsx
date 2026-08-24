/**
 * MessengerBadge — unread-messages indicator for the global header.
 *
 * Two jobs, both of which only make sense outside the messenger page:
 *   • show the number of unread messages across every visible chat, and
 *   • raise a desktop notification when one arrives while the user is
 *     somewhere else in the app.
 *
 * The count comes from `GET /messages/unread-count` (the same math the chat
 * list uses, summed server-side). It is re-fetched on the `message_new` /
 * `message_read` socket events, so it tracks in near-real-time; the slow
 * interval below is only a safety net for missed events.
 *
 * Notifications are deliberately conservative: no permission prompt on load
 * (browsers penalise that), we only ask the first time the user actually
 * clicks the badge. Nothing is shown while the messenger page is open — the
 * message is already on screen there.
 */
import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { MessageCircle } from 'lucide-react';

import { messengerApi } from './api/messengerApi';
import { getMessengerSocket } from './api/socket';
import { getAccessToken } from '@/lib/auth/profileStorage';
import { useTranslation } from 'react-i18next';

export const MessengerBadge = () => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();
    const location = useLocation();
    const onMessengerPage = location.pathname.startsWith('/messenger');
    const notifiedRef = useRef<Set<string>>(new Set());

    const { data } = useQuery({
        queryKey: ['messenger-unread-total'],
        queryFn: messengerApi.getUnreadCount,
        enabled: Boolean(getAccessToken()),
        refetchInterval: 120_000,
        retry: false,
    });
    const total = data?.total ?? 0;

    useEffect(() => {
        if (!getAccessToken()) return;
        const socket = getMessengerSocket();

        const refresh = () =>
            queryClient.invalidateQueries({ queryKey: ['messenger-unread-total'] });

        const onNew = (payload: { room_id: number; message?: Record<string, unknown> }) => {
            refresh();
            if (onMessengerPage) return;
            if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;

            // The socket fans a message out to both the room channel and each
            // participant's personal channel, so the same id can arrive twice.
            const msg = payload.message ?? {};
            const id = String(msg.id ?? '');
            if (id && notifiedRef.current.has(id)) return;
            if (id) notifiedRef.current.add(id);

            const sender = msg.sender as { full_name?: string; username?: string } | null | undefined;
            let body = '';
            try {
                body = JSON.parse(String(msg.content ?? '{}')).text || '';
            } catch {
                body = '';
            }
            new Notification(sender?.full_name || sender?.username || t('messenger.newMessage'), {
                body: body || t('messenger.attachment'),
                tag: `messenger-room-${payload.room_id}`,
            });
        };

        socket.on('message_new', onNew);
        socket.on('message_read', refresh);
        return () => {
            socket.off('message_new', onNew);
            socket.off('message_read', refresh);
        };
    }, [queryClient, onMessengerPage, t]);

    if (!getAccessToken()) return null;

    return (
        <Link
            to="/messenger"
            onClick={() => {
                if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
                    Notification.requestPermission().catch(() => { /* пользователь отказал */ });
                }
            }}
            className="relative inline-flex h-10 w-10 items-center justify-center rounded-full transition-colors hover:bg-accent hover:text-accent-foreground"
            title={total > 0 ? t('messenger.unreadCount', { total }) : t('profile.sidebar.messenger')}
        >
            <MessageCircle className="w-5 h-5" />
            {total > 0 && (
                <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold tabular-nums">
                    {total > 99 ? '99+' : total}
                </span>
            )}
        </Link>
    );
};
