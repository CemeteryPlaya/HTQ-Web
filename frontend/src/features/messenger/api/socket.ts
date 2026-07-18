/**
 * Messenger Socket.IO client.
 *
 * Connects to messenger-service (proxied by nginx at /ws/messenger/).
 * JWT is supplied via `auth` on handshake; the backend validates it and
 * refuses the connection with `ConnectionRefusedError('unauthorized')`
 * if invalid.
 *
 * Server events (backend → client):
 *   - `message_new`: { room_id, message }
 *   - `message_read`: { room_id, message_id, reader_user_id }
 *   - `user_typing`: { room_id, user_id, is_typing }
 *
 * Client events (client → backend):
 *   - `join_room`: { room_id }
 *   - `leave_room`: { room_id }
 *   - `typing`: { room_id, is_typing }
 *
 * REST endpoints remain the source of truth for persisted state; sockets
 * carry real-time hints that trigger React Query invalidations.
 */

import { io, type Socket } from 'socket.io-client';
import { getAccessToken } from '@/lib/auth/profileStorage';


let socket: Socket | null = null;


export function getMessengerSocket(): Socket {
    if (socket && socket.connected) return socket;
    const token = getAccessToken();
    socket = io('/', {
        path: '/ws/messenger/socket.io',
        transports: ['websocket'],
        auth: token ? { token } : undefined,
        autoConnect: true,
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
    });
    return socket;
}


export function disconnectMessengerSocket(): void {
    if (socket) {
        socket.disconnect();
        socket = null;
    }
}


export interface MessageNewPayload {
    room_id: number;
    message: unknown;
}

export interface MessageReadPayload {
    room_id: number;
    message_id: string;
    reader_user_id: number;
}

export interface UserTypingPayload {
    room_id: number;
    user_id: number;
    is_typing: boolean;
}
