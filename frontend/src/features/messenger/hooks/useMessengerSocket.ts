/**
 * useMessengerSocket — subscribes to messenger socket.io events and refreshes
 * React Query caches in response. Drops REST polling to a slow heartbeat
 * because socket events provide real-time deltas.
 *
 * Usage:
 *   const socket = useMessengerSocket(activeRoomId);
 *   socket.emitTyping(true);
 */

import { useEffect, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import {
    getMessengerSocket,
    type MessageNewPayload,
    type MessageReadPayload,
    type UserTypingPayload,
} from '../api/socket';

/** Shared presence cache: `['messenger-presence']` → Record<userId, …>.
 *  Seeded by the REST bulk query in MessengerPage, patched live by the
 *  user_online / user_offline socket events below. */
export type PresenceMap = Record<number, { online: boolean; last_seen: string | null }>;

interface MessengerSocketApi {
    emitTyping: (isTyping: boolean) => void;
}


export function useMessengerSocket(activeRoomId: number | null): MessengerSocketApi {
    const queryClient = useQueryClient();

    useEffect(() => {
        const socket = getMessengerSocket();

        const handleNewMessage = (payload: MessageNewPayload) => {
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', payload.room_id] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        };
        const handleMessageRead = (payload: MessageReadPayload) => {
            // Two query keys are affected by a read receipt:
            //   • ``messenger-messages`` — message rows can carry a ``read_by``
            //     field (today only computed on full re-fetch).
            //   • ``messenger-rooms``    — ``RoomParticipant.last_read_message_id``
            //     lives here, and the green-double-check logic on the sender's
            //     side reads it via ``activeRoom.participants[i].last_read_*``.
            //     Without invalidating this key the receipts never re-render
            //     in real-time even though the WS event arrived.
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', payload.room_id] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        };
        const handleUserTyping = (_payload: UserTypingPayload) => {
            // Presence hint — components can opt-in later. No cache invalidation.
        };
        // Edited/deleted arrive with the same cache footprint as a new
        // message: the row itself + the room list (last_message preview).
        const handleMessageChanged = (payload: { room_id: number }) => {
            queryClient.invalidateQueries({ queryKey: ['messenger-messages', payload.room_id] });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        };
        // Membership/name changes. Delivered to the PERSONAL channel (a just-
        // added participant isn't subscribed to the room channel yet), so we
        // also join the room right away — without waiting for a reconnect.
        const handleRoomUpdated = (payload: { room_id: number }) => {
            socket.emit('join_room', { room_id: payload.room_id });
            queryClient.invalidateQueries({ queryKey: ['messenger-rooms'] });
        };
        const patchPresence = (userId: number, online: boolean, lastSeen: string | null) => {
            queryClient.setQueryData<PresenceMap>(['messenger-presence'], (prev) => ({
                ...(prev ?? {}),
                [userId]: { online, last_seen: lastSeen },
            }));
        };
        const handleUserOnline = (p: { user_id: number }) => patchPresence(p.user_id, true, null);
        const handleUserOffline = (p: { user_id: number; last_seen?: string }) =>
            patchPresence(p.user_id, false, p.last_seen ?? new Date().toISOString());

        socket.on('message_new', handleNewMessage);
        socket.on('message_read', handleMessageRead);
        socket.on('user_typing', handleUserTyping);
        socket.on('message_edited', handleMessageChanged);
        socket.on('message_deleted', handleMessageChanged);
        socket.on('room_updated', handleRoomUpdated);
        socket.on('user_online', handleUserOnline);
        socket.on('user_offline', handleUserOffline);

        return () => {
            socket.off('message_new', handleNewMessage);
            socket.off('message_read', handleMessageRead);
            socket.off('user_typing', handleUserTyping);
            socket.off('message_edited', handleMessageChanged);
            socket.off('message_deleted', handleMessageChanged);
            socket.off('room_updated', handleRoomUpdated);
            socket.off('user_online', handleUserOnline);
            socket.off('user_offline', handleUserOffline);
        };
    }, [queryClient]);

    useEffect(() => {
        if (activeRoomId == null) return;
        const socket = getMessengerSocket();
        socket.emit('join_room', { room_id: activeRoomId });
        return () => {
            socket.emit('leave_room', { room_id: activeRoomId });
        };
    }, [activeRoomId]);

    return useMemo<MessengerSocketApi>(
        () => ({
            emitTyping: (isTyping: boolean) => {
                if (activeRoomId == null) return;
                getMessengerSocket().emit('typing', { room_id: activeRoomId, is_typing: isTyping });
            },
        }),
        [activeRoomId],
    );
}
