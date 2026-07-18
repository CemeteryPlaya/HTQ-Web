import React, { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, startOfMonth, endOfMonth } from 'date-fns';
import { fetchCalendarTimeline } from '@/api/calendar';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';
import { Video } from 'lucide-react';

export const ConferenceNotifier = () => {
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
                    try {
                        // Using a simple oscillator for a "pleasant ding" without needing external assets
                        const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
                        const oscillator = audioCtx.createOscillator();
                        const gainNode = audioCtx.createGain();
                        
                        oscillator.type = 'sine';
                        // A pleasant chime chord
                        oscillator.frequency.setValueAtTime(523.25, audioCtx.currentTime); // C5
                        oscillator.frequency.exponentialRampToValueAtTime(1046.50, audioCtx.currentTime + 0.5); // C6
                        
                        gainNode.gain.setValueAtTime(0, audioCtx.currentTime);
                        gainNode.gain.linearRampToValueAtTime(0.3, audioCtx.currentTime + 0.1);
                        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 1.5);
                        
                        oscillator.connect(gainNode);
                        gainNode.connect(audioCtx.destination);
                        
                        oscillator.start();
                        oscillator.stop(audioCtx.currentTime + 1.5);
                    } catch (e) {
                        console.error("Audio playback failed", e);
                    }

                    // Show toast notification
                    toast('🎥 Конференция начинается', {
                        description: `«${ev.title}» начнётся через 5 минут.`,
                        duration: 30000, // 30 seconds
                        action: {
                            label: 'Войти',
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
    }, [timeline, isAuth, navigate]);

    return null; // This is a logic-only component
};
