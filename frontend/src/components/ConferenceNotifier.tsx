import React, { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, startOfMonth, endOfMonth } from 'date-fns';
import { fetchCalendarTimeline } from '@/api/calendar';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';
import { Video } from 'lucide-react';
import { playMeetingReminder } from '@/lib/sound/soundService';
import { useTranslation } from 'react-i18next';
import { getMessengerSocket } from '@/features/messenger/api/socket';

export const ConferenceNotifier = () => {
    const { t } = useTranslation();
    const { activeProfile } = useActiveProfile();
    const navigate = useNavigate();
    
    // Track notified event IDs to avoid spamming
    const notifiedRef = useRef<Set<number>>(new Set());

    // Only active if logged in
    const isAuth = Boolean(activeProfile);

    // Fetch this month's timeline to find upcoming conferences
    const now = new Date();
    const startDate = startOfMonth(now);
    const endDate = endOfMonth(now);

    const { data: timeline } = useQuery({
        queryKey: ['calendar-timeline', format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')],
        queryFn: () => fetchCalendarTimeline(format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')),
        enabled: isAuth,
        refetchInterval: 60000, // Refetch every minute just in case
    });

    useEffect(() => {
        if (!timeline || !isAuth) return;

        // Responses may temporarily not carry an `events` array. Never crash
        // the whole SPA (this component is mounted globally); just skip.
        const events = Array.isArray(timeline.events) ? timeline.events : [];
        if (events.length === 0) return;

        const checkConferences = () => {
            const currentTime = new Date();

            events.forEach(ev => {
                if (ev.event_type !== 'conference' || !ev.conference_room_id) return;
                
                const startTime = new Date(ev.start_at);
                const timeDiffMs = startTime.getTime() - currentTime.getTime();
                const timeDiffMinutes = timeDiffMs / 1000 / 60;

                // If the conference starts in exactly 5 minutes (allowing a 1-minute checking window)
                if (timeDiffMinutes > 4 && timeDiffMinutes <= 5 && !notifiedRef.current.has(ev.id)) {
                    notifiedRef.current.add(ev.id);
                    
                    // Play a pleasant sound
                    playMeetingReminder();

                    // Show toast notification
                    toast(t('conference.notify.starting'), {
                        description: t('conference.notify.startsSoon', { title: ev.title }),
                        duration: 30000, // 30 seconds
                        action: {
                            label: t('conference.notify.join'),
                            onClick: () => navigate(`/room/${ev.conference_room_id}`),
                        },
                    });
                }
            });
        };

        // Check immediately, then every 30 seconds
        checkConferences();
        const interval = setInterval(checkConferences, 30000);
        
        return () => clearInterval(interval);
    }, [timeline, isAuth, navigate, t]);

    // Канал был готов только наполовину: сервер шлёт «notification» в
    // персональную комнату user:<id> с первого дня, а слушателя во фронте не
    // было ни одного.
    useEffect(() => {
        if (!isAuth) return;
        const socket = getMessengerSocket();

        const onNotification = (raw: unknown) => {
            const payload = raw as { type?: string; title?: string; join_url?: string };
            if (payload?.type !== 'conference_started') return;

            playMeetingReminder();
            toast(t('conference.notify.started', 'Видеоконференция началась'), {
                description: payload.title,
                duration: 30000,
                action: {
                    label: t('conference.notify.join'),
                    onClick: () => navigate(payload.join_url || '/conference'),
                },
            });

            // Системное уведомление — чтобы встречу заметили при свёрнутой
            // вкладке. Разрешение спрашиваем ЗДЕСЬ, а не на входе в приложение:
            // просьба, которой человек не ждал, почти всегда отклоняется.
            //
            // show() защищена своим собственным try/catch, а не общим для
            // всей ветки: вызов из .then() исполняется уже ПОСЛЕ того, как
            // окружающий try завершился, — бросок конструктора Notification
            // там наружный catch не поймает, он уйдёт необработанным
            // отклонением промиса. Поэтому обе точки вызова show() защищены
            // отдельно, симметрично.
            const show = () => {
                try {
                    new Notification(
                        t('conference.notify.started', 'Видеоконференция началась'),
                        { body: payload.title || '' });
                } catch {
                    // Браузер вправе запретить/бросить — это не причина
                    // ронять компонент, смонтированный на всё приложение.
                }
            };
            try {
                if (typeof Notification === 'undefined') return;
                if (Notification.permission === 'granted') show();
                else if (Notification.permission === 'default') {
                    Notification.requestPermission().then((granted) => {
                        if (granted === 'granted') show();
                    }).catch(() => {
                        // Запрос разрешения тоже вправе отклониться/упасть.
                    });
                }
            } catch {
                // Браузер вправе запретить — это не причина ронять компонент,
                // смонтированный на всё приложение.
            }
        };

        socket.on('notification', onNotification);
        return () => { socket.off('notification', onNotification); };
    }, [isAuth, navigate, t]);

    return null; // This is a logic-only component
};
