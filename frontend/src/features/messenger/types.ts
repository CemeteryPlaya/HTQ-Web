/**
 * Messenger feature — TypeScript types
 */

/** What `/api/messenger/v1/users/{me,search}` actually returns is the platform
 * user brief (`apps.users.interface.list_users_brief`): `id`, `username`,
 * `email`, `first_name`, `last_name`, `full_name`, `is_active`. Everything
 * below that isn't in that list is optional — it came from the retired
 * `ChatUserReplica` and is simply absent today. In particular there is no
 * `user_id` alias: always read the numeric id via `uidOf()`. */
export interface ChatUser {
    id: number;
    user_id?: number;
    username: string;
    full_name: string;
    email?: string | null;
    first_name?: string;
    last_name?: string;
    is_active?: boolean;
    avatar_url?: string;
    department_path?: string;
    department_name?: string;
    position_title?: string;
    is_online?: boolean;
    last_seen?: string;
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

/** Snapshot of the quoted message, stored server-side at send time
 *  (metadata_json.reply_to) — survives deletion/edits of the original. */
export interface ReplySnapshot {
    id: string;
    sender_id: number | null;
    sender_name?: string | null;
    preview: string;
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
    reply_to?: ReplySnapshot | null;
    is_edited: boolean;
    /** Tombstone: the author (or a group admin) removed it. Content and
     *  attachments arrive blanked; the admin view still sees the original. */
    is_deleted?: boolean;
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
    /** Id of the message being quoted — the backend builds the snapshot. */
    reply_to?: string | null;
}

export interface PresenceEntry {
    online: boolean;
    last_seen: string | null;
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
