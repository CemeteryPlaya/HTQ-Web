/**
 * Messenger feature — TypeScript types
 */

export interface ChatUser {
    id: number;
    user_id: number;
    username: string;
    full_name: string;
    avatar_url: string;
    department_path: string;
    department_name: string;
    position_title: string;
    is_online: boolean;
    last_seen: string;
    /** True for system bots (Календарь / Задачи / Почта / Файлы / Новости).
     * Frontend renders a BOT badge and pins these DMs to the top of the
     * chat list. */
    is_bot?: boolean;
}

export interface ChatMembership {
    id: number;
    user: ChatUser;
    role: 'member' | 'admin' | 'owner';
    local_pts: number;
    unread_count: number;
    is_muted: boolean;
    is_pinned: boolean;
    joined_at: string;
    last_read_at: string | null;
}

export interface ChatMessage {
    id: number | string;
    room?: number;
    room_id?: number;
    sender_id?: number | null;
    sender: ChatUser | null;
    msg_type?: 'text' | 'file' | 'system' | 'key_exchange';
    content?: string;
    is_encrypted?: boolean;
    encrypted_data?: string; // base64
    msg_key_b64?: string;    // base64
    pts?: number;
    pts_count?: number;
    seq_no: number | null;
    reply_to: number | null;
    is_edited: boolean;
    created_at: string;
    attachments?: ChatAttachment[];
    // Client-side decoded content (after decryption or direct decode)
    _decoded_text?: string;
}

export interface ChatRoom {
    id: number;
    storage_key?: string;
    room_type: 'direct' | 'group' | 'secret';
    name?: string;
    is_e2ee: boolean;
    participants: ChatMembership[];
    last_message: ChatMessage | null;
    created_at: string;
    updated_at: string;
}

export interface CreateRoomPayload {
    room_type: 'direct' | 'group' | 'secret';
    title?: string;
    member_user_ids: number[];
    /** Optional group avatar (signed messenger-service URL). */
    avatar_url?: string | null;
}

export interface UpdateRoomPayload {
    name?: string | null;
    avatar_url?: string | null;
}

export interface SendMessagePayload {
    room_id: number;
    content: string;
    is_encrypted?: boolean;
    metadata_json?: any;
    attachment_ids?: string[];
}

export interface ChatAttachment {
    id: string;
    room_id: number;
    message_id?: string | null;
    file_metadata_id?: string | null;
    filename: string;
    size: number;
    content_type: string;
    data_type: 'images' | 'audio' | 'video' | 'documents' | 'archives' | 'other' | string;
    url: string;
    /** Signed redirect to a ≤ 256×256 WebP thumbnail. ``null`` for non-image
     * attachments or rows uploaded before migration 006_chat_attachment_thumbs.
     * UI must fall back to ``url`` (or a kind-specific icon) when missing. */
    thumbnail_url?: string | null;
    /** Intrinsic pixel size of the original image — used to reserve
     * ``aspect-ratio`` space so the chat bubble doesn't jump on load. */
    width?: number | null;
    height?: number | null;
    created_at: string;
}

// WebSocket incoming message types
export type WsIncoming =
    | { type: 'new_message';[key: string]: any }
    | { type: 'user_typing'; user_id: number; full_name: string }
    | { type: 'read_receipt'; user_id: number; pts: number };
