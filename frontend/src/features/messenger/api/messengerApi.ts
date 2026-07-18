/**
 * Messenger API client — isolated from the rest of the app.
 * Uses the shared axios instance for auth token handling.
 */

import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
    ChatUser,
    ChatRoom,
    ChatMessage,
    ChatAttachment,
    CreateRoomPayload,
    SendMessagePayload,
    UpdateRoomPayload,
} from '../types';

const BASE = `${API_ENDPOINTS.messenger}/`;

export const messengerApi = {
    // --- Users ---
    searchUsers: (query: string) =>
        api.get<ChatUser[]>(`${BASE}users/search/`, { params: { q: query } })
            .then(r => r.data),

    getMe: () =>
        api.get<ChatUser>(`${BASE}users/me/`).then(r => r.data),

    // --- Rooms ---
    getRooms: () =>
        api.get<ChatRoom[]>(`${BASE}rooms/`).then(r => r.data),

    createRoom: (payload: CreateRoomPayload) =>
        api.post<ChatRoom>(`${BASE}rooms/`, payload).then(r => r.data),

    getRoom: (roomId: number) =>
        api.get<ChatRoom>(`${BASE}rooms/${roomId}`).then(r => r.data),

    deleteRoom: (roomId: number) =>
        api.delete(`${BASE}rooms/${roomId}`).then(r => r.data),

    updateRoom: (roomId: number, payload: UpdateRoomPayload) =>
        api.patch<ChatRoom>(`${BASE}rooms/${roomId}`, payload).then(r => r.data),

    /** Upload an image and return its signed URL. Used to set a group's avatar
     *  before/after room creation. Attachments are stored alongside chat
     *  messages, so the returned URL works inside <img src> directly. */
    uploadGroupAvatar: (roomId: number, file: File) => {
        const formData = new FormData();
        formData.append('room_id', String(roomId));
        formData.append('file', file);
        return api.post<ChatAttachment>(
            `${BASE}attachments/upload/`,
            formData
        ).then(r => r.data);
    },

    // --- Messages ---
    getMessages: (roomId: number, limit = 50, offset = 0) =>
        api.get<ChatMessage[]>(`${BASE}messages/room/${roomId}`, {
            params: { limit, offset },
        }).then(r => r.data),

    searchMessages: (
        roomId: number,
        opts: { q?: string; data_type?: 'images' | 'audio' | 'documents' | 'video'; since?: string; until?: string; limit?: number; offset?: number } = {},
    ) =>
        api.get<ChatMessage[]>(`${BASE}messages/room/${roomId}`, {
            params: {
                limit: opts.limit ?? 100,
                offset: opts.offset ?? 0,
                ...(opts.q ? { q: opts.q } : {}),
                ...(opts.data_type ? { data_type: opts.data_type } : {}),
                ...(opts.since ? { since: opts.since } : {}),
                ...(opts.until ? { until: opts.until } : {}),
            },
        }).then(r => r.data),

    sendMessage: (payload: SendMessagePayload) =>
        api.post<ChatMessage>(`${BASE}messages/`, payload)
            .then(r => r.data),

    markRead: (roomId: number, messageId: string) =>
        api.post(`${BASE}messages/room/${roomId}/read/${messageId}`),

    // --- Attachments ---
    uploadAttachment: (roomId: number, file: File) => {
        const formData = new FormData();
        formData.append('room_id', String(roomId));
        formData.append('file', file);
        return api.post<ChatAttachment>(
            `${BASE}attachments/upload/`,
            formData
        ).then(r => r.data);
    },

    // --- Key Bundles ---
    getKeyBundle: (userId: number) =>
        api.get(`${BASE}keys/${userId}`).then(r => r.data),

    uploadKeyBundle: (data: {
        identity_pub_key: string;
        signed_prekey: string;
        prekey_signature: string;
    }) => api.post(`${BASE}keys/`, data).then(r => r.data),

    // --- Admin ---
    admin: {
        getAllRooms: () =>
            api.get<ChatRoom[]>(`${BASE}admin/rooms`).then(r => r.data),

        getRoomMessages: (roomId: number, limit = 200, offset = 0) =>
            api.get<ChatMessage[]>(
                `${BASE}admin/rooms/${roomId}/messages`,
                { params: { limit, offset } }
            ).then(r => r.data),
    }
};
